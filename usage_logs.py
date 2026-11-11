"""Read model and usage metadata from local agent logs."""
from contextlib import closing
import json
import os
from pathlib import Path
import re

from compressed_logs import iter_log_lines

DSH_HOME = Path(os.environ.get('DSH_HOME') or Path.home() / '.dsh').expanduser()
AGY_SELECTION = re.compile(r"changed setting `Model Selection` from .*? to ([^\n]+?)\. No need")
DSH_JOURNAL = re.compile(r'session(?:\.v([0-9]+))?\.jsonl(?:\.(zst|zstd))?$')


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
