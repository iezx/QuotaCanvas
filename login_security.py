"""Bounded, private login-attempt and audit state for the single-process server."""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import threading
import time

from remote_access import secure_write

DEFAULT_POLICY = {'max_failures': 8, 'window_seconds': 900, 'block_seconds': 900}
POLICY_LIMITS = {'max_failures': (1, 100), 'window_seconds': (10, 86400), 'block_seconds': (10, 86400)}
MAX_CLIENTS = 1024
MAX_AUDIT = 500
MAX_STATE_BYTES = 4_000_000
GLOBAL_MAX_FAILURES = 120
GLOBAL_WINDOW_SECONDS = 60
GLOBAL_BLOCK_SECONDS = 5
EVENTS = {'login_failure', 'login_success', 'login_blocked', 'ip_blocked', 'ip_unblocked',
          'policy_updated', 'block_expired', 'global_blocked'}
UNAVAILABLE = 'Login security state unavailable; restore login-security.json before retrying / 登录保护数据不可用，请修复后重试'


def _ip(value):
    if not isinstance(value, str) or len(value) > 64 or '%' in value:
        raise ValueError('Invalid IP address / IP 地址无效')
    address = ipaddress.ip_address(value)
    return str(address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address)


def resolve_client_ip(peer, cloudflare_ip=None, *, access_verified=False):
    """The caller must verify this app's Access JWT and tunnel host before trusting a header."""
    address = _ip(peer)
    if access_verified is True and ipaddress.ip_address(address).is_loopback:
        try:
            return _ip(cloudflare_ip)
        except ValueError:
            pass
    return address


def _client(value):
    try:
        return _ip(value)
    except ValueError:
        # Keep the historical AuthManager API's symbolic clients distinct without logging arbitrary strings.
        if isinstance(value, str) and re.fullmatch(r'client-[a-f0-9]{32}', value):
            return value
        return 'client-' + hashlib.sha256(str(value).encode('utf-8', errors='replace')).hexdigest()[:32]


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _policy(value, *, partial=False):
    if not isinstance(value, dict) or not value or set(value) - set(DEFAULT_POLICY):
        raise ValueError('Invalid login protection settings / 登录保护设置无效')
    if not partial and set(value) != set(DEFAULT_POLICY):
        raise ValueError('Incomplete login protection settings / 登录保护设置不完整')
    for key, item in value.items():
        low, high = POLICY_LIMITS[key]
        if type(item) is not int or not low <= item <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high} / 须为范围内的整数')
    return dict(value)


