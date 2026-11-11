"""Local price overrides and reviewable, opt-in agent research."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlparse

from research_history import ResearchHistory
from runtime_paths import get_data_dir
from research_process import run_research_process

BASE_DIR = Path(__file__).resolve().parent
FIELDS = ('in', 'cache_read', 'cache_write', 'out')
ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,119}$')


def validate_prices(values):
    if not isinstance(values, dict):
        raise ValueError('Prices must be a JSON object')
    result = {}
    for key in FIELDS:
        raw = values.get(key)
        if isinstance(raw, bool):
            raise ValueError('Prices must be finite, non-negative numbers')
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError('Prices must be finite, non-negative numbers') from None
        if not math.isfinite(number) or number < 0 or number > 1_000_000:
            raise ValueError('Prices must be finite, non-negative numbers')
        result[key] = number
    return result


def validate_model(model):
    if not isinstance(model, str) or not ID_RE.fullmatch(model):
        raise ValueError('Invalid model ID')
    return model


AGENTS = {'codex': 'codex', 'agy': 'agy', 'cc': 'claude'}


def research_options(agent='codex', model=''):
    if not isinstance(agent, str) or agent not in AGENTS:
        raise ValueError('Unsupported research agent')
    if not isinstance(model, str) or (model and not ID_RE.fullmatch(model)):
        raise ValueError('Invalid research model ID')
    return agent, model


def find_agent(agent):
    executable = shutil.which(AGENTS[agent])
    fallback = Path.home() / '.local' / 'bin' / AGENTS[agent]
    if executable:
        return executable
    return str(fallback) if fallback.is_file() and os.access(fallback, os.X_OK) else None


def find_codex():
    return find_agent('codex')


_model_cache = {}
_model_lock = threading.Lock()


def list_agent_models(agent):
    if agent == 'cc':
        return [{'id': name, 'model': name} for name in ('opus', 'sonnet', 'haiku')]
    if agent != 'agy' or not find_agent(agent):
        raise ValueError('Agent CLI not installed')
    with _model_lock:
        cached = _model_cache.get(agent)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        try:
            result = subprocess.run([find_agent(agent), 'models'], capture_output=True, text=True, encoding='utf-8', timeout=15, check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError):
            raise ValueError('Could not read AGY models; check CLI login and network') from None
        models = []
        for line in result.stdout.splitlines():
            parts = line.strip().split('\t', 1)
            if len(parts) == 2 and ID_RE.fullmatch(parts[0]):
                models.append({'id': parts[0], 'model': parts[0], 'description': parts[1]})
        if not models:
            raise ValueError('AGY returned no readable model catalog; enter a custom model ID or use the agent default')
        _model_cache[agent] = (time.monotonic(), models)
        return models


class PriceStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self._overrides_cache = {}
        self._signature = None
        self._last_stat = 0.0

    def state(self):
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data, dict):
                    raise ValueError('invalid data')
            except FileNotFoundError:
                data = {}
            return {'overrides': data.get('overrides', {}), 'metadata': data.get('metadata', {}), 'proposals': data.get('proposals', []),
                    'schedule': data.get('schedule', {'enabled': False, 'interval_hours': 168}),
                    'last_checked': data.get('last_checked'), 'last_error': data.get('last_error', '')}

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.prices-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                if hasattr(os, 'fchmod'):
                    os.fchmod(f.fileno(), 0o600)
                else:
                    os.chmod(name, 0o600)
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(name, self.path)
            self._signature = None
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def overrides(self):
        with self.lock:
            now = time.monotonic()
            if self._signature is not None and now - self._last_stat < 1:
                return self._overrides_cache
            self._last_stat = now
            try:
                stat = self.path.stat()
                signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            except FileNotFoundError:
                signature = ()
            if signature != self._signature:
                self._overrides_cache = self.state()['overrides']
                self._signature = signature
            return self._overrides_cache

    def revision(self):
        return hashlib.sha256(json.dumps(self.overrides(), sort_keys=True).encode()).hexdigest()

    def save_override(self, model, values):
        model = validate_model(model)
        prices = validate_prices(values)
        with self.lock:
            state = self.state()
            state['overrides'][model] = prices
            state['metadata'][model] = {'source': 'manual', 'updated_at': int(time.time())}
            self._save(state)
        return prices

    def store_research(self, entries, *, merge=False):
        if not isinstance(entries, list) or len(entries) > 100 or (merge and not entries):
            raise ValueError('Invalid research results')
        proposals = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Invalid research result')
            model = validate_model(entry.get('model'))
            url = str(entry.get('source') or '')
            parsed = urlparse(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or len(url) > 2048:
                raise ValueError('A valid HTTPS source is required')
            description = str(entry.get('description') or '')[:500]
            if model in proposals:
                raise ValueError('Duplicate model ID: ' + model)
            proposals[model] = {'model': model, **validate_prices(entry), 'source': url, 'description': description}
        with self.lock:
            state = self.state()
            if merge:
                existing = {p['model']: p for p in state['proposals']}
                existing.update(proposals)
                proposals = existing
            entries = list(proposals.values())
            state.update(proposals=entries, last_checked=int(time.time()), last_error='')
            self._save(state)
        return entries

    def apply_proposal(self, model):
        validate_model(model)
        with self.lock:
            state = self.state()
            proposal = next((p for p in state['proposals'] if p['model'] == model), None)
            if proposal is None:
                raise ValueError('Proposal not found')
            state['overrides'][model] = validate_prices(proposal)
            state['metadata'][model] = {'source': proposal['source'], 'updated_at': int(time.time()),
                                        'researched_at': state['last_checked'], 'description': proposal['description']}
            state['proposals'] = [p for p in state['proposals'] if p['model'] != model]
            self._save(state)
            return state['overrides'][model]

    def dismiss_proposal(self, model):
        validate_model(model)
        with self.lock:
            state = self.state()
            state['proposals'] = [proposal for proposal in state['proposals'] if proposal['model'] != model]
            self._save(state)

    def configure(self, enabled, interval_hours, agent='codex', model=''):
        agent, model = research_options(agent, model)
        if not isinstance(enabled, bool) or isinstance(interval_hours, bool):
            raise ValueError('Invalid schedule')
        try:
            interval = int(interval_hours)
        except (ValueError, TypeError):
            raise ValueError('Invalid schedule') from None
        if interval < 24 or interval > 720:
            raise ValueError('Update interval must be between 24 and 720 hours')
        with self.lock:
            state = self.state()
            state['schedule'] = {'enabled': enabled, 'interval_hours': interval, 'agent': agent, 'model': model,
                                 'next_at': int(time.time()) + interval * 3600}
            self._save(state)
            return state['schedule']

    def error(self, message):
        with self.lock:
            state = self.state()
            state['last_checked'] = int(time.time())
            state['last_error'] = str(message)[:300]
            self._save(state)

    def claim_due(self):
        with self.lock:
            state = self.state()
            schedule = state['schedule']
            now = int(time.time())
            if not schedule.get('enabled') or now < schedule.get('next_at', 0):
                return False
            schedule['next_at'] = now + max(24, int(schedule.get('interval_hours', 168))) * 3600
            self._save(state)
            return True


RESEARCH_PROMPT = (
    'Research current API list prices for OpenAI, Anthropic, Google, DeepSeek and any requested model IDs. '
    'For a gateway model use the exact logged ID and that gateway’s published rate. Use live web search '
    'and first-party provider pricing pages only. Return only a JSON object with a models array. '
    'Each entry has model, in, cache_read, cache_write, out, source and description. Prices are numbers '
    'in USD per million tokens. Use 0 for an unsupported cache operation only when confirmed. '
    'Omit entries if a required price cannot be verified. Provide a direct HTTPS price source and '
    'brief capability/reasoning details. Do not edit project files or run commands. '
    'QuotaCanvas imports this JSON as suggestions and recalculates after a user applies a suggestion.'
)


class PriceResearch:
    def __init__(self, store):
        self.store, self.lock, self.running = store, threading.Lock(), False
        self.history = ResearchHistory(store.path.with_name('price_research.json'))
        self.history.recover()
        self._claude_messages = {}

    def start(self, agent=None, model=None):
        schedule = self.store.state()['schedule']
        agent, model = research_options(agent or schedule.get('agent', 'codex'), model if model is not None else schedule.get('model', ''))
        if not find_agent(agent):
            raise ValueError(f'{AGENTS[agent]} CLI not found; install and sign in first')
        with self.lock:
            if self.running:
                raise ValueError('Price research is already running')
            run = self.history.create(agent, model, RESEARCH_PROMPT)
            self.running = True
            threading.Thread(target=self._run, args=(agent, model, run['id']), daemon=True).start()
        return run['id']

    def record_event(self, run_id, event):
        session = event.get('thread_id') or event.get('session_id') or event.get('conversation_id')
        if session:
            self.history.session(run_id, session)
        item = event.get('item') if isinstance(event.get('item'), dict) else {}
        if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
            self.history.message(run_id, 'assistant', item.get('text'), key=item.get('id'))
        step = event.get('step_update') if isinstance(event.get('step_update'), dict) else {}
        if event.get('event') == 'step_update' and step.get('step_type') == 'agent_response':
            text = step.get('text') or step.get('text_delta')
            self.history.message(run_id, 'assistant', text, key='agy:' + str(step.get('step_index')), append='text' not in step)
        if event.get('type') == 'assistant' and not event.get('parent_tool_use_id'):
            message = event.get('message') if isinstance(event.get('message'), dict) else {}
            text = '\n'.join(part.get('text', '') for part in message.get('content', []) if isinstance(part, dict) and part.get('type') == 'text')
            self.history.message(run_id, 'assistant', text, key=message.get('id'))
        if event.get('type') == 'stream_event' and not event.get('parent_tool_use_id'):
            stream = event.get('event') if isinstance(event.get('event'), dict) else {}
            if stream.get('type') == 'message_start':
                message = stream.get('message') or {}
                if isinstance(message.get('id'), str):
                    self._claude_messages[run_id] = message['id']
            delta = stream.get('delta') or {}
            if stream.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta':
                self.history.message(run_id, 'assistant', delta.get('text'), key=self._claude_messages.get(run_id, 'claude:partial'), append=True)

    @staticmethod
    def _result(event):
        data = event.get('result') if isinstance(event.get('result'), dict) else event
        if data.get('is_error') or data.get('status') == 'ERROR':
            raise ValueError('Agent research failed')
        data = data.get('structured_output') or data.get('result') or data.get('response') or data
        if isinstance(data, str):
            data = json.loads(data.removeprefix('```json').removeprefix('```').removesuffix('```').strip())
        if not isinstance(data, dict) or not isinstance(data.get('models'), list):
            raise ValueError('Agent did not return a valid model-price result')
        return data

    def _run(self, agent='codex', model='', run_id=None):
        try:
            agent, model = research_options(agent, model)
            if run_id is None:
                run_id = self.history.create(agent, model, RESEARCH_PROMPT)['id']
            executable = find_agent(agent)
            if not executable:
                raise ValueError('Agent CLI not found; install and sign in first')
            schema = {'type': 'object', 'properties': {'models': {'type': 'array', 'items': {
                'type': 'object', 'properties': {key: {'type': 'number'} for key in FIELDS} | {
                    'model': {'type': 'string'}, 'source': {'type': 'string'}, 'description': {'type': 'string'}},
                'required': ['model', *FIELDS, 'source', 'description'], 'additionalProperties': False}}},
                'required': ['models'], 'additionalProperties': False}
            with tempfile.TemporaryDirectory(prefix='quotacanvas-research-') as tmp:
                root = Path(tmp)
                (root / 'schema.json').write_text(json.dumps(schema))
                if agent == 'codex':
                    cmd = [executable, '--search', '-a', 'never', 'exec', '--sandbox', 'read-only', '--skip-git-repo-check',
                           '--ephemeral', '--json', '--output-schema', str(root / 'schema.json'), '-o', str(root / 'result.json')]
                elif agent == 'agy':
                    cmd = [executable, '--mode', 'plan', '--sandbox', '--output-format', 'stream-json',
                           '--json-schema', str(root / 'schema.json')]
                else:
                    cmd = [executable, '--permission-mode', 'plan', '--tools', 'WebSearch,WebFetch',
                           '--allowedTools', 'WebSearch,WebFetch', '--output-format', 'stream-json', '--verbose', '--include-partial-messages', '--json-schema', json.dumps(schema)]
                if model:
                    cmd.extend(['--model', model])
                cmd.extend([RESEARCH_PROMPT] if agent == 'codex' else ['-p', RESEARCH_PROMPT])
                output = run_research_process(cmd, root, lambda event: self.record_event(run_id, event))
                if agent == 'codex':
                    path = root / 'result.json'
                    if path.stat().st_size > 1_000_000:
                        raise ValueError('Agent result is too large')
                    data = self._result(json.loads(path.read_text(encoding='utf-8')))
                else:
                    data = self._result(output)
                self.store.store_research(data['models'])
                self.history.message(run_id, 'assistant', json.dumps(data, ensure_ascii=False, indent=2), key='result')
                self.history.finish(run_id, 'completed')
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            message = 'Research failed: ' + type(error).__name__ + '. Check agent login, model availability and network.'
            self.store.error(message)
            if run_id:
                self.history.finish(run_id, 'failed', message)
        finally:
            self._claude_messages.pop(run_id, None)
            with self.lock:
                self.running = False


PRICE_STORE = PriceStore(get_data_dir(BASE_DIR) / 'prices.json')
PRICE_RESEARCH = PriceResearch(PRICE_STORE)
