"""Persist dashboard display preferences without changing collected source data."""
import copy
import json
from datetime import date
from pathlib import Path
import threading

from remote_access import secure_write


class UISettings:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def get(self):
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                return {'hide_email': data.get('hide_email', False) is True,
                        'public_overview': data.get('public_overview', False) is True,
                        'subscriptions': data.get('subscriptions', {})}
            except FileNotFoundError:
                return {'hide_email': False, 'public_overview': False, 'subscriptions': {}}

    def save(self, data):
        if not isinstance(data, dict):
            raise ValueError('Settings must be a JSON object')
        if 'hide_email' in data and not isinstance(data['hide_email'], bool):
            raise ValueError('hide_email must be true or false')
        if 'public_overview' in data and not isinstance(data['public_overview'], bool):
            raise ValueError('public_overview must be true or false')
        subscriptions = None
        if 'subscriptions' in data:
            if not isinstance(data['subscriptions'], dict):
                raise ValueError('Subscriptions must be a JSON object')
            subscriptions = {}
            for source, value in data['subscriptions'].items():
                if source not in ('codex', 'agy', 'cc') or not isinstance(value, dict):
                    raise ValueError('Invalid subscription source')
                start, end = value.get('start'), value.get('end') or ''
                try:
                    if not isinstance(start, str) or date.fromisoformat(start).isoformat() != start:
                        raise ValueError()
                    if end and (not isinstance(end, str) or date.fromisoformat(end).isoformat() != end or end <= start):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ValueError('Use valid YYYY-MM-DD subscription dates; end must follow start') from None
                subscriptions[source] = {'start': start, 'end': end}
        with self.lock:
            settings = self.get()
            if 'hide_email' in data:
                settings['hide_email'] = data['hide_email']
            if 'public_overview' in data:
                settings['public_overview'] = data['public_overview']
            if subscriptions is not None:
                settings['subscriptions'] = subscriptions
            secure_write(self.path, json.dumps(settings))
            return settings

    def public_payload(self, payload):
        settings = self.get()
        result = copy.deepcopy(payload)
        if isinstance(result, dict):
            for source, dates in settings['subscriptions'].items():
                quotas = result.get('quotas', result)
                quota = quotas.get(source)
                if isinstance(quota, dict):
                    quota.update(subscription_start=dates['start'], subscription_until=dates['end'] or None,
                                 subscription_manual=True)
                    if isinstance(quota.get('live'), dict):
                        quota['live'].update(subscription_start=dates['start'], subscription_until=dates['end'] or None)
                if 'plans' in result and any(p.get('source') == source for p in result['plans']):
                    previous = [p for p in result['plans'] if p.get('source') == source]
                    plan = max(previous, key=lambda p: p.get('from', ''), default={})
                    result['plans'] = [p for p in result['plans'] if p.get('source') != source]
                    result['plans'].append({**plan, 'source': source, 'name': plan.get('name', source),
                                            'from': dates['start'], 'until': dates['end'] or None, 'manual': True})
        if settings['hide_email']:
            def redact(value):
                if isinstance(value, dict):
                    for key in value:
                        if key.lower() in ('email', 'user_email', 'account_email'):
                            value[key] = None
                        else:
                            redact(value[key])
                elif isinstance(value, list):
                    for item in value:
                        redact(item)
            redact(result)
        if isinstance(result, dict):
            result['ui_settings'] = settings
        return result
