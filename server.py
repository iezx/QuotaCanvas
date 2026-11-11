#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hmac
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer as BaseThreadingHTTPServer
import json
import ipaddress
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlparse, parse_qs

import conversations as conv
import quota_live as ql
import codex_commands
from agent_commands import command_list
from login_security import resolve_client_ip
from runtime_paths import get_data_dir
from quota_windows import QuotaLog
from auth import AuthManager, SESSION_SECONDS, configure_password
from ui_settings import UISettings
from pricing import PRICE_STORE, PRICE_RESEARCH, AGENTS, ID_RE, RESEARCH_PROMPT, find_agent, list_agent_models
from remote_access import RemoteAccessError, RemoteAccessManager
from static_web_cache import StaticWebCache
from task_activity import TaskActivity
from usage_logs import DSH_HOME

from collector import MODEL_PRICING, STATS_JSON_FILE, collect_all, print_cli_report

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = get_data_dir(BASE_DIR)
WEB_DIR = BASE_DIR / "web"
WEB_SERVE_DIR: Path | None = None

def _load_token() -> str:
    p = DATA_DIR / "api_token.txt"
    if os.environ.get("API_TOKEN"):
        return os.environ["API_TOKEN"]
    return p.read_text().strip() if p.is_file() else ''


API_TOKEN = _load_token()
PROTECTED = ("/api/conversations", "/api/conversation", "/api/send", "/api/schedules", "/api/remote-access",
             '/api/stats.json', '/api/refresh', '/api/quota', '/api/live', '/api/pricing', '/api/models', '/api/settings',
             '/api/pricing/research', '/api/commands', '/api/security', '/api/quota-windows', '/api/activity', '/api/activity/history',
             '/api/conversation/questions')
REMOTE_ACCESS = RemoteAccessManager(DATA_DIR / 'remote_access.json')
AUTH = AuthManager(DATA_DIR / 'password.json')
UI_SETTINGS = UISettings(DATA_DIR / 'ui_settings.json')
QUOTA_LOG = QuotaLog(DATA_DIR / 'quota_windows.json')
TASK_ACTIVITY = TaskActivity(conv.CODEX_HOME, conv.AGY_HOME, conv.CLAUDE_HOME, history_path=DATA_DIR / 'task_history.json', dsh_home=DSH_HOME)

_collect_lock = threading.Lock()
_latest_stats: dict | None = None


