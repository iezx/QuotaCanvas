"""One private Cloudflare Access entry for this dashboard; disabled until configured."""
from __future__ import annotations

import copy
import fnmatch
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlencode
import urllib.error
import urllib.request


class RemoteAccessError(RuntimeError):
    pass


def secure_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            if hasattr(os, 'fchmod'):
                os.fchmod(output.fileno(), 0o600)
            else:
                os.chmod(temporary, 0o600)
            output.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CloudflareAPI:
    def __init__(self, token: str):
        self.token = token

    def request(self, method: str, path: str, body=None):
        label, permission = next((
            (label, permission) for fragment, label, permission in (
                ('/dns_records', 'DNS 记录', 'Zone → DNS → Edit（包含读取），且 Zone 资源范围包含目标域名'),
                ('/access/organizations', 'Zero Trust 团队', 'Account → Access: Organizations → Read'),
                ('/access/apps', 'Access 应用与策略', 'Account → Access: Apps and Policies → Edit'),
                ('/cfd_tunnel', 'Tunnel 配置', 'Account → Cloudflare Tunnel → Edit'),
                ('/zones', '域名区域', 'Zone → Zone → Read，且资源范围包含目标域名'),
            ) if fragment in path
        ), ('Cloudflare 接口', '此接口对应的账号或域名权限'))
        request = urllib.request.Request(
            'https://api.cloudflare.com/client/v4' + path,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json',
                     'User-Agent': 'ai-dashboard/1.0'},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                payload = json.load(error)
            except (ValueError, OSError):
                payload = {}
            errors = payload.get('errors', []) if isinstance(payload, dict) else []
            detail = '; '.join(f"{item.get('code', '')}: {item.get('message', '')}"
                               for item in errors if isinstance(item, dict))
            if self.token:
                detail = detail.replace(self.token, '[redacted]')
            hint = f'。请检查 {permission} 权限及其资源范围' if error.code in (401, 403) else ''
            raise RemoteAccessError(f'{label}：Cloudflare HTTP {error.code}: {detail[:240]}{hint}') from None
        except OSError:
            raise RemoteAccessError('无法连接 Cloudflare，请检查本机网络后重试') from None
        if not isinstance(payload, dict) or payload.get('success') is not True:
            raise RemoteAccessError('Cloudflare 未确认请求成功，请检查 API Token 权限')
        return payload.get('result')


