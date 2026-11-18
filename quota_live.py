#!/usr/bin/env python3
"""
Live quota fetchers (read-only, using each CLI's own locally stored login) +
clear quota forecast & 5h / Weekly API dollar equivalent calculator.

- AGY  : Cloud Code Assist POST /v1internal:retrieveUserQuotaSummary + :fetchAvailableModels
- Codex: GET https://chatgpt.com/backend-api/wham/usage (same endpoint the Codex CLI uses)
- Claude Code: ~/.claude/.credentials.json + https://api.anthropic.com/api/oauth/usage
"""

from __future__ import annotations

import datetime
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
AGY_HOME = Path(
    os.environ.get("AGY_HOME", str(Path.home() / ".gemini" / "antigravity-cli"))
).expanduser()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude"))).expanduser()

AGY_BASE = os.environ.get("CLOUD_CODE_URL", "https://daily-cloudcode-pa.googleapis.com")
AGY_UA = (
    "antigravity/cli/1.4.12 (aidev_client; os_type=linux; arch=amd64; "
    "cl=1010700967; auth_method=consumer)"
)

_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 45  # seconds

# Reference API-equivalent values for known windows with limited local data.
DEFAULT_FULL_QUOTA_USD: dict[str, float] = {
    "codex:primary": 30.46,
    "codex:secondary": 190.40,
    "agy:gemini-5h": 15.00,
    "agy:gemini-weekly": 52.50,
    "agy:3p-5h": 3.97,
    "agy:3p-weekly": 9.21,
    "agy:gemini-argon-wtu-weekly": 26.98,
    "cc:five_hour": 18.00,
    "cc:seven_day": 90.00,
}


def _iso_to_epoch(s: str | None) -> int | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        if "." in s:
            head, rest = s.split(".", 1)
            tz = ""
            for sep in ("+", "-"):
                if sep in rest:
                    i = rest.index(sep)
                    rest, tz = rest[:i], rest[i:]
                    break
            s = head + "." + rest[:6] + tz
        return int(datetime.datetime.fromisoformat(s).timestamp())
    except Exception:
        return None


