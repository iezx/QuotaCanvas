#!/usr/bin/env python3
"""
AI Usage & Quota Collector for Codex (~/.codex) and Antigravity AGY (~/.gemini/antigravity-cli).
Reads local .jsonl / .jsonl.zst logs, stats-cache.json, sqlite metadata, and CLI logs.
Automatically calculates API equivalent costs ($) and real-time quota status.
Updates stats-cache.json and data/stats.json every minute.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
from contextlib import closing
import datetime
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import quota_live as ql
from zstandard import ZstdError
from compressed_logs import iter_log_lines
from pricing import ID_RE, PRICE_STORE
from runtime_paths import get_data_dir
from usage_logs import DSH_HOME, agy_model, dsh_events, dsh_journals, logged_model

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = get_data_dir(BASE_DIR)
CACHE_FILE = OUTPUT_DIR / "stats-cache.json"
STATS_JSON_FILE = OUTPUT_DIR / "stats.json"

CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
AGY_HOME = Path(
    os.environ.get("AGY_HOME", str(Path.home() / ".gemini" / "antigravity-cli"))
).expanduser()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude"))).expanduser()

# Built-in USD per 1,000,000 tokens, in the order (input, cache read,
# cache write, output). These historical examples may be outdated or inexact.
# Users can supply verified values in the dashboard. Unpriced usage is excluded
# from cost totals. Estimates are not subscription billing.
MODEL_PRICING: dict[str, tuple[float, float, float, float]] = {
    # OpenAI / Codex models
    "gpt-6-astra": (10.00, 1.00, 0.00, 50.00),
    "gpt-6.1-sol": (2.00, 0.10, 0.00, 10.00),
    "gpt-6.1-terra": (1.00, 0.05, 0.00, 5.00),
    "gpt-6-sol": (2.00, 0.10, 0.00, 10.00),
    "gpt-6-terra": (1.00, 0.05, 0.00, 5.00),
    "gpt-6-luna": (0.10, 0.01, 0.00, 0.50),
    "gpt-5.6-sol": (4.00, 0.40, 0.00, 20.00),
    "gpt-5.6-terra": (2.00, 0.20, 0.00, 12.00),
    "gpt-5.6-luna": (0.20, 0.02, 0.00, 1.20),
    "gpt-5.4": (2.50, 0.25, 0.00, 15.00),
    "gpt-reserve": (0.10, 0.01, 0.00, 0.50),
    "codex-auto-review": (0.10, 0.01, 0.00, 0.50),
    "o3": (2.00, 0.50, 0.00, 8.00),
    "o4-mini": (1.10, 0.275, 0.00, 4.40),
    "gpt-5": (1.25, 0.125, 0.00, 10.00),
    "gpt-5-mini": (0.25, 0.025, 0.00, 2.00),
    # Google Antigravity (AGY) & Gemini / Claude models
    "gemini-4-argon-high": (2.00, 0.10, 0.00, 10.00),
    "gemini-4-argon-medium": (2.00, 0.10, 0.00, 10.00),
    "gemini-4-argon-low": (2.00, 0.10, 0.00, 10.00),
    "gemini-4-argon": (2.00, 0.10, 0.00, 10.00),
    "gemini-3.8-flash-high": (0.75, 0.075, 0.00, 3.75),
    "gemini-3.8-flash-medium": (0.75, 0.075, 0.00, 3.75),
    "gemini-3.8-flash-low": (0.75, 0.075, 0.00, 3.75),
    "gemini-3.8-flash": (0.75, 0.075, 0.00, 3.75),
    "gemini-3.5-flash-lite": (0.30, 0.0375, 0.00, 1.875),
    "claude-opus-5-5-high": (4.00, 0.20, 5.00, 20.00),
    "claude-opus-5-5-medium": (4.00, 0.20, 5.00, 20.00),
    "claude-opus-5-5-low": (4.00, 0.20, 5.00, 20.00),
    "claude-opus-5-5": (4.00, 0.20, 5.00, 20.00),
    "claude-opus-5": (4.00, 0.20, 5.00, 20.00),
    "claude-opus-4-8": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4-7": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4-6": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4-5": (5.00, 0.50, 6.25, 25.00),
    "claude-sonnet-5-5-high": (2.00, 0.10, 2.50, 10.00),
    "claude-sonnet-5-5-medium": (2.00, 0.10, 2.50, 10.00),
    "claude-sonnet-5-5-low": (2.00, 0.10, 2.50, 10.00),
    "claude-sonnet-5-5": (2.00, 0.10, 2.50, 10.00),
    "claude-sonnet-4-6": (3.00, 0.30, 3.75, 15.00),
    "claude-sonnet-4-5": (3.00, 0.30, 3.75, 15.00),
    "claude-haiku-4-5": (1.00, 0.10, 1.25, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 0.10, 1.25, 5.00),
    "gpt-oss-120b-medium": (0.15, 0.015, 0.00, 0.60),
    "gpt-oss-120b": (0.15, 0.015, 0.00, 0.60),
}

AGY_MODEL_MAP: dict[str, str] = {
    "gemini 4 argon (high)": "gemini-4-argon-high",
    "gemini 4 argon (medium)": "gemini-4-argon-medium",
    "gemini 4 argon (low)": "gemini-4-argon-low",
    "gemini 3.8 flash (high)": "gemini-3.8-flash-high",
    "gemini 3.8 flash (medium)": "gemini-3.8-flash-medium",
    "gemini 3.8 flash (low)": "gemini-3.8-flash-low",
    "claude opus 5.5 (high)": "claude-opus-5-5-high",
    "claude opus 5.5 (medium)": "claude-opus-5-5-medium",
    "claude opus 5.5 (low)": "claude-opus-5-5-low",
    "claude sonnet 5.5 (high)": "claude-sonnet-5-5-high",
    "claude sonnet 5.5 (medium)": "claude-sonnet-5-5-medium",
    "claude sonnet 5.5 (low)": "claude-sonnet-5-5-low",
    "gpt-oss 120b (medium)": "gpt-oss-120b-medium",
}


def normalize_agy_model(raw: str) -> str:
    if not raw:
        return "gemini-4-argon-high"
    s = raw.strip()
    low = s.lower()
    if low in AGY_MODEL_MAP:
        return AGY_MODEL_MAP[low]
    if ID_RE.fullmatch(s):
        return s
    if low.startswith("gemini") and "argon" in low:
        if "low" in low:
            return "gemini-4-argon-low"
        if "medium" in low:
            return "gemini-4-argon-medium"
        return "gemini-4-argon-high"
    if low.startswith("gemini") and "flash" in low:
        if "low" in low:
            return "gemini-3.8-flash-low"
        if "high" in low:
            return "gemini-3.8-flash-high"
        return "gemini-3.8-flash-medium"
    if low.startswith("claude") and "opus" in low:
        return "claude-opus-5-5"
    if low.startswith("claude") and "sonnet" in low:
        if "high" in low:
            return "claude-sonnet-5-5-high"
        if "low" in low:
            return "claude-sonnet-5-5-low"
        return "claude-sonnet-5-5-medium"
    if low.startswith("claude") and "haiku" in low:
        return "claude-haiku-4-5"
    if "gpt-oss" in low:
        return "gpt-oss-120b-medium"
    return re.sub(r"[^a-z0-9._-]+", "-", low).strip("-")


def get_model_pricing(model: str) -> tuple[float, float, float, float]:
    overrides = PRICE_STORE.overrides()
    if model in overrides:
        p = overrides[model]
        return (p['in'], p['cache_read'], p['cache_write'], p['out'])
    return MODEL_PRICING.get(model, (0, 0, 0, 0))


def calc_cost(model: str, inp_uncached: int, cr: int, cw: int, out: int) -> float:
    p_in, p_cr, p_cw, p_out = get_model_pricing(model)
    return (inp_uncached * p_in + cr * p_cr + cw * p_cw + out * p_out) / 1_000_000.0


TZ_CST = datetime.timezone(datetime.timedelta(hours=8))
_DAY_STR_CACHE: dict[int, str] = {}


def parse_iso_ts(ts: str) -> float | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(ts).timestamp()
    except Exception:
        return None


def ts_to_day(ts_val: float | None, ts_str: str = "") -> str | None:
    if ts_val is not None:
        day_idx = int(ts_val + 28800) // 86400
        s = _DAY_STR_CACHE.get(day_idx)
        if s is None:
            s = datetime.datetime.fromtimestamp(ts_val, TZ_CST).strftime("%Y-%m-%d")
            _DAY_STR_CACHE[day_idx] = s
        return s
    return ts_str[:10] if len(ts_str) >= 10 else None


def parse_codex_stream(lines_iter, default_session: str = "codex") -> dict[str, Any]:
    """
    Parse a stream of Codex rollout JSONL lines (from one file or a batch of .zst files).
    Returns compact serializable dictionary suitable for storing in stats-cache.json.
    """
    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "in": 0,
            "cr": 0,
            "cw": 0,
            "out": 0,
            "tok": 0,
            "req": 0,
            "cost": 0.0,
            "ses": set(),
            "m": Counter(),
            "mc": defaultdict(float),
            "t": Counter(),
        }
    )
    cur_model = "unknown"
    provider = ""
    ses_id = default_session
    seen_rids: set[str] = set()
    ses_last_ts: dict[str, float] = {}
    ses_active_ms: dict[str, float] = defaultdict(float)
    latest_rl: tuple[str, dict[str, Any]] | None = None
    recent_events: list[tuple[float, str, int, int, float]] = []  # (ts, model, tok, req, cost)
    now_ts = time.time()

    for line in lines_iter:
        if not line:
            continue
        # Fast pre-filter to skip multi-megabyte tool output / world_state / reasoning lines
        if (
            '"token_usage_record"' not in line
            and '"token_count"' not in line
            and '"session_meta"' not in line
            and '"turn_context"' not in line
            and '"thread_settings_applied"' not in line
            and '"custom_tool_call"' not in line
            and '"function_call"' not in line
            and '"local_shell_call"' not in line
            and '"web_search_call"' not in line
        ):
            continue
        if '"custom_tool_call_output"' in line or '"function_call_output"' in line:
            continue

        try:
            obj = json.loads(line)
        except Exception:
            continue

        ts_str = obj.get("timestamp") or ""
        ts_val = parse_iso_ts(ts_str)
        day = ts_to_day(ts_val, ts_str)
        t = obj.get("type")
        pl = obj.get("payload")
        if not isinstance(pl, dict):
            continue

        if t == "session_meta":
            ses_id = pl.get("id") or pl.get("session_id") or default_session
            cur_model = logged_model(pl) or "unknown"
            provider = pl.get("model_provider") or ""

        if ts_val is not None:
            prev_ts = ses_last_ts.get(ses_id)
            if prev_ts is not None and 0 <= (ts_val - prev_ts) <= 3600:
                ses_active_ms[ses_id] += (ts_val - prev_ts) * 1000.0
            ses_last_ts[ses_id] = ts_val

        if t == "turn_context":
            cur_model = logged_model(pl) or cur_model
            provider = pl.get("model_provider") or provider
        elif t == "event_msg":
            pt = pl.get("type")
            if pt == "thread_settings_applied":
                settings = pl.get("thread_settings") or {}
                cur_model = logged_model(settings) or cur_model
                provider = settings.get("model_provider") or provider
            elif pt == "token_count":
                rl = pl.get("rate_limits")
                if isinstance(rl, dict) and rl.get("primary"):
                    if latest_rl is None or ts_str >= latest_rl[0]:
                        latest_rl = (ts_str, rl)
        elif t == "token_usage_record" and day:
            rid = pl.get("response_id")
            if rid:
                if rid in seen_rids:
                    continue
                seen_rids.add(rid)
            u = pl.get("usage")
            if isinstance(u, dict):
                inp_total = int(u.get("input_tokens") or 0)
                cr = int(u.get("cached_input_tokens") or 0)
                cw = int(u.get("cache_write_input_tokens") or 0)
                out = int(u.get("output_tokens") or 0)
                tok = int(u.get("total_tokens") or (inp_total + out))
                inp_uncached = max(0, inp_total - cr - cw)
                model = logged_model(pl) or logged_model(u) or cur_model
                model_provider = pl.get("model_provider") or provider
                c = calc_cost(model, inp_uncached, cr, cw, out)
                d = days[day]
                d["in"] += inp_uncached
                d["cr"] += cr
                d["cw"] += cw
                d["out"] += out
                d["tok"] += tok
                d["req"] += 1
                d["cost"] += c
                d["ses"].add(ses_id)
                d["m"][model] += tok
                d["mc"][model] += c
                if model_provider in ("", "openai") and ts_val is not None and (now_ts - ts_val) <= 86400 * 7:
                    recent_events.append((ts_val, model, tok, 1, c))
        elif t == "response_item" and day:
            pt = pl.get("type")
            if pt in ("function_call", "custom_tool_call", "local_shell_call", "web_search_call"):
                name = pl.get("name") or pt
                if name == "exec":
                    inp_s = str(pl.get("input") or pl.get("arguments") or "")
                    nested = re.findall(r"tools\.([a-zA-Z0-9_]+)\s*\(", inp_s)
                    for n in (nested or ["exec"]):
                        days[day]["t"][n] += 1
                else:
                    days[day]["t"][name] += 1

    longest_ms = max(ses_active_ms.values(), default=0.0)
    ser_days = {}
    for day, d in days.items():
        ser_days[day] = {
            "in": d["in"],
            "cr": d["cr"],
            "cw": d["cw"],
            "out": d["out"],
            "tok": d["tok"],
            "req": d["req"],
            "cost": round(d["cost"], 6),
            "ses": list(d["ses"]),
            "m": dict(d["m"]),
            "mc": {k: round(v, 6) for k, v in d["mc"].items()},
            "t": dict(d["t"]),
        }
    return {
        "days": ser_days,
        "longest_ms": round(longest_ms),
        "latest_rl": latest_rl,
        "recent_events": recent_events,
    }


def parse_agy_transcript(path: Path) -> dict[str, Any]:
    """
    Parse an Antigravity (AGY) transcript.jsonl (and transcript_full.jsonl if tool_calls truncated).
    """
    conv_id = path.parent.parent.parent.name
    full_path = path.parent / "transcript_full.jsonl"
    full_lines: list[str] | None = None

    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "in": 0,
            "cr": 0,
            "cw": 0,
            "out": 0,
            "tok": 0,
            "req": 0,
            "cost": 0.0,
            "ses": set(),
            "m": Counter(),
            "mc": defaultdict(float),
            "t": Counter(),
        }
    )
    cur_model_raw, cur_model = "", "unknown"
    last_ts: float | None = None
    active_ms = 0.0
    recent_events: list[tuple[float, str, str, int, int, float]] = []
    model_timeline: list[tuple[float, str, str]] = []
    now_ts = time.time()

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                trunc = obj.get("truncated_fields") or []
                if "tool_calls" in trunc and full_path.is_file():
                    if full_lines is None:
                        try:
                            full_lines = full_path.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines()
                        except Exception:
                            full_lines = []
                    if idx < len(full_lines):
                        try:
                            obj = json.loads(full_lines[idx])
                        except Exception:
                            pass

                ts_str = obj.get("created_at") or ""
                ts_val = parse_iso_ts(ts_str)
                day = ts_to_day(ts_val, ts_str)
                if ts_val is not None:
                    if last_ts is not None and 0 <= (ts_val - last_ts) <= 3600:
                        active_ms += (ts_val - last_ts) * 1000.0
                    last_ts = ts_val

                t = obj.get("type")
                model = agy_model(obj)
                if model and model != cur_model_raw:
                    cur_model_raw = model
                    cur_model = normalize_agy_model(model)
                    if ts_val is not None:
                        model_timeline.append((ts_val, cur_model, cur_model_raw))
                if t == "PLANNER_RESPONSE" and day:
                    inp = int(obj.get("input_tokens") or 0)
                    cr = int(obj.get("cache_read_tokens") or 0)
                    cw = int(obj.get("cache_write_tokens") or 0)
                    out = int(obj.get("output_tokens") or 0)
                    tok = inp + cr + cw + out
                    if tok > 0:
                        c = calc_cost(cur_model, inp, cr, cw, out)
                        d = days[day]
                        d["in"] += inp
                        d["cr"] += cr
                        d["cw"] += cw
                        d["out"] += out
                        d["tok"] += tok
                        d["req"] += 1
                        d["cost"] += c
                        d["ses"].add(conv_id)
                        d["m"][cur_model] += tok
                        d["mc"][cur_model] += c
                        if ts_val is not None and (now_ts - ts_val) <= 86400 * 7:
                            recent_events.append(
                                (ts_val, cur_model, cur_model_raw, tok, 1, c)
                            )

                    tcs = obj.get("tool_calls") or []
                    if isinstance(tcs, list):
                        for tc in tcs:
                            if isinstance(tc, dict):
                                name = tc.get("name") or (
                                    tc.get("function") or {}
                                ).get("name")
                                if name:
                                    days[day]["t"][name] += 1
    except Exception:
        pass

    ser_days = {}
    for day, d in days.items():
        ser_days[day] = {
            "in": d["in"],
            "cr": d["cr"],
            "cw": d["cw"],
            "out": d["out"],
            "tok": d["tok"],
            "req": d["req"],
            "cost": round(d["cost"], 6),
            "ses": list(d["ses"]),
            "m": dict(d["m"]),
            "mc": {k: round(v, 6) for k, v in d["mc"].items()},
            "t": dict(d["t"]),
        }
    return {
        "days": ser_days,
        "longest_ms": round(active_ms),
        "recent_events": recent_events,
        "model_timeline": model_timeline,
    }


def extract_codex_account_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "email": None,
        "name": None,
        "plan_type": "plus",
        "subscription_start": None,
        "subscription_until": None,
        "default_model": "gpt-6-luna",
        "reasoning_effort": "medium",
    }
    cfg_path = CODEX_HOME / "config.toml"
    if cfg_path.is_file():
        try:
            txt = cfg_path.read_text(encoding="utf-8", errors="ignore")
            m_mod = re.search(r'^\s*model\s*=\s*"([^"]+)"', txt, re.M)
            if m_mod:
                info["default_model"] = m_mod.group(1)
            m_eff = re.search(r'^\s*model_reasoning_effort\s*=\s*"([^"]+)"', txt, re.M)
            if m_eff:
                info["reasoning_effort"] = m_eff.group(1)
        except Exception:
            pass

    auth_path = CODEX_HOME / "auth.json"
    if auth_path.is_file():
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8", errors="ignore"))
            tokens = auth.get("tokens") or {}
            for k in ("id_token", "access_token"):
                jwt_s = tokens.get(k)
                if jwt_s and "." in str(jwt_s):
                    parts = str(jwt_s).split(".")
                    if len(parts) >= 2:
                        pad = parts[1] + "=" * (-len(parts[1]) % 4)
                        claims = json.loads(base64.urlsafe_b64decode(pad))
                        if claims.get("email"):
                            info["email"] = claims.get("email")
                        if claims.get("name"):
                            info["name"] = claims.get("name")
                        oa = claims.get("https://api.openai.com/auth") or {}
                        if oa.get("chatgpt_plan_type"):
                            info["plan_type"] = oa.get("chatgpt_plan_type")
                        if oa.get("chatgpt_subscription_active_start"):
                            info["subscription_start"] = oa[
                                "chatgpt_subscription_active_start"
                            ][:10]
                        if oa.get("chatgpt_subscription_active_until"):
                            info["subscription_until"] = oa[
                                "chatgpt_subscription_active_until"
                            ][:10]
                        prof = claims.get("https://api.openai.com/profile") or {}
                        if prof.get("email") and not info["email"]:
                            info["email"] = prof.get("email")
        except Exception:
            pass
    return info


def extract_agy_quota_info(
    recent_events: list[tuple[float, str, str, int, int, float]],
    model_timeline: list[tuple[float, str, str]],
) -> dict[str, Any]:
    now_ts = time.time()
    active_model_raw = "Gemini 4 Argon (High)"
    settings_path = AGY_HOME / "settings.json"
    if settings_path.is_file():
        try:
            st = json.loads(settings_path.read_text(encoding="utf-8", errors="ignore"))
            if st.get("model"):
                active_model_raw = st["model"]
        except Exception:
            pass
    active_model_id = normalize_agy_model(active_model_raw)

    email = None
    auth_method = "consumer"
    model_timeline_sorted = sorted(model_timeline, key=lambda x: x[0])

    def model_at(ts_val: float) -> tuple[str, str]:
        chosen = ("claude-sonnet-5-5-medium", "Claude Sonnet 5.5 (Medium)")
        for mts, mid, mraw in model_timeline_sorted:
            if mts <= ts_val + 5:
                chosen = (mid, mraw)
            else:
                break
        return chosen

    cooldowns: dict[str, dict[str, Any]] = {}
    log_files = sorted(glob.glob(str(AGY_HOME / "log" / "*.log")))
    now_year = datetime.datetime.now().year
    for lp in log_files:
        try:
            with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m_em = re.search(
                        r"applyAuthResult:\s*email=([^,\s]+)(?:,\s*authMethod=([^,\s]+))?",
                        line,
                    )
                    if m_em:
                        email = m_em.group(1)
                        if m_em.group(2):
                            auth_method = m_em.group(2)
                    if "RESOURCE_EXHAUSTED" in line and "Resets in" in line:
                        m_ts = re.match(
                            r"[IWEF](\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", line
                        )
                        m_dur = re.search(
                            r"Resets in\s+(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", line
                        )
                        if m_ts and m_dur:
                            mon, day, hh, mm, ss = map(int, m_ts.groups())
                            dh = int(m_dur.group(1) or 0)
                            dm = int(m_dur.group(2) or 0)
                            ds = int(m_dur.group(3) or 0)
                            dt = datetime.datetime(
                                now_year, mon, day, hh, mm, ss
                            ).astimezone()
                            ev_ts = dt.timestamp()
                            reset_ts = int(
                                (
                                    dt
                                    + datetime.timedelta(
                                        hours=dh, minutes=dm, seconds=ds
                                    )
                                ).timestamp()
                            )
                            mid, mraw = model_at(ev_ts)
                            cooldowns[mid] = {
                                "model_id": mid,
                                "model_name": mraw,
                                "exhausted_at": int(ev_ts),
                                "resets_at": reset_ts,
                                "window_minutes": 300,
                            }
        except Exception:
            pass

    # Rolling 5h and 24h usage per model
    win5h_cut = now_ts - 5 * 3600
    win24h_cut = now_ts - 24 * 3600
    by_model_5h: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"tok": 0, "req": 0, "cost": 0.0, "name": ""}
    )
    tot_5h = {"tok": 0, "req": 0, "cost": 0.0}
    tot_24h = {"tok": 0, "req": 0, "cost": 0.0}

    for ts_val, mid, mraw, tok, req, cost in recent_events:
        if ts_val >= win24h_cut:
            tot_24h["tok"] += tok
            tot_24h["req"] += req
            tot_24h["cost"] += cost
        if ts_val >= win5h_cut:
            tot_5h["tok"] += tok
            tot_5h["req"] += req
            tot_5h["cost"] += cost
            bm = by_model_5h[mid]
            bm["tok"] += tok
            bm["req"] += req
            bm["cost"] += cost
            bm["name"] = mraw or mid

    # Build model quota buckets
    all_models = set(by_model_5h.keys()) | set(cooldowns.keys()) | {active_model_id}
    buckets = []
    for mid in sorted(all_models):
        cd = cooldowns.get(mid)
        bm = by_model_5h.get(mid, {"tok": 0, "req": 0, "cost": 0.0, "name": mid})
        resets_at = cd["resets_at"] if cd else None
        is_exhausted = bool(resets_at and resets_at > now_ts)
        used_pct = 100.0 if is_exhausted else None
        buckets.append(
            {
                "model_id": mid,
                "model_name": (cd and cd["model_name"])
                or bm["name"]
                or (active_model_raw if mid == active_model_id else mid),
                "is_current": mid == active_model_id,
                "status": "exhausted" if is_exhausted else "available",
                "used_percent": used_pct,
                "resets_at": resets_at,
                "window_minutes": 300,
                "window_5h_tokens": bm["tok"],
                "window_5h_requests": bm["req"],
                "window_5h_cost": round(bm["cost"], 4),
            }
        )

    return {
        "source": "agy",
        "name": "Antigravity (AGY)",
        "email": email,
        "plan_type": auth_method,
        "active_model": active_model_raw,
        "active_model_id": active_model_id,
        "window_5h": {
            "tokens": tot_5h["tok"],
            "requests": tot_5h["req"],
            "cost": round(tot_5h["cost"], 4),
        },
        "window_24h": {
            "tokens": tot_24h["tok"],
            "requests": tot_24h["req"],
            "cost": round(tot_24h["cost"], 4),
        },
        "models": buckets,
    }



def collect_claude_days(recent_events=None) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], int], dict[tuple[str, str], float]]:
    """Claude Code interface: ~/.claude/projects/**/*.jsonl (assistant usage records)."""
    days: dict[str, dict[str, Any]] = {}
    mtok: dict[tuple[str, str], int] = Counter()
    mcost: dict[tuple[str, str], float] = defaultdict(float)
    seen: set[str] = set()
    for jp in glob.glob(str(CLAUDE_HOME / "projects" / "**" / "*.jsonl"), recursive=True):
        sid = Path(jp).stem
        try:
            with open(jp, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    msg = o.get("message") or {}
                    u = msg.get("usage") if isinstance(msg, dict) else None
                    if not u or o.get("type") != "assistant":
                        continue
                    key = (msg.get("id") or "") + (o.get("requestId") or "")
                    if key and key in seen:
                        continue
                    seen.add(key)
                    ts_str = o.get("timestamp") or ""
                    day = ts_to_day(parse_iso_ts(ts_str), ts_str)
                    if not day:
                        continue
                    model = logged_model(msg) or logged_model(obj) or "unknown"
                    i = int(u.get("input_tokens") or 0)
                    cr = int(u.get("cache_read_input_tokens") or 0)
                    cw = int(u.get("cache_creation_input_tokens") or 0)
                    out = int(u.get("output_tokens") or 0)
                    c = calc_cost(model, i, cr, cw, out)
                    if recent_events is not None:
                        stamp = parse_iso_ts(ts_str)
                        if stamp and stamp >= time.time() - 8 * 86400:
                            recent_events.append((stamp, model, i + cr + cw + out, 1, c))
                    d = days.setdefault(day, {"in": 0, "cr": 0, "cw": 0, "out": 0, "tok": 0, "req": 0, "cost": 0.0, "ses": set()})
                    d["in"] += i; d["cr"] += cr; d["cw"] += cw; d["out"] += out
                    d["tok"] += i + cr + cw + out
                    d["req"] += 1; d["cost"] += c; d["ses"].add(sid)
                    mtok[(model, day)] += i + cr + cw + out
                    mcost[(model, day)] += c
        except Exception:
            continue
    return days, mtok, mcost


def collect_dsh(previous):
    result = {}
    for path, stat in dsh_journals(DSH_HOME):
        key = str(path)
        sig = f"{stat.st_mtime_ns}:{stat.st_size}"
        cached = previous.get(key)
        if cached and cached["sig"] == sig:
            result[key] = cached
            continue
        days = defaultdict(lambda: {"in": 0, "cr": 0, "cw": 0, "out": 0, "tok": 0,
                                    "req": 0, "cost": 0.0, "m": Counter(), "mc": defaultdict(float)})
        model = "unknown"
        try:
            for kind, stamp, _, _, reported, counts in dsh_events(path):
                if kind in ("model/selection", "request/context") and reported:
                    model = reported
                if counts is None:
                    continue
                used = reported or model
                usage = days[ts_to_day(stamp)]
                for field, count in zip(("in", "cr", "cw", "out"), counts):
                    usage[field] += count
                tokens, cost = sum(counts), calc_cost(used, *counts)
                usage["tok"] += tokens
                usage["req"] += 1
                usage["cost"] += cost
                usage["m"][used] += tokens
                usage["mc"][used] += cost
        except (OSError, ZstdError):
            if cached:
                result[key] = cached
            continue
        result[key] = {"sig": sig, "data": days}
    return result


def collect_all(force_rescan: bool = False) -> dict[str, Any]:
    now_ts = time.time()
    now_ms = int(now_ts * 1000)
    today_str = datetime.datetime.now(TZ_CST).strftime("%Y-%m-%d")

    cache: dict[str, Any] = {"version": 6, "zst_dirs": {}, "jsonl_files": {}, "agy_files": {}}
    if not force_rescan and CACHE_FILE.is_file():
        try:
            loaded = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            same_prices = loaded.get('price_revision') == PRICE_STORE.revision()
            original_cache = 'price_revision' not in loaded and not PRICE_STORE.overrides()
            if loaded.get("version") == 6 and (same_prices or original_cache):
                cache = loaded
        except Exception:
            pass

    # 1. Discover Codex .jsonl and .jsonl.zst files
    zst_all = sorted(glob.glob(str(CODEX_HOME / "sessions" / "**" / "*.jsonl.zst"), recursive=True))
    jsonl_all = [
        p
        for p in sorted(glob.glob(str(CODEX_HOME / "sessions" / "**" / "*.jsonl"), recursive=True))
        if os.path.getsize(p) > 0
    ]
    jsonl_set = set(jsonl_all)
    zst_only = [zp for zp in zst_all if zp[:-4] not in jsonl_set]

    # Group zst_only by parent directory (e.g., sessions/2026/09/21)
    zst_by_dir: dict[str, list[str]] = defaultdict(list)
    for zp in zst_only:
        zst_by_dir[os.path.dirname(zp)].append(zp)

    new_zst_cache: dict[str, Any] = {}
    for dpath, zfiles in sorted(zst_by_dir.items()):
        sig_parts = []
        for zp in zfiles:
            st = os.stat(zp)
            sig_parts.append(f"{os.path.basename(zp)}:{st.st_mtime_ns}:{st.st_size}")
        sig = hashlib.sha1("|".join(sig_parts).encode("utf-8")).hexdigest()
        cached_entry = cache.get("zst_dirs", {}).get(dpath)
        if cached_entry and cached_entry.get("sig") == sig:
            new_zst_cache[dpath] = cached_entry
        else:
            with closing(iter_log_lines(zfiles)) as lines:
                parsed = parse_codex_stream(lines, default_session=dpath)
            new_zst_cache[dpath] = {"sig": sig, "data": parsed}

    new_jsonl_cache: dict[str, Any] = {}
    for jp in jsonl_all:
        st = os.stat(jp)
        sig = f"{st.st_mtime_ns}:{st.st_size}"
        cached_entry = cache.get("jsonl_files", {}).get(jp)
        if cached_entry and cached_entry.get("sig") == sig:
            new_jsonl_cache[jp] = cached_entry
        else:
            with open(jp, "r", encoding="utf-8", errors="replace") as f:
                parsed = parse_codex_stream(f, default_session=Path(jp).stem)
            new_jsonl_cache[jp] = {"sig": sig, "data": parsed}

    # 2. Discover AGY transcript.jsonl files
    agy_transcripts = sorted(
        glob.glob(str(AGY_HOME / "brain" / "*" / ".system_generated" / "logs" / "transcript.jsonl"))
    )
    new_agy_cache: dict[str, Any] = {}
    for ap in agy_transcripts:
        st = os.stat(ap)
        full_p = os.path.join(os.path.dirname(ap), "transcript_full.jsonl")
        full_sz = os.path.getsize(full_p) if os.path.exists(full_p) else 0
        sig = f"{st.st_mtime_ns}:{st.st_size}:{full_sz}"
        cached_entry = cache.get("agy_files", {}).get(ap)
        if cached_entry and cached_entry.get("sig") == sig:
            new_agy_cache[ap] = cached_entry
        else:
            parsed = parse_agy_transcript(Path(ap))
            new_agy_cache[ap] = {"sig": sig, "data": parsed}

    new_dsh_cache = collect_dsh(cache.get("dsh_files", {}))

    # Save updated incremental stats-cache.json
    cache_out = {
        "version": 6,
        'price_revision': PRICE_STORE.revision(),
        "updated_at": now_ms,
        "zst_dirs": new_zst_cache,
        "jsonl_files": new_jsonl_cache,
        "agy_files": new_agy_cache,
        "dsh_files": new_dsh_cache,
    }
    try:
        tmp_cache = CACHE_FILE.with_suffix(".json.tmp")
        tmp_cache.write_text(json.dumps(cache_out, ensure_ascii=False), encoding="utf-8")
        tmp_cache.replace(CACHE_FILE)
    except Exception:
        pass

    # 3. Aggregate Codex & AGY metrics by day
    # Day structure per source: {in, cr, cw, out, tok, req, cost, ses_set, m_counter, t_counter}
    agg_days: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "in": 0,
                "cr": 0,
                "cw": 0,
                "out": 0,
                "tok": 0,
                "req": 0,
                "cost": 0.0,
                "ses": set(),
                "m": Counter(),
                "t": Counter(),
            }
        )
    )
    longest_ms = {"codex": 0, "agy": 0}
    summary_models: dict[tuple[str, str], int] = Counter()
    summary_model_costs: dict[tuple[str, str], float] = defaultdict(float)
    summary_tools: dict[tuple[str, str], int] = Counter()

    latest_codex_rl: tuple[str, dict[str, Any]] | None = None
    codex_recent_events: list[tuple[float, str, int, int, float]] = []

    for entry in list(new_zst_cache.values()) + list(new_jsonl_cache.values()):
        pdata = entry["data"]
        if pdata.get("longest_ms", 0) > longest_ms["codex"]:
            longest_ms["codex"] = pdata["longest_ms"]
        rl = pdata.get("latest_rl")
        if rl and (latest_codex_rl is None or rl[0] >= latest_codex_rl[0]):
            latest_codex_rl = rl
        for ev in pdata.get("recent_events") or []:
            codex_recent_events.append(tuple(ev))
        for day, d in (pdata.get("days") or {}).items():
            target = agg_days[day]["codex"]
            target["in"] += d["in"]
            target["cr"] += d["cr"]
            target["cw"] += d["cw"]
            target["out"] += d["out"]
            target["tok"] += d["tok"]
            target["req"] += d["req"]
            target["cost"] += d["cost"]
            target["ses"].update(d["ses"])
            for m_name, m_tok in (d.get("m") or {}).items():
                target["m"][m_name] += m_tok
                summary_models[(m_name, "codex")] += m_tok
            for m_name, m_cost in (d.get("mc") or {}).items():
                summary_model_costs[(m_name, "codex")] += m_cost
            for t_name, t_cnt in (d.get("t") or {}).items():
                target["t"][t_name] += t_cnt
                summary_tools[(t_name, "codex")] += t_cnt

    agy_recent_events: list[tuple[float, str, str, int, int, float]] = []
    agy_model_timeline: list[tuple[float, str, str]] = []
    for entry in new_agy_cache.values():
        pdata = entry["data"]
        if pdata.get("longest_ms", 0) > longest_ms["agy"]:
            longest_ms["agy"] = pdata["longest_ms"]
        for ev in pdata.get("recent_events") or []:
            agy_recent_events.append(tuple(ev))
        for mt in pdata.get("model_timeline") or []:
            agy_model_timeline.append(tuple(mt))
        for day, d in (pdata.get("days") or {}).items():
            target = agg_days[day]["agy"]
            target["in"] += d["in"]
            target["cr"] += d["cr"]
            target["cw"] += d["cw"]
            target["out"] += d["out"]
            target["tok"] += d["tok"]
            target["req"] += d["req"]
            target["cost"] += d["cost"]
            target["ses"].update(d["ses"])
            for m_name, m_tok in (d.get("m") or {}).items():
                target["m"][m_name] += m_tok
                summary_models[(m_name, "agy")] += m_tok
            for m_name, m_cost in (d.get("mc") or {}).items():
                summary_model_costs[(m_name, "agy")] += m_cost
            for t_name, t_cnt in (d.get("t") or {}).items():
                target["t"][t_name] += t_cnt
                summary_tools[(t_name, "agy")] += t_cnt

    cc_recent_events = []
    cc_days, cc_mtok, cc_mcost = collect_claude_days(recent_events=cc_recent_events)
    for day, d in cc_days.items():
        t = agg_days[day]["cc"]
        for k in ("in", "cr", "cw", "out", "tok", "req", "cost"):
            t[k] += d[k]
        t["ses"].update(d["ses"])
    for (m, day), tok in cc_mtok.items():
        agg_days[day]["cc"]["m"][m] += tok
        summary_models[(m, "cc")] += tok
        summary_model_costs[(m, "cc")] += cc_mcost[(m, day)]

    for path, entry in new_dsh_cache.items():
        for day, usage in entry["data"].items():
            target = agg_days[day]["dsh"]
            for field in ("in", "cr", "cw", "out", "tok", "req", "cost"):
                target[field] += usage[field]
            target["ses"].add(path)
            target["m"].update(usage["m"])
            for model, tokens in usage["m"].items():
                summary_models[(model, "dsh")] += tokens
                summary_model_costs[(model, "dsh")] += usage["mc"][model]

    # Build days list matching https://ai.3301921.xyz/api/stats.json schema
    days_list = []
    for day in sorted(agg_days.keys()):
        srcs_for_day = agg_days[day]
        day_obj: dict[str, Any] = {"d": day, "q": "raw"}
        m_list = []
        t_list = []
        for src_id in ("codex", "agy", "cc", "dsh"):
            if src_id in srcs_for_day:
                sd = srcs_for_day[src_id]
                day_obj[src_id] = {
                    "cost": round(sd["cost"], 6),
                    "cr": sd["cr"],
                    "cw": sd["cw"],
                    "in": sd["in"],
                    "out": sd["out"],
                    "req": sd["req"],
                    "ses": len(sd["ses"]),
                    "tok": sd["tok"],
                }
                for m_name, m_tok in sd["m"].most_common():
                    m_list.append([m_name, m_tok, src_id])
                for t_name, t_cnt in sd["t"].most_common():
                    t_list.append([t_name, t_cnt, src_id])
        m_list.sort(key=lambda x: x[1], reverse=True)
        t_list.sort(key=lambda x: x[1], reverse=True)
        day_obj["m"] = m_list
        day_obj["t"] = t_list
        days_list.append(day_obj)

    if days_list and days_list[-1]["d"] > today_str:
        today_str = days_list[-1]["d"]

    # Build Codex quota object
    codex_acct = extract_codex_account_info()
    rl_ts_str, rl_obj = latest_codex_rl if latest_codex_rl else (None, {})
    prim = (rl_obj or {}).get("primary") or {}
    sec = (rl_obj or {}).get("secondary") or {}
    cred = (rl_obj or {}).get("credits") or {}

    def format_window(w: dict[str, Any], default_mins: int, role: str) -> dict[str, Any] | None:
        if not w:
            return None
        resets_at = w.get("resets_at")
        raw_pct = float(w.get("used_percent") or 0.0)
        is_reset = bool(resets_at and now_ts >= float(resets_at))
        eff_pct = 0.0 if is_reset else raw_pct
        return {
            "label": ql.codex_window_label(int(w.get("window_minutes") or default_mins), role),
            "used_percent": round(eff_pct, 1),
            "raw_used_percent": round(raw_pct, 1),
            "remaining_percent": round(max(0.0, 100.0 - eff_pct), 1),
            "window_minutes": int(w.get("window_minutes") or default_mins),
            "resets_at": resets_at,
            "is_reset": is_reset,
        }

    win5h_cut = now_ts - 5 * 3600
    win24h_cut = now_ts - 24 * 3600
    codex_5h = {"tok": 0, "req": 0, "cost": 0.0}
    codex_24h = {"tok": 0, "req": 0, "cost": 0.0}
    for ts_val, _m, tok, req, cost in codex_recent_events:
        if ts_val >= win24h_cut:
            codex_24h["tok"] += tok
            codex_24h["req"] += req
            codex_24h["cost"] += cost
        if ts_val >= win5h_cut:
            codex_5h["tok"] += tok
            codex_5h["req"] += req
            codex_5h["cost"] += cost

    codex_quota = {
        "source": "codex",
        "name": "OpenAI Codex",
        "email": codex_acct.get("email"),
        "user_name": codex_acct.get("name"),
        "plan_type": (rl_obj or {}).get("plan_type") or codex_acct.get("plan_type") or "plus",
        "subscription_start": codex_acct.get("subscription_start"),
        "subscription_until": codex_acct.get("subscription_until"),
        "default_model": codex_acct.get("default_model"),
        "reasoning_effort": codex_acct.get("reasoning_effort"),
        "updated_at": rl_ts_str,
        "primary": format_window(prim, 300, "primary"),
        "secondary": format_window(sec, 10080, "secondary"),
        "credits": {
            "has_credits": bool(cred.get("has_credits")),
            "unlimited": bool(cred.get("unlimited")),
            "balance": str(cred.get("balance") or "0"),
        },
        "window_5h": {
            "tokens": codex_5h["tok"],
            "requests": codex_5h["req"],
            "cost": round(codex_5h["cost"], 4),
        },
        "window_24h": {
            "tokens": codex_24h["tok"],
            "requests": codex_24h["req"],
            "cost": round(codex_24h["cost"], 4),
        },
    }

    agy_quota = extract_agy_quota_info(agy_recent_events, agy_model_timeline)

    # ---- Live official quotas override log-inferred values ----
    try:
        cxl = ql.fetch_codex_live()
        if cxl and "error" not in cxl:
            codex_quota["plan_type"] = cxl.get("plan_type") or codex_quota["plan_type"]
            for k in ("primary", "secondary"):
                w = cxl.get(k)
                if not w:
                    codex_quota[k] = None
                    continue
                fc = ql.forecast_window(w["used_percent"], w["window_minutes"], w["resets_at"])
                codex_quota[k] = {
                    "label": ql.codex_window_label(w["window_minutes"], k),
                    "used_percent": w["used_percent"],
                    "raw_used_percent": w["used_percent"],
                    "remaining_percent": w["remaining_percent"],
                    "window_minutes": w["window_minutes"],
                    "resets_at": w["resets_at"],
                    "is_reset": False,
                    "forecast": fc,
                }
                ql.attach_cost(
                    codex_quota[k],
                    codex_recent_events,
                    w["window_minutes"],
                    default_key=f"codex:{k}",
                )
                codex_quota[k]["forecast_text"] = ql.forecast_text(
                    fc, w["resets_at"], codex_quota[k]
                )
            codex_quota["live"] = True
            codex_quota["limit_reached"] = cxl.get("limit_reached")
            if cxl.get("credits"):
                codex_quota["credits"]["balance"] = str(cxl["credits"].get("balance", "0"))
        else:
            for k in ("primary", "secondary"):
                w = codex_quota.get(k)
                if w:
                    fc = ql.forecast_window(w["used_percent"], w["window_minutes"], w["resets_at"])
                    w["forecast"] = fc
                    ql.attach_cost(
                        w,
                        codex_recent_events,
                        w["window_minutes"],
                        default_key=f"codex:{k}",
                    )
                    w["forecast_text"] = ql.forecast_text(fc, w["resets_at"], w)
        agl = ql.fetch_agy_live()
        if agl and "error" not in agl:
            for g in agl["groups"]:
                for b in g["buckets"]:
                    wm = {"5h": 300, "weekly": 10080}.get(b.get("window"))
                    b["forecast"] = ql.forecast_window(b.get("used_percent"), wm, b.get("resets_at"))
                    if wm:
                        gname = (g.get("name") or "") + " " + (b.get("bucket_id") or "")
                        if "Argon" in gname:
                            pick = lambda m: "argon" in m
                        elif "Claude" in gname or "3p" in gname:
                            pick = lambda m: ("claude" in m or "gpt-oss" in m)
                        else:
                            pick = lambda m: m.startswith("gemini") and "argon" not in m
                        ql.attach_cost(
                            b,
                            agy_recent_events,
                            wm,
                            pick,
                            default_key=f"agy:{b.get('bucket_id')}",
                        )
                    b["forecast_text"] = ql.forecast_text(b["forecast"], b.get("resets_at"), b)
            agy_quota["live"] = agl
        ccl = ql.fetch_claude_live()
        if ccl is not None or CLAUDE_HOME.is_dir():
            for b in (ccl or {}).get("buckets", []):
                bucket = b.get("bucket_id", "")
                family = "sonnet" if "sonnet" in bucket else ("opus" if "opus" in bucket else None)
                ql.attach_cost(b, cc_recent_events, b.get("window_minutes") or 300,
                               (lambda model, family=family: family in model.lower()) if family else None,
                               default_key="cc:" + bucket)
                b["forecast_text"] = ql.forecast_text(b.get("forecast"), b.get("resets_at"), b)
            cc_quota = {"source": "cc", "name": "Claude Code", **(ccl or {})}
        else:
            cc_quota = None
    except Exception:
        cc_quota = None

    # Subscription plans for ROI calculation
    first_codex_day = next((d["d"] for d in days_list if "codex" in d), "2026-09-06")
    first_agy_day = next((d["d"] for d in days_list if "agy" in d), today_str)
    plans = [
        {"from": first_codex_day, "name": "Codex Plus", "price": 20, "source": "codex"},
        {"from": first_agy_day, "name": "AGY Pro", "price": 20, "source": "agy"},
    ]

    priced_models = MODEL_PRICING.keys() | PRICE_STORE.overrides().keys()
    models_sorted = sorted(
        [
            [m, tok, src, round(summary_model_costs[(m, src)], 4) if m in priced_models else None]
            for (m, src), tok in summary_models.items()
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    tools_sorted = sorted(
        [[t, cnt, src] for (t, src), cnt in summary_tools.items()],
        key=lambda x: x[1],
        reverse=True,
    )

    pricing_table = {
        m: {"in": p[0], "cr": p[1], "cw": p[2], "out": p[3]}
        for m, p in MODEL_PRICING.items()
    }
    pricing_table.update({m: {'in': p['in'], 'cr': p['cache_read'], 'cw': p['cache_write'], 'out': p['out']}
                          for m, p in PRICE_STORE.overrides().items()})

    stats_payload = {
        "days": days_list,
        "generated": now_ms,
        "today": today_str,
        "sources": {
            "codex": {"color": "#10a37f", "name": "OpenAI Codex"},
            "agy": {"color": "#8b5cf6", "name": "Antigravity (AGY)"},
            **({"cc": {"color": "#d97757", "name": "Claude Code"}} if (cc_days or cc_quota) else {}),
            **({"dsh": {"color": "#3976ce", "name": "DeepSeek Harness"}} if any(entry["data"] for entry in new_dsh_cache.values()) else {}),
        },
        "plans": plans,
        "summary": {
            "longest_ms": longest_ms,
            "models": models_sorted,
            "tools": tools_sorted,
        },
        "quotas": {
            "codex": codex_quota,
            "agy": agy_quota,
            **({"cc": cc_quota} if cc_quota else {}),
        },
        "pricing": pricing_table,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_stats = STATS_JSON_FILE.with_suffix(".json.tmp")
    tmp_stats.write_text(
        json.dumps(stats_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp_stats.replace(STATS_JSON_FILE)
    return stats_payload


def fmt_tokens(n: float | int | None) -> str:
    if n is None:
        return "—"
    if n >= 1e8:
        return f"{n / 1e8:.2f}亿"
    if n >= 1e4:
        return f"{n / 1e4:.1f}万"
    return f"{int(n):,}"


def fmt_reset(ts: int | float | None) -> str:
    if not ts:
        return "—"
    now = time.time()
    diff = int(ts - now)
    dt_str = datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    if diff <= 0:
        return f"已重置 ({dt_str})"
    d, rem = divmod(diff, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d > 0:
        return f"{d}天{h}小时后重置 ({dt_str})"
    if h > 0:
        return f"{h}小时{m}分后重置 ({dt_str})"
    return f"{m}分钟后重置 ({dt_str})"


def print_cli_report(stats: dict[str, Any]) -> None:
    print("=" * 78)
    print(
        f" AI 用量与额度监控 (Codex & Antigravity) | 更新时间: "
        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print("=" * 78)

    # 1. Quotas
    q_codex = stats["quotas"]["codex"]
    print("\n【1. 实时使用额度 (Usage Quotas & Rate Limits)】")
    print(
        f"  [OpenAI Codex] 账号: {q_codex.get('email') or '—'} | "
        f"订阅: {str(q_codex.get('plan_type')).upper()} "
        f"({q_codex.get('subscription_start') or '—'} ~ {q_codex.get('subscription_until') or '—'}) | "
        f"默认模型: {q_codex.get('default_model')}"
    )
    for role in ("primary", "secondary"):
        window = q_codex.get(role)
        if window:
            print(
                f"    • {ql.codex_window_label(window.get('window_minutes'), role)} : "
                f"已用 {window['used_percent']:5.1f}% (剩余 {window['remaining_percent']:5.1f}%) | "
                f"{fmt_reset(window['resets_at'])}"
            )
    print(
        f"    • 近5h/24h消耗  : 近5h {fmt_tokens(q_codex['window_5h']['tokens'])} "
        f"(${q_codex['window_5h']['cost']:.2f}) | "
        f"近24h {fmt_tokens(q_codex['window_24h']['tokens'])} "
        f"(${q_codex['window_24h']['cost']:.2f})"
    )

    q_agy = stats["quotas"]["agy"]
    print(
        f"\n  [Antigravity AGY] 账号: {q_agy.get('email') or '—'} | "
        f"当前模型: {q_agy.get('active_model')}"
    )
    for mb in q_agy.get("models", []):
        status_str = (
            f"冷却中 (已用 100%, {fmt_reset(mb['resets_at'])})"
            if mb["status"] == "exhausted"
            else "正常可用 (Available)"
        )
        cur_tag = " [当前]" if mb.get("is_current") else ""
        print(
            f"    • {mb['model_name']}{cur_tag}: {status_str} | "
            f"近5h: {fmt_tokens(mb['window_5h_tokens'])} ({mb['window_5h_requests']}次, ${mb['window_5h_cost']:.2f})"
        )

    # 2. Totals per source
    print("\n【2. 历史累计 Token 消耗与 API 等价费用折算】")
    tot_all = {"tok": 0, "in": 0, "cr": 0, "cw": 0, "out": 0, "req": 0, "ses": 0, "cost": 0.0}
    for src_id, src_meta in stats["sources"].items():
        s_tok = s_in = s_cr = s_cw = s_out = s_req = s_ses = 0
        s_cost = 0.0
        s_days = 0
        for d in stats["days"]:
            sd = d.get(src_id)
            if sd:
                s_days += 1
                s_tok += sd["tok"]
                s_in += sd["in"] or 0
                s_cr += sd["cr"] or 0
                s_cw += sd["cw"] or 0
                s_out += sd["out"] or 0
                s_req += sd["req"] or 0
                s_ses += sd["ses"] or 0
                s_cost += sd["cost"] or 0.0
        tot_all["tok"] += s_tok
        tot_all["in"] += s_in
        tot_all["cr"] += s_cr
        tot_all["cw"] += s_cw
        tot_all["out"] += s_out
        tot_all["req"] += s_req
        tot_all["ses"] += s_ses
        tot_all["cost"] += s_cost
        cache_hit = (s_cr / (s_in + s_cr + s_cw) * 100.0) if (s_in + s_cr + s_cw) > 0 else 0.0
        print(
            f"  [{src_meta['name']}] 活跃 {s_days} 天 | 会话 {s_ses:,} 个 | 请求 {s_req:,} 次"
        )
        print(
            f"    • 总 Tokens : {fmt_tokens(s_tok)} ({s_tok:,}) | "
            f"输入 {fmt_tokens(s_in)} · 缓存读 {fmt_tokens(s_cr)} ({cache_hit:.1f}% 命中) · 输出 {fmt_tokens(s_out)}"
        )
        print(f"    • API 等价  : ${s_cost:,.2f}")

    all_hit = (
        tot_all["cr"] / (tot_all["in"] + tot_all["cr"] + tot_all["cw"]) * 100.0
        if (tot_all["in"] + tot_all["cr"] + tot_all["cw"]) > 0
        else 0.0
    )
    print("-" * 78)
    print(
        f"  [全部来源合计] 总 Tokens: {fmt_tokens(tot_all['tok'])} ({tot_all['tok']:,}) | "
        f"总请求: {tot_all['req']:,} | 缓存命中: {all_hit:.1f}% | "
        f"API 总等价费用: ${tot_all['cost']:,.2f}"
    )
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Codex & AGY usage stats and API costs.")
    parser.add_argument("--force", action="store_true", help="Force full rescan ignoring stats-cache.json")
    parser.add_argument("--quiet", action="store_true", help="Do not print CLI table")
    parser.add_argument("--watch", action="store_true", help="Run continuously every 60 seconds")
    parser.add_argument("--interval", type=int, default=60, help="Refresh interval in seconds (default: 60)")
    args = parser.parse_args()

    while True:
        stats = collect_all(force_rescan=args.force)
        args.force = False
        if not args.quiet:
            print_cli_report(stats)
        if not args.watch:
            break
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()
