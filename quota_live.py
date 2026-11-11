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

AGY_BASE = os.environ.get("CLOUD_CODE_URL", "https://cloudcode-pa.googleapis.com")
AGY_UA = (
    "antigravity/cli/1.4.12 (aidev_client; os_type=linux; arch=amd64; "
    "cl=1010700967; auth_method=consumer)"
)

_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 45  # seconds

# Reference full-quota API dollar equivalents when local window spend is <1%
# (calibrated from measured logs & official plan tiers)
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


def forecast_window(
    used_pct: float | None,
    window_min: int | None,
    resets_at: float | None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """
    Calculate clear, intuitive quota pace metrics:
    - elapsed time & remaining time until reset
    - average burn rate (%/h) and remaining safe allowance (%/h or %/day)
    - estimated remaining续航 time at current average pace
    """
    now = now or time.time()
    if used_pct is None or not window_min or not resets_at:
        return None
    total = float(window_min * 60)
    left = max(0.0, float(resets_at) - now)
    if left <= 0:
        return {"status": "reset", "projected_used_percent": 0.0, "left_seconds": 0}

    # Elapsed time in current window (at least 30m for 5h, 4h for weekly to prevent spike distortion)
    min_elapsed = 1800.0 if window_min <= 360 else 14400.0
    raw_elapsed = max(60.0, total - left)
    elapsed = max(min_elapsed, raw_elapsed)

    rem_pct = max(0.0, 100.0 - float(used_pct))
    rate_per_sec = float(used_pct) / elapsed
    rate_per_hr = rate_per_sec * 3600.0
    projected = min(100.0, float(used_pct) + rate_per_sec * left)
    projected_raw = float(used_pct) + rate_per_sec * left

    # Safe allowance rate to comfortably last until reset
    safe_pct_per_hr = rem_pct / max(left / 3600.0, 0.1)
    safe_pct_per_day = rem_pct / max(left / 86400.0, 0.1)

    res: dict[str, Any] = {
        "window_minutes": window_min,
        "left_seconds": int(left),
        "elapsed_seconds": int(raw_elapsed),
        "burn_percent_per_hour": round(rate_per_hr, 2),
        "safe_percent_per_hour": round(safe_pct_per_hr, 2),
        "safe_percent_per_day": round(min(100.0, safe_pct_per_day), 1),
        "projected_used_percent": round(projected, 1),
        "projected_raw_percent": round(projected_raw, 1),
        "will_exhaust": bool(used_pct >= 100 or projected_raw >= 105),
    }

    if used_pct >= 100:
        res["status"] = "exhausted"
        res["support_seconds"] = 0
        res["exhausts_at"] = None
    elif rate_per_sec > 0:
        support_sec = rem_pct / rate_per_sec
        res["support_seconds"] = int(support_sec)
        eta = now + support_sec
        if eta < resets_at and projected_raw >= 105:
            res["status"] = "will_exhaust"
            res["exhausts_at"] = int(eta)
        else:
            res["status"] = "safe"
            res["exhausts_at"] = None
    else:
        res["status"] = "safe"
        res["support_seconds"] = int(left)
        res["exhausts_at"] = None
    return res


def attach_cost(
    win: dict[str, Any],
    events: list,
    window_minutes: int,
    pick=None,
    default_key: str = "",
) -> None:
    """
    Calculate API dollar equivalents for a 5h or Weekly quota window:
    - cost_used: actual API equivalent USD spent in this window
    - cost_quota_total: estimated 100% full quota value in API USD
    - cost_remaining: remaining quota value in API USD
    - cost_safe_rate: how much API USD you can spend per hour (for 5h) or per day (for weekly) until reset
    """
    used = float(win.get("used_percent") or 0.0)
    rem = max(0.0, 100.0 - used)
    ra = win.get("resets_at")
    now = time.time()
    left = max(0.0, (float(ra) - now) if ra else float(window_minutes * 60))

    t0 = (float(ra) - window_minutes * 60) if ra else (now - window_minutes * 60)
    selected = [e for e in events if t0 <= e[0] <= now and (not ra or e[0] < float(ra))
                and (pick is None or pick(e[1]))]
    models = {}
    for event in selected:
        model = models.setdefault(event[1], {'model': event[1], 'tokens': 0, 'requests': 0, 'cost': 0.0})
        model['tokens'] += event[-3]
        model['requests'] += event[-2]
        model['cost'] += event[-1]
    spent = sum(model['cost'] for model in models.values())
    win['cost_observed'] = round(spent, 6) if selected else None
    win['cost_models'] = sorted(({**model, 'cost': round(model['cost'], 6)} for model in models.values()),
                                key=lambda model: (-model['cost'], model['model']))

    fallback_full = DEFAULT_FULL_QUOTA_USD.get(default_key, 20.0)
    if used >= 5.0 and spent >= 0.20:
        full_usd = spent / (used / 100.0)
        is_estimated_baseline = False
    else:
        full_usd = fallback_full
        if spent <= 0.01 and used > 0:
            spent = full_usd * (used / 100.0)
        is_estimated_baseline = True

    rem_usd = max(0.0, full_usd * (rem / 100.0))
    used_usd = full_usd * (used / 100.0) if is_estimated_baseline else spent

    win["cost_used"] = round(used_usd, 2)
    win['cost_is_estimated'] = is_estimated_baseline
    win["cost_quota_total"] = round(full_usd, 2)
    win["cost_remaining"] = round(rem_usd, 2)

    is_weekly = window_minutes > 360
    win_label = "周度满额" if is_weekly else "5h 满额"
    if left > 0 and rem > 0:
        if is_weekly:
            days_left = max(left / 86400.0, 0.2)
            safe_usd_per_day = rem_usd / days_left
            win["cost_safe_per_day"] = round(safe_usd_per_day, 2)
            pace_str = f"重置前日均可用 ≈${safe_usd_per_day:,.2f}/天"
        else:
            hrs_left = max(left / 3600.0, 0.1)
            safe_usd_per_hr = rem_usd / hrs_left
            win["cost_safe_per_hour"] = round(safe_usd_per_hr, 2)
            pace_str = f"重置前均速可用 ≈${safe_usd_per_hr:,.2f}/小时"
    else:
        pace_str = "等待重置后恢复额度"

    win["cost_text"] = (
        f"{win_label} ≈${full_usd:,.2f} API · 已用 ≈${used_usd:,.2f} · "
        f"剩余可用 ≈${rem_usd:,.2f} ({pace_str})"
    )


def forecast_text(
    fc: dict | None,
    resets_at: float | None = None,
    win: dict[str, Any] | None = None,
    language: str = 'zh',
) -> str:
    """Clear, human-friendly forecast explanation without confusing timezone/empty-window wording."""
    if not fc:
        return ""
    now = time.time()
    left = max(0.0, (resets_at or now) - now)
    is_weekly = (fc.get("window_minutes") or 300) > 360

    if language == 'en':
        if fc.get('status') == 'reset':
            return 'Quota window has reset'
        if fc.get('status') == 'exhausted':
            return f'Quota limit reached; resets in {_hm(left, "en")}'
        support = fc.get('support_seconds') or int(left)
        projected = fc.get('projected_used_percent', 0)
        daily = fc.get('safe_percent_per_day', 0)
        if fc.get('status') == 'will_exhaust':
            if is_weekly:
                usd = (win or {}).get('cost_safe_per_day')
                hint = f' (≈${usd:,.2f}/day)' if usd is not None else ''
                return f'Usage is high; about {_hm(support, "en")} remaining at this rate. Daily allowance until reset: {daily}%/day{hint}'
            return f'Usage is high; about {_hm(support, "en")} remaining at this rate (resets in {_hm(left, "en")})'
        if is_weekly:
            return f'On track: projected use at reset {projected}%; daily allowance until reset {daily}%/day'
        return f'On track: projected use at reset {projected}%; {_hm(left, "en")} until reset'

    if fc.get("status") == "exhausted":
        return f"已达 100% 额度上限，将在 {_hm(left)}后自动重置恢复"

    sup = fc.get("support_seconds") or int(left)
    proj = fc.get("projected_used_percent", 0)
    safe_day = fc.get("safe_percent_per_day", 0)
    safe_hr = fc.get("safe_percent_per_hour", 0)

    if fc.get("status") == "will_exhaust":
        if is_weekly:
            safe_usd = (win or {}).get("cost_safe_per_day")
            usd_hint = f"（≈${safe_usd}/天）" if safe_usd else ""
            return (
                f"短期消耗较快（按当前速率还可连续支撑约 {_hm(sup)}）；"
                f"重置前日均可用 {safe_day}%/天{usd_hint}"
            )
        else:
            return f"短期消耗较快，按当前速率还可支撑约 {_hm(sup)}（{_hm(left)}后重置）"

    if is_weekly:
        return (
            f"余量充足：预计到重置时累计用掉 {proj}% "
            f"（重置前日均可用 {safe_day}%/天）"
        )
    return f"余量充足：预计到重置时累计用掉 {proj}%（还可支撑 {_hm(left)} 直至重置）"


def cost_text(win, window_minutes, language='zh'):
    if 'cost_quota_total' not in win:
        return win.get('cost_text', '') if language != 'en' else ''
    if language != 'en':
        return win.get('cost_text', '')
    label = 'Weekly quota value' if (window_minutes or 300) > 360 else '5h quota value'
    pace = 'Waiting for quota reset'
    if win.get('cost_safe_per_day') is not None:
        pace = f'Average daily allowance until reset ≈${win["cost_safe_per_day"]:,.2f}/day'
    elif win.get('cost_safe_per_hour') is not None:
        pace = f'Average hourly allowance until reset ≈${win["cost_safe_per_hour"]:,.2f}/hour'
    return (f'{label} ≈${win["cost_quota_total"]:,.2f} API · Used ≈${win.get("cost_used", 0):,.2f} · '
            f'Remaining ≈${win.get("cost_remaining", 0):,.2f} ({pace})')


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
