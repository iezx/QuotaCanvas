"""Immutable snapshots of quota exhaustion observed by this running service."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from remote_access import secure_write


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _minutes(window):
    value = _number(window.get('window_minutes') or (window.get('forecast') or {}).get('window_minutes'))
    return int(value) if value and value.is_integer() else {'5h': 300, 'weekly': 10080}.get(window.get('window'))


def _windows(quotas):
    for role in ('primary', 'secondary'):
        window = (quotas.get('codex') or {}).get(role)
        if isinstance(window, dict):
            yield 'codex', '', role, window
    for group in ((quotas.get('agy') or {}).get('live') or {}).get('groups', []):
        for window in group.get('buckets', []):
            yield 'agy', str(group.get('name') or ''), str(window.get('bucket_id') or window.get('name') or ''), window
    for window in (quotas.get('cc') or {}).get('buckets', []):
        yield 'cc', '', str(window.get('bucket_id') or window.get('name') or ''), window


class QuotaLog:
    MAX_LOGS = 500

    def __init__(self, path):
        self.path, self.lock = Path(path), threading.RLock()

    def _load(self):
        try:
            rows = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return []
        if not isinstance(rows, list):
            raise ValueError('Invalid quota-window log')
        return rows[:self.MAX_LOGS]

    def list(self):
        with self.lock:
            return self._load()

    def record(self, quotas):
        observed = int(time.time())
        with self.lock:
            rows = self._load()
            known = {row['id'] for row in rows}
            count = 0
            for source, group, bucket, window in _windows(quotas):
                reset, minutes = _number(window.get('resets_at')), _minutes(window)
                if not reset or not reset.is_integer() or not minutes or not bucket:
                    continue
                used = _number(window.get('used_percent'))
                raw = _number(window.get('raw_used_percent'))
                if (used is None or used < 100) and window.get('is_reset') and reset <= observed:
                    used = raw
                if used is None or used < 100:
                    continue
                reset = int(reset)
                identity = json.dumps([source, group, bucket, reset, minutes], ensure_ascii=False)
                key = hashlib.sha256(identity.encode()).hexdigest()
                if key in known:
                    continue
                models = []
                for model in window.get('cost_models') or []:
                    if not isinstance(model, dict) or not isinstance(model.get('model'), str):
                        continue
                    models.append({'model': model['model'], 'tokens': _number(model.get('tokens')),
                                   'requests': _number(model.get('requests')), 'cost': _number(model.get('cost'))})
                amount = window.get('cost_observed') if 'cost_observed' in window else window.get('cost_used')
                total = None if window.get('cost_is_estimated') else _number(window.get('cost_quota_total'))
                rows.insert(0, {'id': key, 'source': source, 'group': group, 'bucket': bucket,
                                'label': str(window.get('label') or window.get('name') or bucket),
                                'window_minutes': minutes, 'resets_at': reset, 'observed_at': observed,
                                'used_percent': used, 'cost_used': _number(amount), 'cost_quota_total': total,
                                'models': models})
                known.add(key)
                count += 1
            if count:
                secure_write(self.path, json.dumps(rows[:self.MAX_LOGS], ensure_ascii=False))
            return count