class RemoteAccessManager:
    def __init__(self, config_path: Path, *, binary=None, client_factory=CloudflareAPI,
                 on_bind_change=None, origin_port=8088):
        self.config_path = Path(config_path)
        self.token_file = self.config_path.with_name('remote_tunnel.token')
        self.binary = binary or shutil.which('cloudflared') or '/usr/local/bin/cloudflared'
        self.client_factory = client_factory
        self.on_bind_change = on_bind_change
        self.origin_port = origin_port
        self.lan_host = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._proc = None
        self._busy = False
        self._verified = False
        self._monitor = None
        self._info = {}
        self._config = {'hostname': '', 'allowed_emails': [], 'api_token': '', 'enabled': False,
                        'local_only': False, 'auto_start': True, 'resources': {}}
        self._phase, self._message = 'disabled', '远程访问未启用'
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text())
                if not isinstance(loaded, dict):
                    raise ValueError('invalid config')
                self._config.update(loaded)
            except (OSError, ValueError):
                self._config['local_only'] = True
                self._phase, self._message = 'error', '远程访问配置损坏，已保留仅本机访问'
        if self._config['enabled']:
            self._config['local_only'] = True
            self._phase, self._message = 'starting', '正在恢复已启用的远程访问'

    @property
    def local_only(self):
        with self._lock:
            return bool(self._config['local_only'])

    def _persist(self):
        secure_write(self.config_path, json.dumps(self._config, ensure_ascii=False, indent=2))

    def _set_phase(self, phase, message):
        with self._lock:
            self._phase, self._message = phase, message

    def _binary_available(self):
        return os.path.isfile(self.binary) and os.access(self.binary, os.X_OK)

    def status(self):
        with self._lock:
            phase, message = self._phase, self._message
            if self._config['enabled'] and not self._busy and self._proc is not None:
                if self._proc.poll() is not None:
                    phase, message = 'error', '连接组件已退出，正在等待重新连接'
                elif self._ready():
                    phase, message = 'connected', '远程访问已连接，需通过 Access 登录'
                else:
                    phase, message = 'starting', '连接组件运行中，正在连接 Cloudflare'
            hostname = self._config['hostname']
            return {
                'hostname': hostname, 'allowed_emails': list(self._config['allowed_emails']),
                'api_token_saved': bool(self._config['api_token']), 'enabled': bool(self._config['enabled']),
                'local_only': bool(self._config['local_only']), 'auto_start': self._config['auto_start'],
                'phase': phase, 'message': message,
                'can_resume': self._config['enabled'] and not self._busy and not self._verified,
                'public_url': 'https://' + hostname if hostname else None,
                'cloudflared_available': self._binary_available(),
                'zone_name': self._info.get('zone_name', ''), 'account_name': self._info.get('account_name', ''),
                'lan_url': f'http://{self.lan_host}:{self.origin_port}' if self.lan_host else None,
            }

    def auth_context(self):
        with self._lock:
            resources = self._config['resources']
            if not self._config['enabled'] or resources.get('revocation_pending'):
                return {}
            return {'team': resources.get('access_team', ''), 'aud': resources.get('access_aud', ''),
                    'allowed_emails': list(self._config['allowed_emails'])}

    def set_auto_start(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Auto-start must be a boolean')
        with self._lock:
            previous = self._config['auto_start']
            self._config['auto_start'] = enabled
            try:
                self._persist()
            except OSError:
                self._config['auto_start'] = previous
                raise
            return self.status()

    def save(self, body):
        with self._lock:
            if self._busy or self._config['enabled']:
                raise RemoteAccessError('请先停用远程访问并等待当前操作完成，再修改设置')
            hostname = body.get('hostname', self._config['hostname'])
            emails = body.get('allowed_emails', self._config['allowed_emails'])
            token = body.get('api_token', '')
            if not isinstance(hostname, str) or not isinstance(token, str):
                raise ValueError('域名和 API Token 必须是文本')
            hostname = hostname.strip().rstrip('.').lower()
            if hostname:
                try:
                    hostname = hostname.encode('idna').decode('ascii')
                except UnicodeError:
                    raise ValueError('域名格式不正确') from None
                labels = hostname.split('.')
                if (len(hostname) > 253 or len(labels) < 2 or any(
                        not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)):
                    raise ValueError('只填写完整域名，不包含 https://、端口或路径')
                try:
                    ipaddress.ip_address(hostname)
                except ValueError:
                    pass
                else:
                    raise ValueError('请使用 Cloudflare 托管的域名，不能填写 IP 地址')
            if isinstance(emails, str):
                emails = re.split(r'[\s,;]+', emails.strip()) if emails.strip() else []
            if not isinstance(emails, list) or len(emails) > 20:
                raise ValueError('最多填写 20 个允许登录的完整邮箱地址')
            normalized = []
            for email in emails:
                if not isinstance(email, str):
                    raise ValueError('邮箱地址必须是文本')
                email = email.strip().lower()
                if len(email) > 320 or not re.fullmatch(r'[^@\s<>*,;]+@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', email):
                    raise ValueError('请填写完整邮箱地址，不能使用通配符')
                if email not in normalized:
                    normalized.append(email)
            owned_host = self._config['resources'].get('hostname')
            if owned_host and hostname != owned_host:
                raise ValueError('此入口已经配置过域名；请保留该域名，避免覆盖或遗留其他入口')
            self._config.update(hostname=hostname, allowed_emails=normalized,
                                api_token=token.strip() or self._config['api_token'])
            self._persist()
            self._phase, self._message = 'disabled', '设置已保存，尚未启用远程访问'
            self._info = {}
            return self.status()

    def _validated(self):
        with self._lock:
            config = copy.deepcopy(self._config)
        if not config['hostname'] or not config['allowed_emails'] or not config['api_token']:
            raise ValueError('请先保存域名、至少一个允许登录的邮箱和 Cloudflare API Token')
        return config

    def _inspect(self, config):
        client = self.client_factory(config['api_token'])
        zone = None
        labels = config['hostname'].split('.')
        for index in range(len(labels) - 1):
            zones = client.request('GET', '/zones?' + urlencode({'name': '.'.join(labels[index:]), 'status': 'active'}))
            zone = next((item for item in zones if config['hostname'] == item['name'] or config['hostname'].endswith('.' + item['name'])), None)
            if zone:
                break
        if not zone:
            raise RemoteAccessError('未找到此域名的有效 Cloudflare 区域，请检查托管状态和 Token 的 Zone Read 权限')
        account = zone['account']['id']
        resources = config['resources']
        if resources.get('account_id') and (resources['account_id'] != account or resources['zone_id'] != zone['id']):
            raise RemoteAccessError('保存的入口属于其他 Cloudflare 账号，不能覆盖')
        organization = client.request('GET', f'/accounts/{account}/access/organizations')
        auth_domain = (organization or {}).get('auth_domain', '')
        if not re.fullmatch(r'[a-z0-9-]+\.cloudflareaccess\.com', auth_domain):
            raise RemoteAccessError('请先在 Cloudflare 完成 Zero Trust 初始化和登录方式设置')
        page = 1
        while True:
            apps = client.request('GET', f'/accounts/{account}/access/apps?' + urlencode({'page': page, 'per_page': 50}))
            for app in apps:
                if app.get('id') == resources.get('app_id'):
                    continue
                destinations = [app.get('domain', '')] + [
                    destination.get('uri') or destination.get('hostname', '')
                    for destination in app.get('destinations', []) if destination.get('type') == 'public'
                ]
                if any(fnmatch.fnmatchcase(config['hostname'], value.lower().split('/')[0].split(':')[0])
                       for value in destinations if isinstance(value, str) and value):
                    raise RemoteAccessError('此域名或其路径已有其他 Access 应用，请使用专用子域名，避免覆盖原有策略')
            if len(apps) < 50:
                break
            page += 1
        records = client.request('GET', f'/zones/{zone["id"]}/dns_records?' + urlencode({'name': config['hostname']}))
        if any(record['id'] != resources.get('dns_id') or record.get('type') != 'CNAME'
               or record.get('content') != resources.get('tunnel_id', '') + '.cfargotunnel.com' for record in records):
            raise RemoteAccessError('此域名已有其他 DNS 记录，请使用空闲的子域名')
        with self._lock:
            self._info = {'zone_name': zone['name'], 'account_name': zone['account'].get('name', '')}
        return client, account, zone['id'], auth_domain.split('.')[0], bool(records)

    def check(self):
        config = self._validated()
        self._inspect(config)
        self._set_phase('ready', 'Cloudflare 账号、域名和 Access 团队检查通过，尚未启用')
        return self.status()

    def _record_resource(self, **values):
        with self._lock:
            self._config['resources'].update(values)
            self._persist()

    def enable(self):
        config = self._validated()
        if not self._binary_available():
            raise RemoteAccessError('本机尚未安装 cloudflared 连接组件')
        self._set_phase('configuring', '正在验证 Cloudflare 设置')
        client, account, zone, team, dns_exists = self._inspect(config)
        self._record_resource(account_id=account, zone_id=zone, hostname=config['hostname'])
        resources = self._config['resources']
        app_path = f'/accounts/{account}/access/apps'
        self._set_phase('configuring', '正在配置整个域名及 API 的 Access 登录保护')
        app_body = {'name': 'AI Dashboard - ' + config['hostname'], 'domain': config['hostname'],
                    'type': 'self_hosted', 'session_duration': '8h', 'http_only_cookie_attribute': True,
                    'same_site_cookie_attribute': 'lax', 'app_launcher_visible': False}
        if not resources.get('app_id'):
            app = client.request('POST', app_path, app_body)
            self._record_resource(app_id=app['id'])
        else:
            app = client.request('GET', app_path + '/' + resources['app_id'])
        if app.get('domain') != config['hostname']:
            raise RemoteAccessError('Access 应用的域名不符合设置，已停止启用')
        if not app.get('aud'):
            raise RemoteAccessError('Access 应用没有有效的 audience，已停止启用')
        policy_path = app_path + '/' + resources['app_id'] + '/policies'
        policies = client.request('GET', policy_path)
        if any(policy['id'] != resources.get('policy_id') for policy in policies):
            raise RemoteAccessError('Access 应用存在其他策略，已停止以避免扩大访问权限')
        policy_body = {'name': 'Dashboard email allowlist', 'decision': 'allow', 'precedence': 1,
                       'include': [{'email': {'email': email}} for email in config['allowed_emails']],
                       'exclude': [], 'require': []}
        policy_changed = bool(policies) and any(
            policies[0].get(key, [] if key != 'decision' else None) != policy_body[key]
            for key in ('decision', 'include', 'exclude', 'require')
        )
        if policy_changed:
            self._record_resource(revocation_pending=True)
        if resources.get('policy_id'):
            client.request('PUT', policy_path + '/' + resources['policy_id'], policy_body)
        else:
            policy = client.request('POST', policy_path, policy_body)
            self._record_resource(policy_id=policy['id'])
        # No tunnel or DNS is published until the exact email policy exists.
        confirmed = client.request('GET', policy_path)
        if (len(confirmed) != 1 or confirmed[0].get('decision') != 'allow'
                or confirmed[0].get('include') != policy_body['include']
                or confirmed[0].get('exclude') or confirmed[0].get('require')):
            raise RemoteAccessError('Access 策略校验未通过，已停止启用')
        if resources.get('revocation_pending'):
            client.request('POST', app_path + '/' + resources['app_id'] + '/revoke_tokens')
            self._record_resource(revocation_pending=False)
        tunnel_path = f'/accounts/{account}/cfd_tunnel'
        if not resources.get('tunnel_id'):
            tunnel = client.request('POST', tunnel_path, {'name': 'ai-dashboard-' + hashlib.sha256(config['hostname'].encode()).hexdigest()[:12], 'config_src': 'cloudflare'})
            self._record_resource(tunnel_id=tunnel['id'])
        tunnel_path += '/' + resources['tunnel_id']
        ingress = [{'hostname': config['hostname'], 'service': f'http://127.0.0.1:{self.origin_port}',
                    'originRequest': {'access': {'required': True, 'teamName': team, 'audTag': [app['aud']]}}},
                   {'service': 'http_status:404'}]
        client.request('PUT', tunnel_path + '/configurations', {'config': {'ingress': ingress}})
        tunnel_config = client.request('GET', tunnel_path + '/configurations')
        confirmed_ingress = (tunnel_config or {}).get('config', {}).get('ingress', [])
        if (len(confirmed_ingress) != 2
                or any(confirmed_ingress[0].get(key) != ingress[0][key] for key in ('hostname', 'service'))
                or confirmed_ingress[0].get('path')
                or confirmed_ingress[0].get('originRequest', {}).get('access') != ingress[0]['originRequest']['access']
                or confirmed_ingress[1].get('service') != 'http_status:404'):
            raise RemoteAccessError('Tunnel 的 Access 校验配置未确认，已停止启用')
        self._record_resource(access_team=team + '.cloudflareaccess.com', access_aud=app['aud'])
        connector_token = client.request('GET', tunnel_path + '/token')
        if not isinstance(connector_token, str) or not connector_token:
            raise RemoteAccessError('Cloudflare 未返回连接凭据')
        secure_write(self.token_file, connector_token)
        self._set_phase('configuring', 'Access 已保护入口，正在配置域名和本机连接')
        if not dns_exists:
            dns = client.request('POST', f'/zones/{zone}/dns_records', {
                'name': config['hostname'], 'type': 'CNAME', 'content': resources['tunnel_id'] + '.cfargotunnel.com',
                'proxied': True, 'ttl': 1,
            })
            self._record_resource(dns_id=dns['id'])
        with self._lock:
            self._config['local_only'] = True
            self._persist()
        if self.on_bind_change and not config['local_only']:
            self.on_bind_change()
        with self._lock:
            self._config['enabled'] = True
            self._persist()
            self._verified = True
        self._start_connector()
        self._set_phase('starting', 'Access 已配置，连接组件正在连接 Cloudflare')
        return self.status()

    def begin(self, action):
        if action not in ('check', 'enable'):
            raise ValueError('不支持的操作')
        self._validated()
        with self._lock:
            if self._busy or (self._config['enabled'] and (action != 'enable' or self._verified)):
                raise RemoteAccessError('当前已有操作或远程访问正在运行，请先停用后重试')
            self._busy = True
            self._phase = 'checking' if action == 'check' else 'configuring'
            self._message = '正在检查 Cloudflare 设置' if action == 'check' else '正在准备受保护的远程入口'
        def worker():
            try:
                getattr(self, action)()
            except Exception as error:
                detail = str(error).replace(self._config['api_token'], '[redacted]')
                self._set_phase('error', detail[:500])
            finally:
                with self._lock:
                    self._busy = False
        threading.Thread(target=worker, daemon=True).start()
        return self.status()

    def _start_connector(self):
        with self._lock:
            if self._stop.is_set() or not self._config['enabled']:
                return
            if self._proc is not None and self._proc.poll() is None:
                return
            log_path = self.config_path.with_name('remote_access.log')
            fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, 'ab') as log:
                self._proc = subprocess.Popen([
                    self.binary, 'tunnel', '--no-autoupdate', '--metrics', '127.0.0.1:20242',
                    '--disable-path-normalization=false', 'run', '--token-file', str(self.token_file),
                ], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def _ready(self):
        try:
            with urllib.request.urlopen('http://127.0.0.1:20242/ready', timeout=0.4) as response:
                return response.status == 200
        except OSError:
            return False

    def _stop_connector(self):
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def disable(self, *, reset_binding=False):
        with self._lock:
            if self._busy:
                raise RemoteAccessError('请等待当前配置操作完成后再停用')
            self._config['enabled'] = False
            self._verified = False
            if reset_binding:
                self._config['local_only'] = False
            self._persist()
        self._stop_connector()
        self._set_phase('disabled', '远程访问已停用；已有 Access 保护保留，本机访问方式保持不变')
        return self.status()

    def start(self):
        """Called by the server, not on import; resume an explicitly enabled entry."""
        if self._config['enabled']:
            if self._config['auto_start']:
                try:
                    self.begin('enable')
                except (ValueError, RemoteAccessError) as error:
                    self._set_phase('error', str(error))
            else:
                self._set_phase('paused', '已关闭开机自动连接；可在本机或内网手动启动')
        retry_at = time.monotonic() + 60
        def monitor():
            nonlocal retry_at
            while not self._stop.wait(5):
                with self._lock:
                    restore = (self._config['enabled'] and self._config['auto_start']
                               and not self._verified and not self._busy and self._phase == 'error'
                               and time.monotonic() >= retry_at)
                    restart = (self._config['enabled'] and self._verified and not self._busy
                               and (self._proc is None or self._proc.poll() is not None))
                if restore:
                    retry_at = time.monotonic() + 60
                    try:
                        self.begin('enable')
                    except (ValueError, RemoteAccessError):
                        pass
                if restart:
                    try:
                        self._start_connector()
                    except OSError:
                        self._set_phase('error', '连接组件启动失败，稍后会重试')
        self._monitor = threading.Thread(target=monitor, daemon=True)
        self._monitor.start()

    def close(self):
        self._stop.set()
        self._stop_connector()
