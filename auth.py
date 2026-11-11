"""Single administrator password, short-lived sessions and Access setup verification."""
from __future__ import annotations

import base64
import hashlib
import getpass
import hmac
from http.cookies import CookieError, SimpleCookie
import json
import math
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import urllib.request

from remote_access import secure_write
from login_security import LoginSecurity, resolve_client_ip

SESSION_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 600_000


def configure_password(manager, *, reset=False, interactive=None, password_input=None):
    if manager.configured and not reset:
        return False
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise ValueError('Password setup required. Run python3 server.py --set-password in a terminal first. / 请先在终端设置密码。')
    read = password_input or getpass.getpass
    print('Set dashboard password / 设置面板登录密码（10–256 characters / 字符）', flush=True)
    while True:
        try:
            password = read('New password / 新密码: ')
            repeated = read('Confirm password / 再次输入密码: ')
        except (EOFError, KeyboardInterrupt):
            raise ValueError('Password setup canceled / 密码设置已取消') from None
        if password != repeated:
            print('Passwords do not match / 两次输入不一致', flush=True)
            continue
        try:
            manager.set_password(password)
        except ValueError:
            print('Use 10–256 characters / 请使用 10–256 个字符', flush=True)
            continue
        print('Password saved / 密码已保存', flush=True)
        return True


class AuthManager:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._sessions, self._keys = {}, {}
        self._security = LoginSecurity(self.path.with_name('login-security.json'), lock=self._lock)
        self._password = None
        if self.path.exists():
            try:
                self._password = json.loads(self.path.read_text())
                if not isinstance(self._password, dict):
                    self._password = {}
            except (OSError, ValueError):
                self._password = {}  # Corrupt credentials must not reopen first-time setup.

    @property
    def configured(self):
        return self._password is not None

    def set_password(self, password):
        if not isinstance(password, str) or not 10 <= len(password) <= 256:
            raise ValueError('密码长度须为 10–256 个字符')
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
        record = {'salt': salt, 'hash': digest, 'iterations': PASSWORD_ITERATIONS}
        with self._lock:
            secure_write(self.path, json.dumps(record))
            self._password = record
            self._sessions.clear()

    def verify_password(self, password):
        if not isinstance(password, str) or len(password) > 256:
            return False
        with self._lock:
            record = self._password
        if not record or record.get('iterations') != PASSWORD_ITERATIONS:
            return False
        try:
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), PASSWORD_ITERATIONS).hex()
            return hmac.compare_digest(digest, record['hash'])
        except (KeyError, TypeError, ValueError):
            return False

    def login(self, password, client):
        # ponytail: one process serializes attempts; use transactional storage before adding workers.
        with self._lock:
            self._security.check(client)
            if not self.verify_password(password):
                self._security.failure(client)
                raise ValueError('密码不正确')
            self._security.success(client)
            return self.new_session()

    def security_status(self):
        return self._security.status()

    def configure_security(self, policy, client):
        return self._security.configure(policy, client)

    def unblock_ip(self, ip, client):
        return self._security.unblock(ip, client)

    @staticmethod
    def _cookie_token(cookie):
        try:
            value = SimpleCookie(cookie or '').get('ai_session')
            return value.value if value else ''
        except CookieError:
            return ''

    def new_session(self):
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > time.time()}
            if len(self._sessions) >= 128:
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[hashlib.sha256(token.encode()).hexdigest()] = time.time() + SESSION_SECONDS
        return token

    def authenticated(self, cookie):
        token = self._cookie_token(cookie)
        with self._lock:
            return bool(token and self._sessions.get(hashlib.sha256(token.encode()).hexdigest(), 0) > time.time())

    def logout(self, cookie):
        token = self._cookie_token(cookie)
        with self._lock:
            self._sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def _signing_keys(self, team):
        with self._lock:
            cached = self._keys.get(team)
            if cached and cached[0] > time.time():
                return cached[1]
            request = urllib.request.Request('https://' + team + '/cdn-cgi/access/certs',
                                             headers={'User-Agent': 'ai-dashboard/1.0'})
            with urllib.request.urlopen(request, timeout=8) as response:
                keys = json.loads(response.read(100_000))['public_certs']
            self._keys[team] = (time.time() + 600, keys)
            return keys

    def access_email(self, token, context):
        """Only a signed JWT for our configured app can authorize initial setup."""
        if not token or len(token) > 16_384 or not context:
            return None
        team, audience = context.get('team', ''), context.get('aud')
        if not re.fullmatch(r'[a-z0-9-]+\.cloudflareaccess\.com', team) or not audience:
            return None
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
            decode = lambda value: base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
            header, payload, signature = token.split('.')
            metadata, claims = json.loads(decode(header)), json.loads(decode(payload))
            if metadata.get('alg') != 'RS256' or not metadata.get('kid'):
                return None
            now = time.time()
            exp, nbf = claims.get('exp'), claims.get('nbf', 0)
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (exp, nbf)):
                return None
            if exp <= now or nbf > now or claims.get('iss') != 'https://' + team or claims.get('type') != 'app':
                return None
            audiences = claims.get('aud')
            if not isinstance(audiences, list) or audience not in audiences:
                return None
            email = claims.get('email')
            if not isinstance(email, str) or email.lower() not in [e.lower() for e in context.get('allowed_emails', [])]:
                return None
            keys = self._signing_keys(team)
            cert = next(item['cert'] for item in keys if item.get('kid') == metadata['kid']).encode()
            key = (x509.load_pem_x509_certificate(cert).public_key() if b'BEGIN CERTIFICATE' in cert
                   else serialization.load_pem_public_key(cert))
            if not isinstance(key, rsa.RSAPublicKey):
                return None
            key.verify(decode(signature), (header + '.' + payload).encode(), padding.PKCS1v15(), hashes.SHA256())
            return email
        except Exception:
            return None