class LoginSecurity:
    def __init__(self, path: Path, lock=None):
        self.path = Path(path)
        self._lock = lock or threading.RLock()
        self._unavailable = False
        self._state = {'version': 1, 'policy': dict(DEFAULT_POLICY), 'clients': {},
                       'global': {'failures': [], 'blocked_until': 0}, 'audit': []}
        try:
            with self.path.open('rb') as source:
                raw = source.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError('Oversized security state')
            state = json.loads(raw)
            self._validate(state)
            self._state = state
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            self._unavailable = True

    @staticmethod
    def _validate(state):
        if not isinstance(state, dict) or set(state) != {'version', 'policy', 'clients', 'global', 'audit'} or type(state['version']) is not int or state['version'] != 1:
            raise ValueError('Invalid security state')
        _policy(state['policy'])
        clients, global_state, audit = state['clients'], state['global'], state['audit']
        if not isinstance(clients, dict) or len(clients) > MAX_CLIENTS:
            raise ValueError('Invalid client state')
        for key, entry in clients.items():
            if not isinstance(key, str) or _client(key) != key or not isinstance(entry, dict):
                raise ValueError('Invalid client entry')
            if set(entry) != {'failures', 'blocked_until', 'last_seen'} or not _number(entry['blocked_until']) or not _number(entry['last_seen']):
                raise ValueError('Invalid client entry')
            if not isinstance(entry['failures'], list) or len(entry['failures']) > POLICY_LIMITS['max_failures'][1] or not all(_number(stamp) for stamp in entry['failures']):
                raise ValueError('Invalid failure state')
        if not isinstance(global_state, dict) or set(global_state) != {'failures', 'blocked_until'} or not _number(global_state['blocked_until']):
            raise ValueError('Invalid global state')
        if not isinstance(global_state['failures'], list) or len(global_state['failures']) > GLOBAL_MAX_FAILURES or not all(_number(stamp) for stamp in global_state['failures']):
            raise ValueError('Invalid global failures')
        if not isinstance(audit, list) or len(audit) > MAX_AUDIT:
            raise ValueError('Invalid audit state')
        for row in audit:
            if not isinstance(row, dict) or set(row) - {'time', 'event', 'ip', 'target_ip', 'blocked_until', 'reason', 'policy'}:
                raise ValueError('Invalid audit record')
            if not _number(row.get('time')) or row.get('event') not in EVENTS or not isinstance(row.get('ip'), str) or _client(row['ip']) != row['ip']:
                raise ValueError('Invalid audit record')
            if 'target_ip' in row and _ip(row['target_ip']) != row['target_ip']:
                raise ValueError('Invalid audit target')
            if 'blocked_until' in row and not _number(row['blocked_until']):
                raise ValueError('Invalid audit expiry')
            if 'reason' in row and row['reason'] not in {'ip', 'global', 'capacity', 'policy'}:
                raise ValueError('Invalid audit reason')
            if 'policy' in row:
                _policy(row['policy'])

    def _ready(self):
        if self._unavailable:
            raise PermissionError(UNAVAILABLE)

    def _save(self):
        try:
            secure_write(self.path, json.dumps(self._state, ensure_ascii=True, separators=(',', ':')))
        except OSError:
            self._unavailable = True
            raise PermissionError(UNAVAILABLE) from None

    def _audit(self, event, ip, now, **fields):
        self._state['audit'].append({'time': now, 'event': event, 'ip': _client(ip), **fields})
        del self._state['audit'][:-MAX_AUDIT]

    def _prune(self, now):
        self._ready()
        clients, policy = self._state['clients'], self._state['policy']
        for ip, entry in list(clients.items()):
            if entry['blocked_until'] > now:
                continue
            if entry['blocked_until']:
                self._audit('block_expired', ip, now)
                entry['failures'], entry['blocked_until'] = [], 0
            entry['failures'] = [stamp for stamp in entry['failures'] if stamp > now - policy['window_seconds']]
            if not entry['failures']:
                del clients[ip]
        guard = self._state['global']
        if guard['blocked_until'] and guard['blocked_until'] <= now:
            # A new cooldown needs a fresh batch of guesses; rejected retries never renew it.
            guard['failures'], guard['blocked_until'] = [], 0
        guard['failures'] = [stamp for stamp in guard['failures'] if stamp > now - GLOBAL_WINDOW_SECONDS]

    def check(self, client):
        with self._lock:
            now, ip = time.time(), _client(client)
            self._prune(now)
            clients = self._state['clients']
            entry = clients.get(ip)
            blocked_until, reason = 0, ''
            if entry and entry['blocked_until'] > now:
                blocked_until, reason = entry['blocked_until'], 'ip'
            elif self._state['global']['blocked_until'] > now:
                blocked_until, reason = self._state['global']['blocked_until'], 'global'
            elif ip not in clients and len(clients) >= MAX_CLIENTS and all(row['blocked_until'] > now for row in clients.values()):
                blocked_until, reason = min(row['blocked_until'] for row in clients.values()), 'capacity'
            if reason:
                self._audit('login_blocked', ip, now, reason=reason, blocked_until=blocked_until)
                self._save()
                seconds = max(1, math.ceil(blocked_until - now))
                raise PermissionError(f'Login blocked; retry in {seconds}s / 登录暂时受限，请在 {seconds} 秒后重试')

    def failure(self, client):
        with self._lock:
            self.check(client)
            now, ip = time.time(), _client(client)
            clients, policy = self._state['clients'], self._state['policy']
            if ip not in clients:
                if len(clients) >= MAX_CLIENTS:
                    # Rotating IPs cannot evict active blocks; the global guard also limits rotations.
                    oldest = min((key for key in clients if clients[key]['blocked_until'] <= now),
                                 key=lambda key: clients[key]['last_seen'])
                    del clients[oldest]
                clients[ip] = {'failures': [], 'blocked_until': 0, 'last_seen': now}
            entry = clients[ip]
            entry['failures'].append(now)
            entry['last_seen'] = now
            self._audit('login_failure', ip, now)
            if len(entry['failures']) >= policy['max_failures']:
                entry['blocked_until'] = now + policy['block_seconds']
                self._audit('ip_blocked', ip, now, blocked_until=entry['blocked_until'])
            guard = self._state['global']
            guard['failures'].append(now)
            if len(guard['failures']) >= GLOBAL_MAX_FAILURES:
                guard['blocked_until'] = now + GLOBAL_BLOCK_SECONDS
                self._audit('global_blocked', ip, now, blocked_until=guard['blocked_until'])
            self._save()

    def success(self, client):
        with self._lock:
            self.check(client)
            self._state['clients'].pop(_client(client), None)
            self._audit('login_success', client, time.time())
            self._save()

    def configure(self, policy, client):
        with self._lock:
            self._ready()
            changes = _policy(policy, partial=True)
            self._state['policy'].update(changes)
            now = time.time()
            self._prune(now)
            for ip, entry in self._state['clients'].items():
                if not entry['blocked_until'] and len(entry['failures']) >= self._state['policy']['max_failures']:
                    entry['blocked_until'] = now + self._state['policy']['block_seconds']
                    self._audit('ip_blocked', ip, now, reason='policy', blocked_until=entry['blocked_until'])
            self._audit('policy_updated', client, now, policy=dict(self._state['policy']))
            self._save()
            return self.status()

    def unblock(self, ip, client):
        with self._lock:
            self._ready()
            ip = _ip(ip)
            self._prune(time.time())
            self._state['clients'].pop(ip, None)
            self._audit('ip_unblocked', client, time.time(), target_ip=ip)
            self._save()
            return self.status()

    def status(self):
        with self._lock:
            now = time.time()
            self._prune(now)
            self._save()
            return copy.deepcopy({
                'policy': self._state['policy'],
                'blocked': sorted(({'ip': ip, 'failed_attempts': len(entry['failures']), 'blocked_until': entry['blocked_until']}
                                   for ip, entry in self._state['clients'].items() if entry['blocked_until'] > now),
                                  key=lambda entry: entry['blocked_until'], reverse=True),
                'audit': list(reversed(self._state['audit'])),
                'global': {'blocked_until': self._state['global']['blocked_until'], 'max_failures': GLOBAL_MAX_FAILURES,
                           'window_seconds': GLOBAL_WINDOW_SECONDS, 'cooldown_seconds': GLOBAL_BLOCK_SECONDS},
            })