class ThreadingHTTPServer(BaseThreadingHTTPServer):
    """Keep slow or abusive connections from creating unbounded worker threads."""
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(64)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def display_payload(payload, language='zh'):
    result = UI_SETTINGS.public_payload(payload)
    if language != 'en':
        return result
    def localize(value, role=''):
        if isinstance(value, list):
            for item in value:
                localize(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                localize(item, key)
            forecast = value.get('forecast')
            minutes = value.get('window_minutes') or (forecast or {}).get('window_minutes')
            if forecast:
                value['forecast_text'] = ql.forecast_text(forecast, value.get('resets_at'), value, language='en')
            if value.get('cost_text'):
                value['cost_text'] = ql.cost_text(value, minutes, language='en')
            if minutes and (role in ('primary', 'secondary') or (isinstance(value.get('label'), str) and re.search(r'[\u4e00-\u9fff]', value['label']))):
                unit = f'{minutes // 1440}d' if minutes % 1440 == 0 else (f'{minutes // 60}h' if minutes % 60 == 0 else f'{minutes}m')
                prefix = role.title() + ' ' if role in ('primary', 'secondary') else ''
                value['label'] = f'{prefix}{unit} quota window'
    localize(result)
    return result


def refresh_stats(force: bool = False) -> dict:
    global _latest_stats
    with _collect_lock:
        data = collect_all(force_rescan=force)
        try:
            QUOTA_LOG.record(data.get('quotas') or {})
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(f'[quota-log] Could not save history: {type(error).__name__}', flush=True)
        _latest_stats = data
        return data


def background_updater(interval_sec: int) -> None:
    while True:
        try:
            refresh_stats(force=False)
        except Exception as exc:
            print(f"[updater] refresh error: {exc}", flush=True)
        time.sleep(max(5, interval_sec))


def activity_updater() -> None:
    while True:
        try:
            TASK_ACTIVITY.snapshot()
        except (OSError, ValueError) as error:
            print(f'[task-history] Could not update: {type(error).__name__}', flush=True)
        time.sleep(1)



def build_live() -> dict:
    """Live quotas (official APIs, fallback to local logs) + forecasts."""
    stats = json.loads(STATS_JSON_FILE.read_text(encoding="utf-8")) if STATS_JSON_FILE.is_file() else {}
    q = stats.get("quotas", {})
    cx_live = ql.fetch_codex_live()
    agy_live = ql.fetch_agy_live()
    out: dict = {"generated": int(time.time())}

    cx = {"source_of_truth": "live" if cx_live and "error" not in cx_live else "local_log"}
    if cx_live and "error" not in cx_live:
        cx.update(cx_live)
    else:
        lc = q.get("codex", {})
        cx.update({"error": (cx_live or {}).get("error"), "plan_type": lc.get("plan_type"),
                   "primary": lc.get("primary"), "secondary": lc.get("secondary")})
    cx["window_5h_local"] = q.get("codex", {}).get("window_5h")
    for k in ("primary", "secondary"):
        w = cx.get(k)
        if w:
            w["label"] = ql.codex_window_label(w.get("window_minutes"), k)
            w["forecast"] = ql.forecast_window(w.get("used_percent"), w.get("window_minutes"), w.get("resets_at"))
            sw = (q.get("codex") or {}).get(k) or {}
            if all(w.get(f) == sw.get(f) for f in ("window_minutes", "resets_at", "used_percent")):
                for f in ("cost_text", "cost_used", "cost_quota_total", "cost_remaining", "cost_projected", "cost_safe_per_day", "cost_safe_per_hour", "cost_models", "cost_observed", "cost_is_estimated"):
                    if f in sw:
                        w[f] = sw[f]
            w["forecast_text"] = ql.forecast_text(w["forecast"], w.get("resets_at"), w)
    out["codex"] = cx

    ag = {"source_of_truth": "live" if agy_live and "error" not in agy_live else "local_log"}
    if agy_live and "error" not in agy_live:
        ag.update(agy_live)
        for g in ag["groups"]:
            for b in g["buckets"]:
                wm = {"5h": 300, "weekly": 10080}.get(b.get("window"))
                b["forecast"] = ql.forecast_window(b.get("used_percent"), wm, b.get("resets_at"))
        sb = {x["bucket_id"] + g2["name"]: x for g2 in ((q.get("agy") or {}).get("live") or {}).get("groups", []) for x in g2["buckets"]}
        for g in ag["groups"]:
            for b in g["buckets"]:
                x = sb.get(b["bucket_id"] + g["name"], {})
                if any(b.get(f) != x.get(f) for f in ("window", "resets_at", "used_percent")):
                    continue
                for f in ("forecast_text", "cost_text", "cost_used", "cost_quota_total", "cost_remaining", "cost_projected", "cost_safe_per_day", "cost_safe_per_hour", "cost_models", "cost_observed", "cost_is_estimated"):
                    if f in x:
                        b[f] = x[f]
    else:
        ag.update({"error": (agy_live or {}).get("error", "token unavailable"), "local": q.get("agy")})
    out["agy"] = ag
    out["cc"] = ql.claude_info()
    return out


def scheduler_loop() -> None:
    while True:
        try:
            if PRICE_STORE.claim_due():
                try:
                    PRICE_RESEARCH.start()
                except ValueError:
                    pass
            live = build_live()
            quotas = {
                "codex": live.get("codex") or {},
                "agy": live.get("agy") or {},
                "cc": live.get("cc") or {},
            }
            conv.check_and_run_schedules(quotas)
        except Exception as exc:
            print(f"[scheduler] error: {exc}", flush=True)
        time.sleep(30)


class UsageHTTPHandler(SimpleHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_SERVE_DIR or WEB_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        # Keep logs concise
        pass

    def send_error(self, code, message=None, explain=None):
        if code != HTTPStatus.NOT_FOUND:
            return super().send_error(code, message, explain)
        path = self.path.split('?', 1)[0]
        known = {'/', '/index.html', '/live.html', '/settings.html', '/favicon.svg',
                 '/assets/index.css', '/assets/index.js', '/assets/auth.css', '/assets/auth.js',
                 '/assets/conversations.js', '/assets/remote-settings.js'}
        failure = sys.exc_info()[1]
        detail = (f' error={type(failure).__name__} errno={failure.errno}'
                  if isinstance(failure, OSError) and isinstance(failure.errno, int) else '')
        ray = self.headers.get('Cf-Ray', '')
        if re.fullmatch(r'[0-9a-fA-F]{16,32}-[A-Za-z]{3,4}', ray):
            detail += f' ray={ray}'
        print(f'[http404] path={path if path in known else "<other>"}{detail}', flush=True)
        self._not_found_response = True
        try:
            return super().send_error(code, message, explain)
        finally:
            self._not_found_response = False

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        if getattr(self, '_not_found_response', False):
            self.send_header('Cache-Control', 'no-store')
        elif not urlparse(self.path).path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-store, max-age=0')
        super().end_headers()

    def _display_json(self, payload):
        language = 'en' if self.headers.get('X-UI-Language', '').lower() == 'en' else 'zh'
        self._send_json(json.dumps(display_payload(payload, language), ensure_ascii=False).encode())

    def _send_json(self, payload: bytes, status: int = HTTPStatus.OK, *, cookie=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if n < 0 or n > 65536:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _authed(self, path: str) -> bool:
        if path not in PROTECTED:
            return True
        if self._has_token() or AUTH.authenticated(self.headers.get('Cookie')):
            return True
        if self.command == 'GET' and path in ('/api/stats.json', '/api/activity') and UI_SETTINGS.get()['public_overview']:
            return True
        self._send_json(b'{"error":"unauthorized"}', HTTPStatus.UNAUTHORIZED)
        return False

    def _has_token(self):
        return bool(API_TOKEN and hmac.compare_digest(self.headers.get('X-Token', ''), API_TOKEN))

    def _session_cookie(self, token, *, clear=False):
        secure = self.client_address[0] in ('127.0.0.1', '::1') and self.headers.get('X-Forwarded-Proto') == 'https'
        return (f'ai_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else SESSION_SECONDS}'
                + ('; Secure' if secure else ''))

    def _setup_email(self):
        return AUTH.access_email(self.headers.get('Cf-Access-Jwt-Assertion', ''), REMOTE_ACCESS.auth_context())

    def _error_message(self, error):
        message = str(error)
        if self.headers.get('X-UI-Language', '').lower() != 'en':
            return message
        if ' / ' in message:
            return message.split(' / ', 1)[0]
        return {'密码不正确': 'Incorrect password', '密码长度须为 10–256 个字符': 'Use a password of 10–256 characters',
                '已经设置过密码，请直接登录': 'A password is already configured; please sign in',
                '请求内容必须是 JSON 对象': 'The request must be a JSON object'}.get(message, message)

    def _client_ip(self):
        peer = self.client_address[0]
        try:
            loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            loopback = False
        forwarded = self.headers.get('CF-Connecting-IP')
        verified = False
        if loopback and forwarded and self.headers.get('X-Forwarded-Proto') == 'https':
            hostname = REMOTE_ACCESS.status().get('hostname')
            try:
                host = urlparse('//'+self.headers.get('Host', '')).hostname
            except ValueError:
                host = None
            if hostname and host and hostname.lower() == host.lower():
                verified = bool(self._setup_email())
        return resolve_client_ip(peer, forwarded, access_verified=verified)

    def _auth_status(self):
        configured = AUTH.configured
        email = self._setup_email() if not configured else None
        return {'configured': configured, 'authenticated': self._has_token() or AUTH.authenticated(self.headers.get('Cookie')),
                'can_setup': not configured and bool(email or self._has_token()), 'access_email': email,
                'setup_url': REMOTE_ACCESS.status().get('public_url')}

    def _auth_post(self, path, body):
        cookie = None
        try:
            if not isinstance(body, dict):
                raise ValueError('请求内容必须是 JSON 对象')
            if path == '/api/auth/logout':
                AUTH.logout(self.headers.get('Cookie'))
                cookie = self._session_cookie('', clear=True)
            elif path == '/api/auth/login':
                cookie = self._session_cookie(AUTH.login(body.get('password'), self._client_ip()))
            elif path == '/api/auth/setup':
                with AUTH._lock:
                    if AUTH.configured:
                        raise ValueError('已经设置过密码，请直接登录')
                    if not (self._has_token() or self._setup_email()):
                        self._send_json(json.dumps({'error': '请先通过公网域名的 Cloudflare 邮箱验证，或使用已有访问令牌'}, ensure_ascii=False).encode(), 403)
                        return
                    AUTH.set_password(body.get('password'))
                    cookie = self._session_cookie(AUTH.new_session())
            elif path == '/api/auth/password':
                client = self._client_ip()
                with AUTH._lock:
                    AUTH.login(body.get('current_password'), client)
                    AUTH.set_password(body.get('password'))
                    cookie = self._session_cookie(AUTH.new_session())
            else:
                self._send_json(b'{"error":"not found"}', 404)
                return
        except PermissionError as error:
            self._send_json(json.dumps({'error': self._error_message(error)}, ensure_ascii=False).encode(), 429)
            return
        except ValueError as error:
            self._send_json(json.dumps({'error': self._error_message(error)}, ensure_ascii=False).encode(), 400)
            return
        self._send_json(b'{"ok":true}', cookie=cookie)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        origin = self.headers.get('Origin')
        if (self.headers.get('Sec-Fetch-Site') == 'cross-site'
                or (origin and (urlparse(origin).scheme not in ('http', 'https') or urlparse(origin).netloc != self.headers.get('Host')))):
            self._send_json(b'{"error":"cross-origin request denied"}', 403)
            return
        if path.startswith('/api/auth/'):
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self._send_json(b'{"error":"application/json required"}', 415)
                return
            self._auth_post(path, self._read_body())
            return
        if not self._authed(path):
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self._send_json(b'{"error":"application/json required"}', 415)
            return
        body = self._read_body()
        if not isinstance(body, dict):
            self._send_json(b'{"error":"JSON object required"}', 400)
            return
        if path == '/api/conversation/questions':
            import conversation_questions
            try:
                if body.get('source') != 'codex':
                    raise ValueError('Native question controls are available for Codex only')
                result = conversation_questions.respond_to_question(body.get('conv_id'), body.get('request_id'), body.get('answers'))
                self._send_json(json.dumps(result, ensure_ascii=False).encode())
            except (ValueError, OSError) as error:
                self._send_json(json.dumps({'error': str(error)}, ensure_ascii=False).encode(), 400)
            return
        if path == '/api/settings':
            try:
                result = UI_SETTINGS.save(body)
                self._send_json(json.dumps(result).encode())
            except (ValueError, OSError) as error:
                self._send_json(json.dumps({'error': str(error)}).encode(), 400)
            return
        if path == '/api/security':
            try:
                if body.get('action') == 'configure':
                    result = AUTH.configure_security({key: value for key, value in body.items() if key != 'action'}, self._client_ip())
                elif body.get('action') == 'unblock':
                    result = AUTH.unblock_ip(body.get('ip'), self._client_ip())
                else:
                    raise ValueError('Unsupported security action')
                self._send_json(json.dumps(result, ensure_ascii=False).encode())
            except PermissionError as error:
                self._send_json(json.dumps({'error': self._error_message(error)}, ensure_ascii=False).encode(), 503)
            except (ValueError, OSError) as error:
                self._send_json(json.dumps({'error': self._error_message(error)}, ensure_ascii=False).encode(), 400)
            return
        if path == '/api/conversations':
            try:
                result = conv.create_conversation(body)
                self._send_json(json.dumps(result, ensure_ascii=False).encode(), 201)
            except (ValueError, OSError) as error:
                self._send_json(json.dumps({'error': str(error)}, ensure_ascii=False).encode(), 400)
            return
        if path == '/api/pricing':
            try:
                action = body.get('action')
                result = {'ok': True}
                if action == 'save':
                    with _collect_lock:
                        PRICE_STORE.save_override(body.get('model'), body.get('prices') or {})
                elif action == 'apply':
                    with _collect_lock:
                        PRICE_STORE.apply_proposal(body.get('model'))
                elif action == 'dismiss':
                    PRICE_STORE.dismiss_proposal(body.get('model'))
                elif action == 'import':
                    with PRICE_RESEARCH.lock:
                        if PRICE_RESEARCH.running:
                            raise ValueError('Wait until the current price research finishes')
                        PRICE_STORE.store_research(body.get('models'), merge=True)
                elif action == 'research':
                    result['research_id'] = PRICE_RESEARCH.start(body.get('agent'), body.get('research_model'))
                elif action == 'schedule':
                    PRICE_STORE.configure(body.get('enabled'), body.get('interval_hours'),
                                          body.get('agent', 'codex'), body.get('research_model', ''))
                else:
                    raise ValueError('Unsupported pricing action')
                if action in ('save', 'apply'):
                    threading.Thread(target=refresh_stats, kwargs={'force': True}, daemon=True).start()
                self._send_json(json.dumps(result, ensure_ascii=False).encode())
            except (ValueError, OSError) as error:
                self._send_json(json.dumps({'error': str(error)}, ensure_ascii=False).encode(), 400)
            return
        if path == '/api/remote-access':
            try:
                if not isinstance(body, dict):
                    raise ValueError('请求内容必须是 JSON 对象')
                action = body.get('action')
                if action == 'save':
                    result = REMOTE_ACCESS.save(body)
                elif action == 'disable':
                    result = REMOTE_ACCESS.disable()
                elif action == 'auto_start':
                    result = REMOTE_ACCESS.set_auto_start(body.get('enabled'))
                elif action in ('check', 'enable'):
                    result = REMOTE_ACCESS.begin(action)
                else:
                    raise ValueError('不支持的设置操作')
            except (ValueError, RemoteAccessError, OSError) as error:
                code = HTTPStatus.BAD_REQUEST if isinstance(error, ValueError) else HTTPStatus.CONFLICT
                if isinstance(error, OSError):
                    error = '无法保存远程访问设置'
                self._send_json(json.dumps({'error': str(error)}, ensure_ascii=False).encode(), code)
                return
            self._send_json(json.dumps(result, ensure_ascii=False).encode(),
                            HTTPStatus.ACCEPTED if action in ('check', 'enable') else HTTPStatus.OK)
            return
        if path == "/api/send":
            if not body.get("source") or not body.get("conv_id") or not body.get("prompt"):
                self._send_json(b'{"error":"source, conv_id, prompt required"}', HTTPStatus.BAD_REQUEST)
                return
            prompt = body['prompt']
            if not isinstance(prompt, str):
                self._send_json(b'{"error":"prompt must be text"}', 400)
                return
            if prompt.lstrip().startswith('/'):
                try:
                    if body.get('source') == 'codex':
                        result = codex_commands.execute_command(body['conv_id'], prompt)
                        self._send_json(json.dumps({'command': True, 'result': result}, ensure_ascii=False).encode())
                        return
                    prompt = conv.validate_native_command(body['source'], prompt)
                except ValueError as error:
                    self._send_json(json.dumps({'error': str(error)}, ensure_ascii=False).encode(), 400)
                    return
            e = conv.send_message_async(
                body["source"],
                body["conv_id"],
                prompt,
                conv_title=body.get("conv_title", ""),
                cwd=body.get("cwd"),
                model=body.get("model") or None,
                effort=body.get("effort") or None,
            )
            self._send_json(json.dumps(e, ensure_ascii=False).encode())
            return
        if path == "/api/schedules":
            if isinstance(body.get('prompt'), str) and body['prompt'].lstrip().startswith('/'):
                self._send_json(b'{"error":"Slash commands cannot be scheduled"}', 400)
                return
            if body.get("delete"):
                ok = conv.delete_schedule(body.get("id", ""))
                self._send_json(json.dumps({"deleted": ok}).encode())
                return
            quotas = None
            if STATS_JSON_FILE.is_file():
                try:
                    quotas = json.loads(STATS_JSON_FILE.read_text(encoding="utf-8")).get("quotas")
                except Exception:
                    pass
            sc = conv.upsert_schedule(body, quotas)
            self._send_json(json.dumps(sc, ensure_ascii=False).encode())
            return
        self._send_json(b'{"error":"not found"}', HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/api/auth/status':
            self._send_json(json.dumps(self._auth_status(), ensure_ascii=False).encode())
            return
        if not self._authed(path):
            return

        if path == '/api/activity':
            self._send_json(json.dumps(TASK_ACTIVITY.snapshot(), ensure_ascii=False).encode())
            return

        if path == '/api/activity/history':
            try:
                self._send_json(json.dumps({'tasks': TASK_ACTIVITY.history()}, ensure_ascii=False).encode())
            except (OSError, ValueError) as error:
                self._send_json(json.dumps({'error': self._error_message(error)}).encode(), 503)
            return

        if path == '/api/conversation/questions':
            import conversation_questions
            try:
                query = parse_qs(parsed.query)
                if (query.get('source') or ['codex'])[0] != 'codex':
                    raise ValueError('Native question controls are available for Codex only')
                result = conversation_questions.pending_questions((query.get('id') or [''])[0])
                self._send_json(json.dumps(result, ensure_ascii=False).encode())
            except (ValueError, OSError) as error:
                self._send_json(json.dumps({'error': str(error)}, ensure_ascii=False).encode(), 400)
            return

        if path == '/api/quota-windows':
            try:
                self._send_json(json.dumps({'windows': QUOTA_LOG.list()}, ensure_ascii=False).encode())
            except (OSError, ValueError) as error:
                self._send_json(json.dumps({'error': self._error_message(error)}, ensure_ascii=False).encode(), 503)
            return

        if path == '/api/security':
            try:
                self._send_json(json.dumps(AUTH.security_status(), ensure_ascii=False).encode())
            except PermissionError as error:
                self._send_json(json.dumps({'error': self._error_message(error)}, ensure_ascii=False).encode(), 503)
            return

        if path == '/api/settings':
            self._send_json(json.dumps(UI_SETTINGS.get()).encode())
            return

        if path == '/api/commands':
            try:
                source = (parse_qs(parsed.query).get('source') or ['codex'])[0]
                self._send_json(json.dumps({'source': source, 'commands': command_list(source)}, ensure_ascii=False).encode())
            except ValueError as error:
                self._send_json(json.dumps({'error': str(error)}).encode(), 400)
            return

        if path == '/api/pricing/research':
            try:
                runs = PRICE_RESEARCH.history.list()
                run_id = (parse_qs(parsed.query).get('id') or [runs[0]['id'] if runs else None])[0]
                run = PRICE_RESEARCH.history.read(run_id) if run_id else None
                self._send_json(json.dumps({'runs': runs, 'run': run}, ensure_ascii=False).encode())
            except (ValueError, OSError) as error:
                self._send_json(json.dumps({'error': str(error)}).encode(), 400)
            return

        if path == '/api/remote-access':
            self._send_json(json.dumps(REMOTE_ACCESS.status(), ensure_ascii=False).encode())
            return

        if path == "/api/stats.json":
            if STATS_JSON_FILE.is_file():
                data_bytes = STATS_JSON_FILE.read_bytes()
            else:
                data = refresh_stats(force=False)
                data_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._display_json(json.loads(data_bytes))
            return

        if path == "/api/refresh":
            data = refresh_stats(force=False)
            data_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._display_json(data)
            return

        if path == "/api/quota":
            if STATS_JSON_FILE.is_file():
                data = json.loads(STATS_JSON_FILE.read_text(encoding="utf-8"))
            else:
                data = refresh_stats(force=False)
            q_bytes = json.dumps(data.get("quotas", {}), ensure_ascii=False, indent=2).encode(
                "utf-8"
            )
            self._display_json(data.get('quotas', {}))
            return

        if path == "/api/live":
            self._display_json(build_live())
            return

        if path == "/api/pricing":
            tbl = {m: {"in": p[0], "cache_read": p[1], "cache_write": p[2], "out": p[3]} for m, p in MODEL_PRICING.items()}
            tbl.update(PRICE_STORE.overrides())
            state = PRICE_STORE.state()
            observed = sorted({row[0] for row in (_latest_stats or {}).get('summary', {}).get('models', [])
                               if row[0] != 'unknown' and ID_RE.fullmatch(row[0])})
            self._send_json(json.dumps({"unit": "USD per 1M tokens", "models": tbl, 'observed_models': observed,
                                       'research_prompt': RESEARCH_PROMPT,
                                       'overrides': list(state['overrides']), 'metadata': state['metadata'], 'proposals': state['proposals'],
                                       'schedule': state['schedule'], 'last_checked': state['last_checked'],
                                       'agents': {key: {'installed': bool(find_agent(key))} for key in AGENTS},
                                       'research_runs': PRICE_RESEARCH.history.list(),
                                       'last_error': state['last_error'], 'running': PRICE_RESEARCH.running}, ensure_ascii=False).encode())
            return

        if path == '/api/models':
            try:
                source = (parse_qs(parsed.query).get('source') or ['codex'])[0]
                result = codex_commands.rpc('model/list', {'limit': 100}) if source == 'codex' else {'data': list_agent_models(source)}
                self._send_json(json.dumps(result, ensure_ascii=False).encode())
            except ValueError as error:
                self._send_json(json.dumps({'error': str(error)}, ensure_ascii=False).encode(), 503)
            return

        if path == "/api/conversations":
            qs = parse_qs(parsed.query)
            items = conv.list_all_conversations(
                source_filter=(qs.get("source") or ["all"])[0],
                include_subthreads=(qs.get("sub") or ["0"])[0] == "1",
                limit=int((qs.get("limit") or ["100"])[0]),
            )
            self._send_json(json.dumps(items, ensure_ascii=False).encode())
            return

        if path == "/api/conversation":
            qs = parse_qs(parsed.query)
            source, conv_id = (qs.get("source") or [""])[0], (qs.get("id") or [""])[0]
            try:
                if (qs.get("page") or ["0"])[0] == "1":
                    before = int(qs["before"][0]) if "before" in qs else None
                    result = conv.get_conversation_page(
                        source, conv_id, limit=int((qs.get("limit") or ["50"])[0]), before=before,
                    )
                else:
                    result = conv.get_conversation_messages(source, conv_id)
            except ValueError as exc:
                self._send_json(json.dumps({"error": str(exc)}).encode(), HTTPStatus.BAD_REQUEST)
                return
            self._send_json(json.dumps(result, ensure_ascii=False).encode())
            return

        if path == "/api/schedules":
            self._send_json(json.dumps({"schedules": conv.get_schedules(), "history": conv.get_send_history()}, ensure_ascii=False).encode())
            return

        if path == "/healthz":
            self._send_json(b'{"ok":true}')
            return

        # Serve static files from WEB_DIR
        super().do_GET()


def serve_dashboard(host: str, port: int, manager: RemoteAccessManager, *, lan_host=None) -> None:
    """Rebind to loopback before starting a public connector, without killing AI jobs."""
    lan_server = None
    if lan_host:
        address = ipaddress.ip_address(lan_host)
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified or address.is_link_local:
            raise ValueError('--lan-host 必须为明确的内网 IPv4 地址')
        lan_server = ThreadingHTTPServer((lan_host, port), UsageHTTPHandler)
        threading.Thread(target=lan_server.serve_forever, daemon=True).start()
        host = '127.0.0.1'
        manager.lan_host = lan_host
        print(f'[server] LAN dashboard listening on http://{lan_host}:{port}', flush=True)
    requested, bound = threading.Event(), threading.Event()
    current_server = None

    def rebind():
        requested.set()
        bound.clear()
        if current_server is not None:
            threading.Thread(target=current_server.shutdown, daemon=True).start()
        if not bound.wait(15):
            raise RemoteAccessError('本机监听切换超时，已停止启动远程连接')

    manager.on_bind_change = rebind
    manager.origin_port = port
    started = False
    try:
        while True:
            bind_host = '127.0.0.1' if manager.local_only else host
            current_server = ThreadingHTTPServer((bind_host, port), UsageHTTPHandler)
            bound.set()
            if not started:
                manager.start()
                started = True
            print(f'[server] Dashboard listening on http://{bind_host}:{port}', flush=True)
            try:
                current_server.serve_forever()
            except KeyboardInterrupt:
                break
            finally:
                current_server.server_close()
            if not requested.is_set():
                break
            requested.clear()
    finally:
        manager.close()
        if lan_server:
            lan_server.shutdown()
            lan_server.server_close()


def main() -> None:
    global WEB_SERVE_DIR
    parser = argparse.ArgumentParser(
        description="Codex & AGY Usage + Quota Web Dashboard & 1-Minute Auto-Updater"
    )
    parser.add_argument(
        "--host", default=os.environ.get("HOST", "127.0.0.1"), help="Bind host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8088")),
        help="Bind port (default: 8088)",
    )
    parser.add_argument('--lan-host', default=os.environ.get('LAN_HOST'), help='Keep this explicit private IPv4 address available alongside the loopback Tunnel origin')
    parser.add_argument('--web-cache', default=os.environ.get('WEB_CACHE_DIR'), help='Serve complete static-page snapshots from this local directory')
    parser.add_argument('--set-password', action='store_true', help='Set or reset the dashboard password interactively, then exit')
    parser.add_argument('--disable-remote', action='store_true', help='Disable saved remote access and exit; stop the running dashboard first')
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("REFRESH_INTERVAL", "60")),
        help="Auto-refresh interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run collection once, print CLI summary, and exit without starting web server",
    )
    args = parser.parse_args()
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'posix':
        os.chmod(DATA_DIR, 0o700)
        if DATA_DIR.stat().st_mode & 0o077:
            parser.error('Use a private local data directory with QUOTACANVAS_DATA_DIR. / 请将数据目录设为支持权限保护的本机目录。')

    if args.disable_remote:
        REMOTE_ACCESS.disable(reset_binding=True)
        print('Remote access disabled; Access protection retained. / 远程访问已停用，已有 Access 保护规则保留。', flush=True)
        return

    if args.set_password or not args.once:
        try:
            configure_password(AUTH, reset=args.set_password)
        except ValueError as error:
            parser.error(str(error))
        if args.set_password:
            print('Restart any running dashboard service to load this password. / 请重启正在运行的面板服务以加载新密码。', flush=True)
            return

    stats = refresh_stats(force=False)
    print_cli_report(stats)

    if args.once:
        return

    web_cache = None
    if args.web_cache:
        web_cache = StaticWebCache(WEB_DIR, Path(args.web_cache))
        WEB_SERVE_DIR = web_cache.start()
        print(f'[server] 页面使用本地快照：{WEB_SERVE_DIR}', flush=True)

    t = threading.Thread(target=background_updater, args=(args.interval,), daemon=True)
    t.start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=activity_updater, daemon=True).start()

    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")

    try:
        serve_dashboard(args.host, args.port, REMOTE_ACCESS, lan_host=args.lan_host)
    finally:
        if web_cache:
            web_cache.close()


if __name__ == "__main__":
    main()