def _hm(sec: float, language='zh') -> str:
    sec = max(0, int(sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if language == 'en':
        if d > 0:
            return f'{d}d {h}h'
        if h > 0:
            return f'{h}h {m}m'
        return f'{max(1, m)}m'
    if d > 0:
        return f"{d}天{h}小时"
    if h > 0:
        return f"{h}小时{m}分"
    return f"{max(1, m)}分钟"


def _agy_token(allow_refresh: bool = True) -> str | None:
    p = AGY_HOME / "antigravity-oauth-token"
    try:
        tok = json.loads(p.read_text())["token"]
    except Exception:
        return None
    exp = _iso_to_epoch(tok.get("expiry")) or 0
    if exp - time.time() < 120 and allow_refresh:
        agy = shutil.which("agy") or str(Path.home() / '.local/bin/agy')
        try:
            subprocess.run(
                [agy, "models"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=40,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception:
            pass
        return _agy_token(False)
    if exp < time.time():
        return None
    return tok.get("access_token")


def _post(path: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        AGY_BASE + path,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": AGY_UA,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def fetch_agy_live() -> dict[str, Any] | None:
    c = _cache.get("agy")
    if c and time.time() - c[0] < CACHE_TTL:
        return c[1]
    token = _agy_token()
    if not token:
        return None
    try:
        summary = _post("/v1internal:retrieveUserQuotaSummary", token, {})
        models = _post("/v1internal:fetchAvailableModels", token, {}).get("models", {})
    except Exception as e:
        return {"error": str(e)[:200]}

    groups = []
    for g in summary.get("groups", []):
        buckets = []
        for b in g.get("buckets", []):
            rf = b.get("remainingFraction", 0.0 if b.get("resetTime") else None)
            buckets.append(
                {
                    "bucket_id": b.get("bucketId"),
                    "name": b.get("displayName"),
                    "window": b.get("window") or b.get("refreshWindowLabel"),
                    "remaining_percent": None if rf is None else round(rf * 100, 2),
                    "used_percent": None if rf is None else round((1 - rf) * 100, 2),
                    "resets_at": _iso_to_epoch(b.get("resetTime")),
                    "description": b.get("description"),
                }
            )
        groups.append(
            {
                "name": g.get("displayName"),
                "description": g.get("description"),
                "buckets": buckets,
            }
        )

    model_list = []
    for mid, m in models.items():
        qi = m.get("quotaInfo") or {}
        name = m.get("displayName")
        if not name or mid.startswith(("chat_", "tab_")):
            continue
        rf = qi.get("remainingFraction", 0.0 if qi.get("resetTime") else None)
        model_list.append(
            {
                "model_id": mid,
                "name": name,
                "remaining_percent": None if rf is None else round(rf * 100, 2),
                "used_percent": None if rf is None else round((1 - rf) * 100, 2),
                "resets_at": _iso_to_epoch(qi.get("resetTime")),
            }
        )
    model_list.sort(key=lambda x: x["name"])
    out = {"fetched_at": int(time.time()), "groups": groups, "models": model_list}
    _cache["agy"] = (time.time(), out)
    return out


def codex_window_label(window_minutes: int | None, role: str) -> str:
    name = "Primary" if role == "primary" else "Secondary"
    if not window_minutes:
        return f"窗口额度 ({name} Window)"
    if window_minutes % 1440 == 0:
        value, unit, suffix = window_minutes // 1440, "天", "d"
    elif window_minutes % 60 == 0:
        value, unit, suffix = window_minutes // 60, "小时", "h"
    else:
        value, unit, suffix = window_minutes, "分钟", "m"
    kind = "周度额度" if window_minutes == 10080 else "窗口额度"
    return f"{value} {unit}{kind} ({name} {value}{suffix} Window)"


def fetch_codex_live() -> dict[str, Any] | None:
    c = _cache.get("codex")
    if c and time.time() - c[0] < CACHE_TTL:
        return c[1]
    try:
        auth = json.loads((CODEX_HOME / "auth.json").read_text())
        tk = auth["tokens"]
        headers = {
            "Authorization": f"Bearer {tk['access_token']}",
            "Accept": "application/json",
            "User-Agent": "codex_cli_rs/0.1.0",
        }
        if tk.get("account_id"):
            headers["ChatGPT-Account-Id"] = tk["account_id"]
        req = urllib.request.Request(
            "https://chatgpt.com/backend-api/wham/usage", headers=headers
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)[:200]}

    rl = d.get("rate_limit") or {}

    def win(w: dict | None, role: str) -> dict | None:
        if not w:
            return None
        minutes = round((w.get("limit_window_seconds") or 0) / 60)
        return {
            "label": codex_window_label(minutes, role),
            "used_percent": w.get("used_percent"),
            "remaining_percent": round(100 - (w.get("used_percent") or 0), 1),
            "window_minutes": minutes,
            "resets_at": w.get("reset_at"),
        }

    out = {
        "fetched_at": int(time.time()),
        "plan_type": d.get("plan_type"),
        "allowed": rl.get("allowed"),
        "limit_reached": rl.get("limit_reached"),
        "primary": win(rl.get("primary_window"), "primary"),
        "secondary": win(rl.get("secondary_window"), "secondary"),
        "credits": d.get("credits"),
        "model_usage": d.get("model_usage"),
    }
    _cache["codex"] = (time.time(), out)
    return out


def fetch_claude_live() -> dict[str, Any] | None:
    c = _cache.get("cc")
    if c and time.time() - c[0] < CACHE_TTL:
        return c[1]
    cred = CLAUDE_HOME / ".credentials.json"
    if not cred.is_file():
        return None
    oa: dict[str, Any] = {}
    try:
        oa = json.loads(cred.read_text()).get("claudeAiOauth") or {}
        tok = oa.get("accessToken")
        if not tok:
            return None
        if (oa.get("expiresAt") or 0) / 1000 < time.time():
            claude = shutil.which("claude")
            if claude:
                subprocess.run(
                    [claude, "-p", "ok", "--max-turns", "1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                oa = json.loads(cred.read_text()).get("claudeAiOauth") or {}
                tok = oa.get("accessToken")
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {tok}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-cli/2.0 (external, cli)",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)[:200], "plan": oa.get("subscriptionType")}
    names = {
        "five_hour": ("5 小时窗口额度 (5h)", 300),
        "seven_day": ("7 天周度额度 (Weekly)", 10080),
        "seven_day_opus": ("7 天 Opus 额度", 10080),
        "seven_day_sonnet": ("7 天 Sonnet 额度", 10080),
    }
    buckets = []
    for k, (label, mins) in names.items():
        w = d.get(k)
        if isinstance(w, dict) and w.get("utilization") is not None:
            used = float(w["utilization"])
            ra = _iso_to_epoch(w.get("resets_at"))
            fc = forecast_window(used, mins, ra)
            b = {
                "bucket_id": k,
                "name": label,
                "window": "5h" if mins <= 300 else "weekly",
                "window_minutes": mins,
                "used_percent": round(used, 1),
                "remaining_percent": round(100 - used, 1),
                "resets_at": ra,
                "forecast": fc,
            }
            attach_cost(b, [], mins, default_key=f"cc:{k}")
            b["forecast_text"] = forecast_text(fc, ra, b)
            buckets.append(b)
    out = {
        "fetched_at": int(time.time()),
        "plan": oa.get("subscriptionType"),
        "buckets": buckets,
    }
    _cache["cc"] = (time.time(), out)
    return out


def _used_percent(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return min(100.0, max(0.0, float(value)))


def forecast_window(
    used_pct: float | None,
    window_min: int | None,
    resets_at: float | None,
    now: float | None = None,
) -> dict[str, Any] | None:
    used = _used_percent(used_pct)
    if used is None or not window_min or window_min <= 0 or not resets_at or not math.isfinite(resets_at):
        return None

    now = time.time() if now is None else now
    left = resets_at - now
    if left <= 0:
        return {"status": "reset", "left_seconds": 0, "window_minutes": window_min}

    elapsed = max(0.0, window_min * 60 - left)
    remaining = 100.0 - used
    result = {
        "window_minutes": window_min,
        "left_seconds": int(left),
        "elapsed_seconds": int(elapsed),
        "safe_percent_per_hour": round(remaining * 3600 / left, 2) if left >= 3600 else None,
        "safe_percent_per_day": round(remaining * 86400 / left, 1) if left >= 86400 else None,
        "projected_used_percent": None,
        "will_exhaust": used == 100,
        "support_seconds": None,
        "exhausts_at": None,
    }
    if used == 100:
        result.update(status="exhausted", support_seconds=0, projected_used_percent=100.0)
        return result

    min_elapsed = 1800 if window_min <= 360 else 14400
    if elapsed < min_elapsed:
        result["status"] = "early"
        return result

    rate = used / elapsed
    projected = used + rate * left
    support = remaining / rate if rate > 0 else None
    will_exhaust = support is not None and support < left
    result.update(
        status="will_exhaust" if will_exhaust else "safe",
        burn_percent_per_hour=round(rate * 3600, 2),
        projected_used_percent=round(min(100.0, projected), 1),
        projected_raw_percent=round(projected, 1),
        will_exhaust=will_exhaust,
        support_seconds=int(support) if support is not None else None,
        exhausts_at=int(now + support) if will_exhaust else None,
    )
    return result


def attach_cost(
    win: dict[str, Any],
    events: list,
    window_minutes: int,
    pick=None,
    default_key: str = "",
) -> None:
    """Sum priced log activity in the provider's actual window and estimate capacity."""
    reset = win.get("resets_at")
    now = time.time()
    models = {}
    if reset and math.isfinite(reset) and window_minutes > 0:
        start = reset - window_minutes * 60
        for event in events:
            if not (start <= event[0] < reset and event[0] <= now):
                continue
            if pick is not None and not pick(event[1]):
                continue
            model = models.setdefault(event[1], {'model': event[1], 'tokens': 0, 'requests': 0, 'cost': 0.0})
            model['tokens'] += event[-3]
            model['requests'] += event[-2]
            model['cost'] += event[-1]

    spent = sum(model['cost'] for model in models.values())
    win['cost_observed'] = round(spent, 6) if spent > 0 else None
    win['cost_models'] = sorted(({**model, 'cost': round(model['cost'], 6)} for model in models.values()),
                                key=lambda model: (-model['cost'], model['model']))
    estimate_cost(win, window_minutes, default_key, now=now)


def estimate_cost(win, window_minutes, default_key, *, now=None):
    """Estimate capacity from the quota percentage and the same window's log costs."""
    used = _used_percent(win.get('used_percent'))
    spent = win.get('cost_observed')
    reset = win.get('resets_at')
    now = time.time() if now is None else now
    left = reset - now if reset and math.isfinite(reset) else 0
    win.pop('cost_safe_per_day', None)
    win.pop('cost_safe_per_hour', None)

    full = remaining = None
    uses_reference = False
    if used == 100 and spent is not None:
        full = spent
    elif used is not None and left > 0:
        # The same Codex slot can carry different durations on different plans.
        if default_key.startswith('codex:'):
            default_key = {300: 'codex:primary', 10080: 'codex:secondary'}.get(window_minutes, '')
        reference = DEFAULT_FULL_QUOTA_USD.get(default_key)
        if spent is not None and used >= 25:
            full = spent * 100 / used
        elif reference is not None:
            full = reference
            if spent is not None and used > 0:
                # Very small reported percentages are sensitive to rounding and lag.
                sample_weight = min(1.0, used / 5)
                reference_weight = 15 * (1 - used / 25)
                full = (spent * 100 * sample_weight + reference * reference_weight) / (
                    used * sample_weight + reference_weight
                )
            uses_reference = True
        if full is not None:
            full = max(full, spent or 0.0)

    if full is not None and left > 0:
        remaining = full * (100 - used) / 100
        if remaining > 0 and window_minutes > 360 and left >= 86400:
            win['cost_safe_per_day'] = round(remaining * 86400 / left, 2)
        elif remaining > 0 and left >= 3600:
            win['cost_safe_per_hour'] = round(remaining * 3600 / left, 2)

    win['cost_used'] = round(spent, 2) if spent is not None else None
    win['cost_is_estimated'] = full is None or uses_reference
    win['cost_quota_total'] = round(full, 2) if full is not None else None
    win['cost_remaining'] = round(remaining, 2) if remaining is not None else None
    win['cost_text'] = cost_text(win, window_minutes)


def quota_window_minutes(window):
    return window.get("window_minutes") or {"5h": 300, "weekly": 10080}.get(window.get("window"))


def remaining_full_5h_windows(short, weekly, *, now=None):
    """Count complete windows after the current 5h window, at a similar model mix."""
    if quota_window_minutes(short) != 300 or quota_window_minutes(weekly) != 10080:
        return None

    now = time.time() if now is None else now
    short_reset = short.get("resets_at")
    week_reset = weekly.get("resets_at")
    if not (short_reset and week_reset and 0 < short_reset - now <= 18000
            and 0 < week_reset - now <= 604800):
        return None

    time_limit = max(0, int((week_reset - short_reset) // 18000))
    short_used = _used_percent(short.get("used_percent"))
    week_used = _used_percent(weekly.get("used_percent"))
    if short_used is None or week_used is None:
        return None
    if time_limit == 0 or week_used == 100:
        return 0

    short_cost = short.get("cost_observed")
    week_cost = weekly.get("cost_observed")
    week_start = week_reset - 604800
    # Wait for at least one 5h period and require some priced usage outside
    # the current 5h window so one burst cannot calibrate both windows.
    if (short_used < 5 or week_used < 5 or not short_cost or not week_cost
            or not 0 < short_cost < week_cost or not math.isfinite(week_cost)
            or now - week_start < 18000 or short_reset - 18000 < week_start):
        return None

    short_full = short_cost * 100 / short_used
    weekly_left = week_cost * (100 - week_used) / week_used
    current_left = short_full - short_cost
    quota_limit = max(0, math.floor((weekly_left - current_left) / short_full))
    return min(quota_limit, time_limit)


def add_5h_cycle_forecasts(payload, language):
    quotas = payload.get("quotas", payload)

    def annotate(windows):
        short = [w for w in windows if w and quota_window_minutes(w) == 300]
        weekly = [w for w in windows if w and quota_window_minutes(w) == 10080]
        if len(short) != 1 or len(weekly) != 1:
            return
        week = weekly[0]
        count = remaining_full_5h_windows(short[0], week)
        if count is None:
            return
        if language == "en":
            note = f"Est. {count} full 5-hour {'cycle' if count == 1 else 'cycles'} after this one"
        else:
            note = f"本轮结束后预计还能用满 {count} 轮 5 小时额度"
        week["remaining_5h_cycles"] = count
        week["forecast_text"] = " · ".join(filter(None, (week.get("forecast_text"), note)))

    codex = quotas.get("codex") or {}
    annotate([codex.get("primary"), codex.get("secondary")])

    agy = quotas.get("agy") or {}
    for group in (agy.get("live") or agy).get("groups", []):
        annotate(group.get("buckets", []))

    claude = quotas.get("cc") or {}
    annotate([w for w in (claude.get("quota") or claude).get("buckets", [])
              if w.get("bucket_id") in {"five_hour", "seven_day"}])


def forecast_text(
    fc: dict | None,
    resets_at: float | None = None,
    win: dict[str, Any] | None = None,
    language: str = 'zh',
) -> str:
    if not fc:
        return ""
    now = time.time()
    left = fc.get('left_seconds', max(0.0, (resets_at or now) - now))
    support = fc.get('support_seconds')
    projected = fc.get('projected_used_percent')
    weekly = (fc.get('window_minutes') or 300) > 360
    unit = 'day' if weekly and fc.get('safe_percent_per_day') is not None else 'hour'
    safe_pct = fc.get(f'safe_percent_per_{unit}')
    safe_usd = (win or {}).get(f'cost_safe_per_{unit}')
    status = fc.get('status')

    if language == 'en':
        allowance = f' · Allowance until reset {safe_pct}%/{unit}' if safe_pct is not None else ''
        if status == 'reset':
            return 'Quota window has reset'
        if status == 'exhausted':
            return f'Quota limit reached; resets in {_hm(left, "en")}'
        if status == 'early':
            return f'Collecting usage data · Resets in {_hm(left, "en")}{allowance}'
        if status == 'will_exhaust':
            usd_hint = f' (≈${safe_usd:,.2f}/{unit})' if safe_usd is not None else ''
            return f'At the window’s average pace, quota will run out in about {_hm(support or 0, "en")}{allowance}{usd_hint}'
        return f'Projected use at reset at the window’s average pace {projected}%{allowance}'

    unit_zh = '天' if unit == 'day' else '小时'
    allowance = f' · 重置前平均可用 {safe_pct}%/{unit_zh}' if safe_pct is not None else ''
    if status == 'reset':
        return '额度窗口已重置'
    if status == 'exhausted':
        return f'已达额度上限 · {_hm(left)}后重置'
    if status == 'early':
        return f'正在收集用量数据 · {_hm(left)}后重置{allowance}'
    if status == 'will_exhaust':
        usd_hint = f'（≈${safe_usd:,.2f}/{unit_zh}）' if safe_usd is not None else ''
        return f'按本窗口平均速度，约 {_hm(support or 0)}后用完{allowance}{usd_hint}'
    return f'按本窗口平均速度，重置时预计用掉 {projected}%{allowance}'


def cost_text(win, window_minutes, language='zh'):
    if 'cost_quota_total' not in win:
        return win.get('cost_text', '') if language != 'en' else ''

    full = win.get('cost_quota_total')
    spent = win.get('cost_used')
    remaining = win.get('cost_remaining')
    reference = win.get('cost_is_estimated')
    en = language == 'en'
    weekly = (window_minutes or 300) > 360
    parts = []
    if full is not None:
        period = ('Weekly' if weekly else '5h') if en else ('周度' if weekly else '5 小时')
        quality = ('reference' if reference else 'estimate') if en else ('参考值' if reference else '估算值')
        label = f'{period} quota value ({quality})' if en else f'{period}满额（{quality}）'
        parts.append(f'{label} ≈${full:,.2f} API')
    if spent is not None:
        label = 'Usage from priced logs' if en else '本机已定价日志折算'
        parts.append(f'{label} ≈${spent:,.2f}')
    elif full is not None:
        parts.append('No priced usage recorded' if en else '暂无已定价的用量记录')
    if remaining is not None:
        label = 'Estimated remaining' if en else '预计剩余'
        parts.append(f'{label} ≈${remaining:,.2f}')
        for rate, unit, unit_zh in (('cost_safe_per_day', 'day', '天'), ('cost_safe_per_hour', 'hour', '小时')):
            if win.get(rate) is not None:
                label = 'Average allowance until reset' if en else '重置前平均可用'
                parts[-1] += f' ({label} ≈${win[rate]:,.2f}/{unit if en else unit_zh})'
                break
    return ' · '.join(parts)


def claude_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "installed": CLAUDE_HOME.is_dir(),
        "plan": None,
        "quota": fetch_claude_live(),
    }
    cred = CLAUDE_HOME / ".credentials.json"
    if cred.is_file():
        try:
            oa = json.loads(cred.read_text()).get("claudeAiOauth") or {}
            info["plan"] = oa.get("subscriptionType")
        except Exception:
            pass
    return info
