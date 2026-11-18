"""Read model and usage metadata from local agent logs."""
from contextlib import closing
import json
import os
from pathlib import Path
import re

from compressed_logs import iter_log_lines
from pricing import DEFAULT_PRICES, ID_RE

DSH_HOME = Path(os.environ.get('DSH_HOME') or Path.home() / '.dsh').expanduser()
AGY_SELECTION = re.compile(r"changed setting `Model Selection` from .*? to ([^\n]+?)\. No need")
DSH_JOURNAL = re.compile(r'session(?:\.v([0-9]+))?\.jsonl(?:\.(zst|zstd))?$')

AGY_MODEL_MAP: dict[str, str] = {
    "gemini 4 argon (high)": "gemini-4-argon-high",
    "gemini 4 argon (medium)": "gemini-4-argon-medium",
    "gemini 4 argon (low)": "gemini-4-argon-low",
    "gemini 4 hydrogen (xhigh)": "gemini-4-hydrogen-xhigh",
    "gemini 4 hydrogen (high)": "gemini-4-hydrogen-high",
    "gemini 4 hydrogen (medium)": "gemini-4-hydrogen-medium",
    "gemini 4 hydrogen (low)": "gemini-4-hydrogen-low",
    "gemini 4 carbon (xhigh)": "gemini-4-carbon-xhigh",
    "gemini 4 carbon (high)": "gemini-4-carbon-high",
    "gemini 4 carbon (medium)": "gemini-4-carbon-medium",
    "gemini 4 carbon (low)": "gemini-4-carbon-low",
    "orchestrator (argon)": "gemini-pro-orchestrator-g1-pro",
    "gemini 3.8 flash (high)": "gemini-3.8-flash-high",
    "gemini 3.8 flash (medium)": "gemini-3.8-flash-medium",
    "gemini 3.8 flash (low)": "gemini-3.8-flash-low",
    "gemini 3.5 flash lite": "gemini-3.5-flash-lite",
    "gemini 3.1 flash lite": "gemini-3.1-flash-lite",
    "gemini 3 flash": "gemini-3-flash",
    "gemini 2.5 pro": "gemini-2.5-pro",
    "claude opus 5.5 (high)": "claude-opus-5-5-high",
    "claude opus 5.5 (medium)": "claude-opus-5-5-medium",
    "claude opus 5.5 (low)": "claude-opus-5-5-low",
    "claude sonnet 5.5 (high)": "claude-sonnet-5-5-high",
    "claude sonnet 5.5 (medium)": "claude-sonnet-5-5-medium",
    "claude sonnet 5.5 (low)": "claude-sonnet-5-5-low",
    "gpt-oss 120b (medium)": "gpt-oss-120b-medium",
}


def normalize_agy_model(raw: str, default: str = "gemini-4-argon-high") -> str:
    """Normalize an Antigravity display or slug model name to its canonical catalog ID."""
    if not raw or not str(raw).strip():
        return default
    s = str(raw).strip()
    low = s.lower()
    if low in AGY_MODEL_MAP:
        return AGY_MODEL_MAP[low]
    tier_match = re.match(r"^(.*?)\s*\(([^()]+)\)$", low)
    if tier_match:
        base_slug = re.sub(r"[^a-z0-9._-]+", "-", tier_match.group(1)).strip("-")
        tier_slug = re.sub(r"[^a-z0-9._-]+", "-", tier_match.group(2)).strip("-")
        tiered = f"{base_slug}-{tier_slug}" if base_slug and tier_slug else ""
        if tiered and (
            tiered in DEFAULT_PRICES
            or (base_slug.startswith("gemini-") and tier_slug in ("low", "medium", "high", "xhigh", "max"))
        ):
            return tiered
    display_name = re.sub(r"\s*\([^()]*\)$", "", low).replace(" ", "-")
    if display_name in DEFAULT_PRICES and display_name.startswith("gemini-"):
        return display_name
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


def logged_model(record):
    for key in ('response_model', 'model', 'model_id'):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return ''


def agy_model(record):
    model = logged_model(record)
    if not model and record.get('type') == 'USER_INPUT':
        content = record.get('content')
        if isinstance(content, str):
            match = AGY_SELECTION.search(content)
            if match:
                return match[1].strip()
    return model


def dsh_journals(home):
    # Retained generations and compression copies are alternative views of one journal.
    latest = {}
    for path in (home / 'sessions').glob('**/session*.jsonl*'):
        match = DSH_JOURNAL.fullmatch(path.name)
        if not match:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if not stat.st_size:
            continue
        rank = (int(match[1] or 0), stat.st_mtime_ns, match[2] is None)
        previous = latest.get(path.parent)
        if previous is None or rank > previous[0]:
            latest[path.parent] = (rank, path, stat)
    return [(path, stat) for _, path, stat in latest.values()]


def dsh_events(path):
    with closing(iter_log_lines([path])) as lines:
        for line in lines:
            try:
                event = json.loads(line)
                kind, data, millis = event['type'], event['data'], event['time']
                if not isinstance(data, dict) or type(millis) is not int or not 0 < millis < 253402300800000:
                    continue
                if kind not in ('turn/start', 'turn/end', 'model/selection', 'request/context',
                                'assistant/message', 'compaction/summary'):
                    continue
                message = data.get('message') or {}
                route = message.get('source') or {}
                model = logged_model(route) if isinstance(route, dict) else ''
                usage = data.get('usage')
                counts = None
                if isinstance(usage, dict):
                    fields = [usage.get(key, 0) for key in ('inputTokens', 'cacheReadTokens', 'cacheWriteTokens', 'outputTokens')]
                    if all(type(count) is int and count >= 0 for count in fields):
                        counts = tuple(fields)
                yield kind, millis / 1000, data.get('turn'), data.get('reason'), model or logged_model(data), counts
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
