"""Local price overrides and reviewable, opt-in agent research."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
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


def openrouter_native_id(model):
    """Map standard OpenRouter IDs for GPT, Claude and Gemini to local IDs."""
    provider, _, slug = model.partition('/')
    if ':' in slug or '/' in slug:
        return model
    if provider == 'openai' and slug.startswith('gpt-'):
        return slug
    if provider == 'google' and slug.startswith('gemini-'):
        return slug
    if provider == 'anthropic' and slug.startswith('claude-'):
        return re.sub(r'(?<=\d)\.(?=\d)', '-', slug)
    return model


@lru_cache(maxsize=2048)
def model_price_candidates(model):
    candidates = [model, openrouter_native_id(model)]
    native = candidates[-1]
    if native.startswith(('claude-', 'gemini-')) and not any(c in native for c in '/:'):
        base = re.sub(r'-(?:low|medium|high|xhigh|max)$', '', native)
        for candidate in dict.fromkeys((native, base)):
            candidates.append(candidate)
            if native.startswith('claude-'):
                candidates.extend((
                    re.sub(r'(?<=\d)\.(?=\d)', '-', candidate),
                    re.sub(r'^(claude-[a-z]+-\d+)-(\d+)(?=-|$)', r'\1.\2', candidate),
                ))
    return tuple(dict.fromkeys(candidates))


def validate_model(model):
    if not isinstance(model, str) or not ID_RE.fullmatch(model):
        raise ValueError('Invalid model ID')
    return model


def validate_https_url(url):
    text = str(url or '')
    parsed = urlparse(text)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or len(text) > 2048 or re.search(r'\s', text)):
        raise ValueError('A valid HTTPS source is required')
    return text


AGENTS = {'codex': 'codex', 'agy': 'agy', 'cc': 'claude'}
RESEARCH_SOURCES = {
    'openai': ('OpenAI', 'https://openai.com/api/pricing/'),
    'anthropic': ('Anthropic', 'https://platform.claude.com/docs/en/about-claude/pricing'),
    'google': ('Google Gemini', 'https://aistudio.google.com/docs/pricing'),
    'deepseek': ('DeepSeek', 'https://api-docs.deepseek.com/quick_start/pricing'),
}


def validate_scope(scope):
    if not isinstance(scope, str) or (scope != 'all' and scope not in RESEARCH_SOURCES):
        raise ValueError('Invalid pricing research scope')
    return scope


_catalog = (BASE_DIR / 'model_prices.json').read_bytes()
DEFAULT_PRICES = json.loads(_catalog)['models']
DEFAULT_REVISION = hashlib.sha256(_catalog).digest()
_RATE_CHANGES = {}
for _model, _entry in DEFAULT_PRICES.items():
    if 'alias' in _entry:
        continue
    validate_model(_model)
    validate_prices(_entry)
    if _change := _entry.get('next_rate'):
        _RATE_CHANGES[_model] = (
            datetime.fromisoformat(_change['effective_from']).replace(tzinfo=timezone.utc).timestamp(),
            tuple(validate_prices(_change).values()),
        )


def upcoming_default_rate(model, stamp):
    entry = DEFAULT_PRICES[model]
    model = entry.get('alias', model)
    change = _RATE_CHANGES.get(model)
    if change and stamp < change[0]:
        return DEFAULT_PRICES[model]['next_rate']


def default_rates(model, stamp=None):
    entry = DEFAULT_PRICES.get(model)
    if entry is None:
        return (0, 0, 0, 0)
    model = entry.get('alias', model)
    change = _RATE_CHANGES.get(model)
    if change and (time.time() if stamp is None else stamp) >= change[0]:
        return change[1]
    return tuple(DEFAULT_PRICES[model][key] for key in FIELDS)


def resolve_price_model(model, overrides, defaults=DEFAULT_PRICES):
    candidates = model_price_candidates(model)
    for candidate in candidates:
        canonical = defaults.get(candidate, {}).get('alias', candidate)
        if candidate in overrides or canonical in overrides:
            return candidate
    return next((candidate for candidate in candidates if candidate in defaults), model)


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
            overrides = data.get('overrides', {})
            metadata = data.get('metadata', {})
            for model in list(overrides):
                native = openrouter_native_id(model)
                details = metadata.get(model, {})
                if (native == model or details.get('channel') != 'openrouter'
                        or details.get('source') == 'manual' or details.get('channel_model') != model):
                    continue
                target = resolve_price_model(native, overrides)
                target = DEFAULT_PRICES.get(target, {}).get('alias', target)
                if target not in overrides:
                    overrides[target] = overrides[model]
                    metadata[target] = details
                del overrides[model]
                metadata.pop(model, None)
            return {'overrides': overrides, 'metadata': metadata, 'proposals': data.get('proposals', []),
                    'schedule': data.get('schedule', {'enabled': False, 'interval_hours': 168}),
                    'last_checked': data.get('last_checked'), 'last_error': data.get('last_error', ''),
                    'last_rejected': data.get('last_rejected', 0)}

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
        return hashlib.sha256(DEFAULT_REVISION + json.dumps(self.overrides(), sort_keys=True).encode()).hexdigest()

    def save_override(self, model, values):
        model = validate_model(model)
        prices = validate_prices(values)
        with self.lock:
            state = self.state()
            state['overrides'][model] = prices
            state['metadata'][model] = {'source': 'manual', 'updated_at': int(time.time())}
            self._save(state)
        return prices

    def save_channel_price(self, model, values, *, source, description='', channel='openrouter', channel_model='', overwrite_manual=False):
        """Save a synced channel price override while guarding manual entries unless confirmed."""
        model = validate_model(model)
        prices = validate_prices(values)
        url = validate_https_url(source)
        now = int(time.time())
        with self.lock:
            state = self.state()
            if state['metadata'].get(model, {}).get('source') == 'manual' and not overwrite_manual:
                raise ValueError('Manual price is protected; confirm overwrite')
            state['overrides'][model] = prices
            state['metadata'][model] = {
                'source': url, 'channel': str(channel or 'openrouter')[:40],
                'channel_model': str(channel_model or model)[:120],
                'updated_at': now, 'description': str(description or '')[:500],
            }
            self._save(state)
        return prices

    def sync_channel_prices(self, entries, *, channel='openrouter'):
        """Atomically sync multiple channel quotes without overwriting manual prices."""
        validated = []
        for entry in entries:
            model = validate_model(entry.get('model'))
            prices = validate_prices(entry)
            url = validate_https_url(entry.get('source'))
            validated.append((model, prices, url, str(entry.get('description') or '')[:500], str(entry.get('channel_model') or model)[:120]))
        now = int(time.time())
        synced, skipped_manual, unchanged = [], [], []
        with self.lock:
            state = self.state()
            changed = False
            for model, prices, url, description, channel_model in validated:
                meta = state['metadata'].get(model, {})
                if meta.get('source') == 'manual':
                    skipped_manual.append(model)
                    continue
                current = state['overrides'].get(model)
                effective = current if current is not None else dict(zip(FIELDS, default_rates(model, now)))
                has_entry = current is not None or model in DEFAULT_PRICES
                if has_entry and all(math.isclose(effective.get(k, 0.0), prices[k], rel_tol=0.0, abs_tol=1e-9) for k in FIELDS):
                    unchanged.append(model)
                    continue
                state['overrides'][model] = prices
                state['metadata'][model] = {
                    'source': url, 'channel': str(channel or 'openrouter')[:40],
                    'channel_model': channel_model, 'updated_at': now, 'description': description,
                }
                synced.append(model)
                changed = True
            if changed:
                self._save(state)
        return {'synced': synced, 'skipped_manual': skipped_manual, 'unchanged': unchanged}

    def store_research(self, entries, *, merge=False, allow_partial=False):
        if not isinstance(entries, list) or len(entries) > 100 or (merge and not entries):
            raise ValueError('Invalid research results')
        proposals = {}
        rejected = 0
        for entry in entries:
            try:
                if not isinstance(entry, dict):
                    raise ValueError('Invalid research result')
                model = validate_model(entry.get('model'))
                url = validate_https_url(entry.get('source'))
                if model in proposals:
                    raise ValueError('Duplicate model ID: ' + model)
                description = str(entry.get('description') or '')[:500]
                proposals[model] = {'model': model, **validate_prices(entry), 'source': url, 'description': description}
            except ValueError:
                if not allow_partial:
                    raise
                rejected += 1
        if allow_partial and not proposals:
            raise ValueError('No usable model prices')
        with self.lock:
            state = self.state()
            if merge:
                existing = {p['model']: p for p in state['proposals']}
                existing.update(proposals)
                proposals = existing
            entries = list(proposals.values())
            state.update(proposals=entries, last_checked=int(time.time()), last_error='', last_rejected=rejected)
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

    def configure(self, enabled, interval_hours, agent='codex', model='', *, scope='all'):
        agent, model = research_options(agent, model)
        scope = validate_scope(scope)
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
            previous = state['schedule']
            next_at = int(time.time()) + interval * 3600
            if enabled and previous.get('enabled') and previous.get('interval_hours') == interval:
                next_at = previous.get('next_at') or next_at
            state['schedule'] = {'enabled': enabled, 'interval_hours': interval, 'agent': agent, 'model': model,
                                 'next_at': next_at, 'scope': scope}
            self._save(state)
            return state['schedule']

    def error(self, message):
        with self.lock:
            state = self.state()
            state['last_checked'] = int(time.time())
            state['last_error'] = str(message)[:300]
            state['last_rejected'] = 0
            self._save(state)

    def claim_due(self):
        with self.lock:
            state = self.state()
            schedule = state['schedule']
            now = int(time.time())
            if not schedule.get('enabled') or now < schedule.get('next_at', 0):
                return None
            schedule['next_at'] = now + max(24, int(schedule.get('interval_hours', 168))) * 3600
            self._save(state)
            return schedule


RESEARCH_PROMPT = (
    'Research current API list prices for the scope below. '
    'For a gateway model use the exact logged ID and that gateway’s published rate. Use live web search '
    'and first-party provider pricing pages only. Return only a JSON object with a models array. '
    'Each entry has model, in, cache_read, cache_write, out, source and description. Prices are numbers '
    'in USD per million tokens. Use 0 for an unsupported cache operation only when confirmed. '
    'Use the current standard paid text-token rate. Exclude hourly cache storage, per-item fees, '
    'batch and priority rates. Do not submit future rates as current. Note any published expiration '
    'or effective date and tier limits in the description. Omit entries if a required price cannot be verified. '
    'For source, use a single direct HTTPS URL from the official provider, without Markdown, citation markers, or text around it. '
    'Keep each description brief. Do not edit project files or run commands. '
    'QuotaCanvas imports this JSON as suggestions and recalculates after a user applies a suggestion.'
)


def research_prompt(scope='all'):
    providers = RESEARCH_SOURCES.values() if validate_scope(scope) == 'all' else (RESEARCH_SOURCES[scope],)
    limit = 8 if scope == 'all' else 5
    sources = '\n'.join(f'- {name}: {url}' for name, url in providers)
    return (f'{RESEARCH_PROMPT}\n\nPrioritize newly released or recently repriced text models. '
            f'Return at most {limit} models. Check these official pricing pages first:\n{sources}')


class PriceResearch:
    def __init__(self, store):
        self.store, self.lock, self.running = store, threading.Lock(), False
        self.history = ResearchHistory(store.path.with_name('price_research.json'))
        self.history.recover()
        self._claude_messages = {}

    def start(self, agent=None, model=None, *, scheduled=False, scope=None):
        with self.lock:
            if self.running:
                if scheduled:
                    return None
                raise ValueError('Price research is already running')
            schedule = self.store.claim_due() if scheduled else self.store.state()['schedule']
            if schedule is None:
                return None
            agent, model = research_options(agent or schedule.get('agent', 'codex'), model if model is not None else schedule.get('model', ''))
            scope = validate_scope(schedule.get('scope', 'all') if scope is None else scope)
            if not find_agent(agent):
                message = f'{AGENTS[agent]} CLI not found; install and sign in first'
                if scheduled:
                    self.store.error(message)
                    return None
                raise ValueError(message)
            run = self.history.create(agent, model, research_prompt(scope))
            self.running = True
            try:
                threading.Thread(target=self._run, args=(agent, model, run['id'], scope), daemon=True).start()
            except RuntimeError:
                self.running = False
                self.history.finish(run['id'], 'failed', 'Could not start price research')
                raise
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
        if not isinstance(event, dict):
            raise ValueError('Agent did not return a JSON object')
        data = event.get('result') if isinstance(event.get('result'), dict) else event
        if data.get('is_error') or data.get('status') == 'ERROR':
            raise ValueError('Agent research failed')
        data = data.get('structured_output') or data.get('result') or data.get('response') or data
        if isinstance(data, str):
            data = json.loads(data.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
        if not isinstance(data, dict) or not isinstance(data.get('models'), list):
            raise ValueError('Agent did not return a valid model-price result')
        return data

    def _run(self, agent='codex', model='', run_id=None, scope='all'):
        try:
            agent, model = research_options(agent, model)
            prompt = research_prompt(scope)
            if run_id is None:
                run_id = self.history.create(agent, model, prompt)['id']
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
                           '--json-schema', str(root / 'schema.json'), '--print-timeout', '210s', '--disable-slash-commands']
                else:
                    cmd = [executable, '--permission-mode', 'plan', '--tools', 'WebSearch,WebFetch',
                           '--allowedTools', 'WebSearch,WebFetch', '--output-format', 'stream-json', '--verbose', '--include-partial-messages', '--json-schema', json.dumps(schema)]
                if model:
                    cmd.extend(['--model', model])
                cmd.extend([prompt] if agent == 'codex' else ['-p', prompt])
                output = run_research_process(cmd, root, lambda event: self.record_event(run_id, event))
                if agent == 'codex':
                    path = root / 'result.json'
                    if path.stat().st_size > 1_000_000:
                        raise ValueError('Agent result is too large')
                    data = self._result(json.loads(path.read_text(encoding='utf-8')))
                else:
                    data = self._result(output)
                self.store.store_research(data['models'], merge=True, allow_partial=True)
                self.history.message(run_id, 'assistant', json.dumps(data, ensure_ascii=False, indent=2), key='result')
                self.history.finish(run_id, 'completed')
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            if isinstance(error, subprocess.TimeoutExpired):
                message = 'Price research timed out after 4 minutes.'
            elif isinstance(error, (json.JSONDecodeError, ValueError)):
                message = 'Price research returned no usable model prices. Check the research conversation.'
            else:
                message = 'Price research failed. Check agent login, model availability and network.'
            self.store.error(message)
            if run_id:
                self.history.finish(run_id, 'failed', message)
        finally:
            self._claude_messages.pop(run_id, None)
            with self.lock:
                self.running = False


PRICE_STORE = PriceStore(get_data_dir(BASE_DIR) / 'prices.json')
PRICE_RESEARCH = PriceResearch(PRICE_STORE)
