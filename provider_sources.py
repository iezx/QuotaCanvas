"""Direct integrations for OpenRouter quotes and first-party model discovery."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import json
import math
import re
import threading
import time
import urllib.error
from urllib.parse import urlencode, urlparse
import urllib.request
from pathlib import Path

from pricing import FIELDS, ID_RE, default_rates, model_price_candidates, openrouter_native_id, resolve_price_model, validate_prices
from remote_access import secure_write

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_MODELS_PER_SOURCE = 5000
MAX_PAGES = 20
ANTHROPIC_VERSION = '2023-06-01'

PROVIDERS = {
    'openrouter': {
        'id': 'openrouter',
        'name': 'OpenRouter',
        'kind': 'quotes',
        'requires_key': False,
        'default_enabled': True,
        'docs_url': 'https://openrouter.ai/models',
    },
    'google': {
        'id': 'google',
        'name': 'Google Gemini',
        'kind': 'discovery',
        'requires_key': True,
        'default_enabled': False,
        'docs_url': 'https://aistudio.google.com/docs/pricing',
    },
    'openai': {
        'id': 'openai',
        'name': 'OpenAI',
        'kind': 'discovery',
        'requires_key': True,
        'default_enabled': False,
        'docs_url': 'https://openai.com/api/pricing/',
    },
    'anthropic': {
        'id': 'anthropic',
        'name': 'Anthropic',
        'kind': 'discovery',
        'requires_key': True,
        'default_enabled': False,
        'docs_url': 'https://platform.claude.com/docs/en/about-claude/pricing',
    },
    'deepseek': {
        'id': 'deepseek',
        'name': 'DeepSeek',
        'kind': 'discovery',
        'requires_key': True,
        'default_enabled': False,
        'docs_url': 'https://api-docs.deepseek.com/quick_start/pricing',
    },
}
PROVIDER_IDS = tuple(PROVIDERS)
DISCOVERY_IDS = tuple(pid for pid, meta in PROVIDERS.items() if meta['kind'] == 'discovery')


class ProviderFetchError(RuntimeError):
    """Raised when an upstream provider request fails safely."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderFetchError(f'Unexpected redirect (HTTP {code})')


@lru_cache(maxsize=1)
def _https_opener():
    return urllib.request.build_opener(_NoRedirectHandler())


def _redact(text, secret=''):
    value = str(text or '')
    if secret:
        value = value.replace(secret, '[redacted]')
    return value


def _validate_api_key(value):
    if not isinstance(value, str):
        raise ValueError('API key must be text')
    cleaned = value.strip()
    if len(cleaned) > 512 or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError('Invalid API key format')
    return cleaned


def _fetch_json(url, *, headers=None, timeout=12, secret=''):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ProviderFetchError('HTTPS endpoint required')
    request = urllib.request.Request(
        url,
        headers={'Accept': 'application/json', 'User-Agent': 'QuotaCanvas/0.0.2', **(headers or {})},
        method='GET',
    )
    try:
        with _https_opener().open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        detail = ''
        try:
            body = error.read(4096).decode('utf-8', errors='replace')
            err_json = json.loads(body)
            if isinstance(err_json, dict):
                nested = err_json.get('error')
                if isinstance(nested, dict):
                    detail = str(nested.get('message') or '')
                elif nested:
                    detail = str(nested)
                else:
                    detail = str(err_json.get('message') or err_json.get('detail') or '')
        except (OSError, ValueError):
            detail = ''
        suffix = f': {_redact(detail[:160], secret)}' if detail else ''
        raise ProviderFetchError(f'HTTP {error.code}{suffix}') from None
    except ProviderFetchError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ProviderFetchError(_redact(f'Request failed: {error}', secret)[:180]) from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProviderFetchError('Provider response exceeded size limit')
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ProviderFetchError('Provider returned invalid JSON') from None
    if not isinstance(payload, dict):
        raise ProviderFetchError('Provider JSON root must be an object')
    return payload


def _per_million(raw, *, default=None):
    if raw is None or raw == '':
        return default
    if isinstance(raw, bool):
        raise ValueError('Boolean price not allowed')
    try:
        dec = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ValueError('Non-numeric price') from None
    if not dec.is_finite() or dec < 0:
        raise ValueError('Negative or non-finite price')
    scaled = float(round(dec * Decimal('1000000'), 8))
    if not math.isfinite(scaled) or scaled < 0 or scaled > 1_000_000:
        raise ValueError('Price out of range')
    return scaled


def _parse_iso_epoch(text):
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith('Z'):
        raw = raw[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def parse_openrouter_models(payload):
    """Parse OpenRouter /api/v1/models or /api/v1/models/user response."""
    raw_models = payload.get('data')
    if not isinstance(raw_models, list):
        raise ProviderFetchError('OpenRouter response missing data array')
    models = []
    seen = set()
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = item.get('id')
        if not isinstance(model_id, str) or not ID_RE.fullmatch(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        base_id, _, variant = model_id.partition(':')
        pricing = item.get('pricing') if isinstance(item.get('pricing'), dict) else {}
        quote_available = False
        prices = {'in': None, 'cache_read': None, 'cache_write': None, 'out': None}
        try:
            p_in = _per_million(pricing.get('prompt'))
            p_out = _per_million(pricing.get('completion'))
            if p_in is not None and p_out is not None:
                p_cr = _per_million(pricing.get('input_cache_read'), default=0.0)
                p_cw = _per_million(pricing.get('input_cache_write'), default=0.0)
                prices = validate_prices({'in': p_in, 'cache_read': p_cr, 'cache_write': p_cw, 'out': p_out})
                quote_available = True
        except ValueError:
            quote_available = False
        models.append({
            'id': model_id,
            'name': str(item.get('name') or model_id)[:160],
            'provider': model_id.split('/', 1)[0] if '/' in model_id else '',
            'variant': variant[:40],
            'quote_available': quote_available,
            **prices,
            'context_length': item.get('context_length') if type(item.get('context_length')) is int else None,
            'created': item.get('created') if type(item.get('created')) is int else None,
            'source': f'https://openrouter.ai/{base_id}',
        })
        if len(models) >= MAX_MODELS_PER_SOURCE:
            break
    return models


def parse_google_models(items):
    """Parse Google Gemini /v1beta/models records."""
    models = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get('name') or '')
        model_id = raw_name.removeprefix('models/').strip()
        if not ID_RE.fullmatch(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        methods = [str(m) for m in (item.get('supportedGenerationMethods') or []) if isinstance(m, str)][:8]
        models.append({
            'id': model_id,
            'display_name': str(item.get('displayName') or model_id)[:160],
            'detail': ', '.join(methods[:4]) if methods else str(item.get('description') or '')[:160],
            'created': None,
            'source': 'https://aistudio.google.com/docs/pricing',
        })
        if len(models) >= MAX_MODELS_PER_SOURCE:
            break
    return models


def parse_openai_models(payload):
    """Parse OpenAI /v1/models response sorted newest-first."""
    raw_models = payload.get('data')
    if not isinstance(raw_models, list):
        raise ProviderFetchError('OpenAI response missing data array')
    models = []
    seen = set()
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = item.get('id')
        if not isinstance(model_id, str) or not ID_RE.fullmatch(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        created = item.get('created') if type(item.get('created')) is int else None
        owned_by = str(item.get('owned_by') or '')[:80]
        models.append({
            'id': model_id,
            'display_name': model_id,
            'detail': owned_by,
            'created': created,
            'source': 'https://openai.com/api/pricing/',
        })
        if len(models) >= MAX_MODELS_PER_SOURCE:
            break
    models.sort(key=lambda m: (-(m['created'] or 0), m['id']))
    return models


def parse_anthropic_models(items):
    """Parse Anthropic /v1/models records sorted newest-first."""
    models = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get('id')
        if not isinstance(model_id, str) or not ID_RE.fullmatch(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        models.append({
            'id': model_id,
            'display_name': str(item.get('display_name') or model_id)[:160],
            'detail': '',
            'created': _parse_iso_epoch(item.get('created_at')),
            'source': 'https://platform.claude.com/docs/en/about-claude/pricing',
        })
        if len(models) >= MAX_MODELS_PER_SOURCE:
            break
    models.sort(key=lambda m: (-(m['created'] or 0), m['id']))
    return models


def parse_deepseek_models(payload):
    """Parse DeepSeek /models response."""
    raw_models = payload.get('data')
    if not isinstance(raw_models, list):
        raise ProviderFetchError('DeepSeek response missing data array')
    models = []
    seen = set()
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = item.get('id')
        if not isinstance(model_id, str) or not ID_RE.fullmatch(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        models.append({
            'id': model_id,
            'display_name': model_id,
            'detail': str(item.get('owned_by') or '')[:80],
            'created': None,
            'source': 'https://api-docs.deepseek.com/quick_start/pricing',
        })
        if len(models) >= MAX_MODELS_PER_SOURCE:
            break
    return models


def fetch_openrouter(api_key='', *, fetcher=None):
    fetcher = fetcher or _fetch_json
    url = 'https://openrouter.ai/api/v1/models/user' if api_key else 'https://openrouter.ai/api/v1/models'
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
    payload = fetcher(url, headers=headers, secret=api_key)
    return parse_openrouter_models(payload)


def fetch_google(api_key, *, fetcher=None):
    fetcher = fetcher or _fetch_json
    items = []
    page_token = ''
    seen_tokens = set()
    for _ in range(MAX_PAGES):
        params = {'pageSize': '1000'}
        if page_token:
            params['pageToken'] = page_token
        url = 'https://generativelanguage.googleapis.com/v1beta/models?' + urlencode(params)
        payload = fetcher(url, headers={'x-goog-api-key': api_key}, secret=api_key)
        batch = payload.get('models')
        if not isinstance(batch, list):
            raise ProviderFetchError('Google Gemini response missing models array')
        items.extend(batch)
        next_token = payload.get('nextPageToken')
        if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
            break
        seen_tokens.add(next_token)
        page_token = next_token
    return parse_google_models(items)


def fetch_openai(api_key, *, fetcher=None):
    fetcher = fetcher or _fetch_json
    payload = fetcher('https://api.openai.com/v1/models', headers={'Authorization': f'Bearer {api_key}'}, secret=api_key)
    return parse_openai_models(payload)


def fetch_anthropic(api_key, *, fetcher=None):
    fetcher = fetcher or _fetch_json
    items = []
    after_id = ''
    seen_cursors = set()
    headers = {'x-api-key': api_key, 'anthropic-version': ANTHROPIC_VERSION}
    for _ in range(MAX_PAGES):
        params = {'limit': '1000'}
        if after_id:
            params['after_id'] = after_id
        url = 'https://api.anthropic.com/v1/models?' + urlencode(params)
        payload = fetcher(url, headers=headers, secret=api_key)
        batch = payload.get('data')
        if not isinstance(batch, list):
            raise ProviderFetchError('Anthropic response missing data array')
        items.extend(batch)
        last_id = payload.get('last_id')
        if not payload.get('has_more') or not isinstance(last_id, str) or not last_id or last_id in seen_cursors:
            break
        seen_cursors.add(last_id)
        after_id = last_id
    return parse_anthropic_models(items)


def fetch_deepseek(api_key, *, fetcher=None):
    fetcher = fetcher or _fetch_json
    payload = fetcher('https://api.deepseek.com/models', headers={'Authorization': f'Bearer {api_key}'}, secret=api_key)
    return parse_deepseek_models(payload)


FETCHERS = {
    'openrouter': fetch_openrouter,
    'google': fetch_google,
    'openai': fetch_openai,
    'anthropic': fetch_anthropic,
    'deepseek': fetch_deepseek,
}


def _strip_date_suffix(model_id):
    return re.sub(r'-(?:20\d{6}|\d{4}-\d{2}-\d{2})$', '', model_id)


def _known_priced_set(default_prices, overrides):
    return set(default_prices.keys()) | set(overrides.keys())


def _is_model_priced(model_id, default_prices, overrides):
    model = resolve_price_model(model_id, overrides, default_prices)
    return model in default_prices or model in overrides


def _canonical_known_id(candidate, known_models, default_prices):
    if candidate not in known_models:
        return None
    entry = default_prices.get(candidate)
    if entry and 'alias' in entry:
        return entry['alias']
    return candidate


def match_local_model(quote, known_models, default_prices):
    """Map an OpenRouter quote to a tracked local/observed model ID when unambiguous."""
    qid = quote['id']
    if quote.get('variant') or ':' in qid or '/' not in qid:
        return _canonical_known_id(qid, known_models, default_prices)

    native = openrouter_native_id(qid)
    if native == qid:
        exact = _canonical_known_id(qid, known_models, default_prices)
        if exact:
            return exact
    slug = qid.split('/', 1)[1]
    candidates = [native, slug]
    if qid.startswith('anthropic/claude-'):
        candidates.extend(model_price_candidates(native))
    for candidate in dict.fromkeys(candidates):
        for model in dict.fromkeys((candidate, _strip_date_suffix(candidate))):
            matched = _canonical_known_id(model, known_models, default_prices)
            if matched:
                return matched
    return None


def _build_quote_indexes(or_models):
    exact_by_id = {}
    standard_by_id = {}
    anthropic_dash = {}
    slug_candidates = {}
    for quote in or_models:
        if not isinstance(quote, dict) or not quote.get('id'):
            continue
        qid = quote['id']
        exact_by_id[qid] = quote
        if quote.get('variant'):
            continue
        standard_by_id[qid] = quote
        if '/' in qid:
            slug = qid.split('/', 1)[1]
            slug_candidates.setdefault(slug, []).append(quote)
            if quote.get('provider') == 'anthropic':
                anthropic_dash.setdefault(slug.replace('.', '-'), quote)
    unique_slugs = {slug: items[0] for slug, items in slug_candidates.items() if len(items) == 1}
    return exact_by_id, standard_by_id, anthropic_dash, unique_slugs


def find_openrouter_quote_for_model(
    model_id, source_id, standard_quotes_by_id, anthropic_dash_quotes,
    *, exact_quotes_by_id=None, unique_slug_quotes=None,
):
    """Find a matching OpenRouter quote (exact or normalized) for an observed or discovered model."""
    candidates = model_price_candidates(model_id)
    candidates += tuple(_strip_date_suffix(candidate) for candidate in candidates)
    for cand in dict.fromkeys(candidates):
        if exact_quotes_by_id and cand in exact_quotes_by_id:
            return exact_quotes_by_id[cand]
        keys = (cand, f'{source_id}/{cand}') if source_id else (cand,)
        for key in keys:
            if key in standard_quotes_by_id:
                return standard_quotes_by_id[key]
        if source_id in ('', 'anthropic', None) and cand in anthropic_dash_quotes:
            return anthropic_dash_quotes[cand]
        quote = (unique_slug_quotes or {}).get(cand)
        if quote and (not source_id or quote.get('provider') == source_id):
            return quote
    return None


def _default_source_entry(source_id):
    meta = PROVIDERS[source_id]
    return {
        'enabled': meta['default_enabled'],
        'api_key': '',
        'status': 'idle',
        'error': '',
        'checked_at': None,
        'models': [],
        'last_new_ids': [],
        'dismissed_ids': [],
        'first_seen': {},
    }


def _default_state():
    return {
        'sources': {sid: _default_source_entry(sid) for sid in PROVIDER_IDS},
        'schedule': {
            'enabled': True,
            'interval_hours': 1,
            'next_at': 0,
            'auto_sync_openrouter': False,
        },
        'last_checked': None,
        'unpriced_lookup_at': None,
        'unpriced_checked_ids': [],
    }


class ProviderSourceStore:
    """Thread-safe 0600 store for API keys, check schedules, quotes, and discovered models."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def state(self):
        with self.lock:
            defaults = _default_state()
            try:
                raw = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(raw, dict):
                    raise ValueError('invalid provider sources state')
            except (FileNotFoundError, ValueError, OSError):
                return defaults
            raw_sources = raw.get('sources') if isinstance(raw.get('sources'), dict) else {}
            for sid in PROVIDER_IDS:
                entry = raw_sources.get(sid)
                if isinstance(entry, dict):
                    target = defaults['sources'][sid]
                    if isinstance(entry.get('enabled'), bool):
                        target['enabled'] = entry['enabled']
                    if isinstance(entry.get('api_key'), str):
                        target['api_key'] = entry['api_key']
                    if isinstance(entry.get('status'), str):
                        target['status'] = entry['status']
                    if isinstance(entry.get('error'), str):
                        target['error'] = entry['error']
                    if type(entry.get('checked_at')) is int:
                        target['checked_at'] = entry['checked_at']
                    if isinstance(entry.get('models'), list):
                        target['models'] = entry['models']
                    if isinstance(entry.get('last_new_ids'), list):
                        target['last_new_ids'] = [m for m in entry['last_new_ids'] if isinstance(m, str)]
                    if isinstance(entry.get('dismissed_ids'), list):
                        target['dismissed_ids'] = [m for m in entry['dismissed_ids'] if isinstance(m, str)]
                    if isinstance(entry.get('first_seen'), dict):
                        target['first_seen'] = {k: v for k, v in entry['first_seen'].items()
                                                if isinstance(k, str) and type(v) is int}
            raw_schedule = raw.get('schedule') if isinstance(raw.get('schedule'), dict) else {}
            sched = defaults['schedule']
            if isinstance(raw_schedule.get('enabled'), bool):
                sched['enabled'] = raw_schedule['enabled']
            if type(raw_schedule.get('interval_hours')) is int and 1 <= raw_schedule['interval_hours'] <= 720:
                sched['interval_hours'] = raw_schedule['interval_hours']
            if type(raw_schedule.get('next_at')) is int:
                sched['next_at'] = raw_schedule['next_at']
            if isinstance(raw_schedule.get('auto_sync_openrouter'), bool):
                sched['auto_sync_openrouter'] = raw_schedule['auto_sync_openrouter']
            if type(raw.get('last_checked')) is int:
                defaults['last_checked'] = raw['last_checked']
            if type(raw.get('unpriced_lookup_at')) is int:
                defaults['unpriced_lookup_at'] = raw['unpriced_lookup_at']
            if isinstance(raw.get('unpriced_checked_ids'), list):
                defaults['unpriced_checked_ids'] = [m for m in raw['unpriced_checked_ids'] if isinstance(m, str)]
            return defaults

    def _save(self, data):
        secure_write(self.path, json.dumps(data, ensure_ascii=False, indent=2))

    def configure(self, *, sources=None, schedule=None):
        with self.lock:
            data = self.state()
            if sources is not None:
                if not isinstance(sources, dict):
                    raise ValueError('Sources configuration must be an object')
                for sid, patch in sources.items():
                    if sid not in PROVIDERS or not isinstance(patch, dict):
                        raise ValueError(f'Unsupported provider source: {sid}')
                    entry = data['sources'][sid]
                    if 'enabled' in patch:
                        if not isinstance(patch['enabled'], bool):
                            raise ValueError('Source enabled flag must be true or false')
                        entry['enabled'] = patch['enabled']
                    if patch.get('clear_key') is True:
                        entry['api_key'] = ''
                    elif 'api_key' in patch and patch['api_key'] is not None:
                        cleaned = _validate_api_key(patch['api_key'])
                        if cleaned:
                            entry['api_key'] = cleaned
            if schedule is not None:
                if not isinstance(schedule, dict):
                    raise ValueError('Schedule configuration must be an object')
                sched = data['schedule']
                previous_enabled = sched['enabled']
                previous_interval = sched['interval_hours']
                if 'enabled' in schedule:
                    if not isinstance(schedule['enabled'], bool):
                        raise ValueError('Schedule enabled flag must be true or false')
                    sched['enabled'] = schedule['enabled']
                if 'interval_hours' in schedule:
                    raw_hours = schedule['interval_hours']
                    if isinstance(raw_hours, bool):
                        raise ValueError('Interval hours must be a number between 1 and 720')
                    try:
                        hours = int(raw_hours)
                    except (TypeError, ValueError):
                        raise ValueError('Interval hours must be a number between 1 and 720') from None
                    if hours < 1 or hours > 720:
                        raise ValueError('Check interval must be between 1 and 720 hours')
                    sched['interval_hours'] = hours
                if 'auto_sync_openrouter' in schedule:
                    if not isinstance(schedule['auto_sync_openrouter'], bool):
                        raise ValueError('auto_sync_openrouter must be true or false')
                    sched['auto_sync_openrouter'] = schedule['auto_sync_openrouter']
                if sched['enabled'] and (not previous_enabled or sched['interval_hours'] != previous_interval):
                    if data['last_checked']:
                        sched['next_at'] = int(time.time()) + sched['interval_hours'] * 3600
                    else:
                        sched['next_at'] = 0
            self._save(data)
            return copy.deepcopy(data)

    def claim_due(self):
        with self.lock:
            data = self.state()
            sched = data['schedule']
            now = int(time.time())
            if not sched.get('enabled') or now < sched.get('next_at', 0):
                return None
            enabled_sources = [sid for sid in PROVIDER_IDS if data['sources'][sid]['enabled']]
            sched['next_at'] = now + max(1, int(sched.get('interval_hours', 1))) * 3600
            self._save(data)
            return enabled_sources

    def record_results(self, results, *, checked_at=None, reset_next=False):
        now = int(time.time()) if checked_at is None else int(checked_at)
        with self.lock:
            data = self.state()
            for sid, outcome in results.items():
                if sid not in PROVIDERS:
                    continue
                entry = data['sources'][sid]
                entry['checked_at'] = now
                entry['status'] = outcome['status']
                entry['error'] = str(outcome.get('error') or '')[:300]
                if outcome['status'] == 'ok':
                    models = outcome['models']
                    prev_ids = {m['id'] for m in entry['models'] if isinstance(m, dict) and isinstance(m.get('id'), str)}
                    had_prev = bool(prev_ids)
                    first_seen = dict(entry.get('first_seen') or {})
                    new_ids = []
                    for model in models:
                        mid = model['id']
                        if mid not in first_seen:
                            first_seen[mid] = now
                        if had_prev and mid not in prev_ids:
                            new_ids.append(mid)
                    current_set = {m['id'] for m in models}
                    entry['first_seen'] = {mid: ts for mid, ts in first_seen.items() if mid in current_set}
                    entry['models'] = models
                    entry['last_new_ids'] = new_ids
            data['last_checked'] = now
            if reset_next and data['schedule']['enabled']:
                data['schedule']['next_at'] = now + max(1, int(data['schedule']['interval_hours'])) * 3600
            self._save(data)
            return data

    def dismiss_discovered(self, source_id, model_id):
        if source_id not in DISCOVERY_IDS:
            raise ValueError('Unsupported discovery source')
        if not isinstance(model_id, str) or not ID_RE.fullmatch(model_id):
            raise ValueError('Invalid model ID')
        with self.lock:
            data = self.state()
            dismissed = data['sources'][source_id]['dismissed_ids']
            if model_id not in dismissed:
                dismissed.append(model_id)
                self._save(data)

    def restore_discovered(self, source_id, model_id):
        if source_id not in DISCOVERY_IDS:
            raise ValueError('Unsupported discovery source')
        if not isinstance(model_id, str) or not ID_RE.fullmatch(model_id):
            raise ValueError('Invalid model ID')
        with self.lock:
            data = self.state()
            data['sources'][source_id]['dismissed_ids'] = [
                mid for mid in data['sources'][source_id]['dismissed_ids'] if mid != model_id
            ]
            self._save(data)

    def mark_unpriced_checked(self, model_ids, *, checked_at=None):
        now = int(time.time()) if checked_at is None else int(checked_at)
        cleaned = sorted({m for m in (model_ids or ()) if isinstance(m, str) and m})
        with self.lock:
            data = self.state()
            merged = sorted(set(data.get('unpriced_checked_ids') or ()) | set(cleaned))
            data['unpriced_checked_ids'] = merged[-500:]
            data['unpriced_lookup_at'] = now
            self._save(data)
            return data

    def get_openrouter_quote(self, quote_id):
        with self.lock:
            models = self.state()['sources']['openrouter']['models']
        for item in models:
            if item.get('id') == quote_id:
                return copy.deepcopy(item)
        return None

    def public_state(self, price_store, default_prices, observed_models, *, running=False):
        with self.lock:
            raw = self.state()
        price_state = price_store.state()
        overrides = price_state['overrides']
        metadata = price_state['metadata']
        now = time.time()
        known_priced = set(default_prices.keys()) | set(overrides.keys())
        known_all = known_priced | {candidate for model in (observed_models or ())
                                    for candidate in model_price_candidates(model)}

        or_entry = raw['sources']['openrouter']
        or_models = []
        exact_by_id, standard_by_id, anthropic_dash, unique_slugs = _build_quote_indexes(
            [item for item in or_entry['models'] if isinstance(item, dict) and item.get('quote_available')]
        )
        all_or_exact, all_or_standard, all_or_dash, all_or_slugs = _build_quote_indexes(or_entry['models'])
        matched_count = 0
        diff_count = 0
        quoted_count = 0
        dynamic_count = 0

        for item in or_entry['models']:
            if not isinstance(item, dict) or not item.get('id'):
                continue
            quote = copy.deepcopy(item)
            if quote.get('quote_available'):
                quoted_count += 1
            else:
                dynamic_count += 1
            matched = match_local_model(quote, known_all, default_prices)
            quote['matched_model'] = matched
            if matched:
                matched_count += 1
                is_priced = matched in known_priced
                cur_rates = overrides.get(matched) or (dict(zip(FIELDS, default_rates(matched, now))) if matched in default_prices else None)
                quote['current_price'] = cur_rates
                quote['is_manual'] = metadata.get(matched, {}).get('source') == 'manual'
                quote['current_source'] = metadata.get(matched, {}).get('source') or ('built-in' if matched in default_prices else '')
                if quote.get('quote_available'):
                    quote['price_differs'] = (not is_priced) or any(
                        not math.isclose(cur_rates.get(f, 0.0), quote[f], rel_tol=0.0, abs_tol=1e-9)
                        for f in FIELDS
                    )
                    if quote['price_differs']:
                        diff_count += 1
                else:
                    quote['price_differs'] = False
            else:
                quote['current_price'] = None
                quote['is_manual'] = False
                quote['current_source'] = ''
                quote['price_differs'] = False
            or_models.append(quote)

        sources_out = {
            'openrouter': {
                **PROVIDERS['openrouter'],
                'enabled': or_entry['enabled'],
                'api_key_saved': bool(or_entry['api_key']),
                'status': or_entry['status'],
                'error': or_entry['error'],
                'checked_at': or_entry['checked_at'],
                'total_count': len(or_models),
                'quoted_count': quoted_count,
                'dynamic_count': dynamic_count,
                'matched_count': matched_count,
                'diff_count': diff_count,
                'last_new_count': len(or_entry['last_new_ids']),
                'models': or_models,
            }
        }

        for sid in DISCOVERY_IDS:
            entry = raw['sources'][sid]
            dismissed_set = set(entry['dismissed_ids'])
            new_set = set(entry['last_new_ids'])
            first_seen = entry.get('first_seen') or {}
            discovered = []
            unpriced_count = 0
            new_count = 0
            dismissed_count = 0
            for item in entry['models']:
                if not isinstance(item, dict) or not item.get('id'):
                    continue
                mid = item['id']
                in_catalog = _is_model_priced(mid, default_prices, overrides)
                is_dismissed = mid in dismissed_set
                is_new = mid in new_set
                if is_dismissed:
                    dismissed_count += 1
                elif not in_catalog:
                    unpriced_count += 1
                if is_new and not is_dismissed:
                    new_count += 1
                or_quote = find_openrouter_quote_for_model(
                    mid, sid, standard_by_id, anthropic_dash,
                    exact_quotes_by_id=exact_by_id, unique_slug_quotes=unique_slugs,
                )
                discovered.append({
                    **item,
                    'in_catalog': in_catalog,
                    'observed': mid in known_all and not in_catalog,
                    'dismissed': is_dismissed,
                    'is_new_since_last': is_new,
                    'first_seen_at': first_seen.get(mid),
                    'openrouter_quote': {
                        'id': or_quote['id'],
                        **{f: or_quote[f] for f in FIELDS},
                        'source': or_quote['source'],
                    } if or_quote else None,
                })
            sources_out[sid] = {
                **PROVIDERS[sid],
                'enabled': entry['enabled'],
                'api_key_saved': bool(entry['api_key']),
                'status': entry['status'],
                'error': entry['error'],
                'checked_at': entry['checked_at'],
                'total_count': len(discovered),
                'unpriced_count': unpriced_count,
                'new_count': new_count,
                'dismissed_count': dismissed_count,
                'models': discovered,
            }

        # Collect every unpriced local/observed and non-dismissed discovered model with its OpenRouter match state.
        unpriced_map = {}
        for mid in sorted(set(observed_models or ())):
            if not mid or mid == 'unknown' or _is_model_priced(mid, default_prices, overrides):
                continue
            unpriced_map[mid] = {'id': mid, 'origin': 'observed', 'sources': ['local']}
        for sid in DISCOVERY_IDS:
            for item in sources_out[sid]['models']:
                mid = item['id']
                if item.get('dismissed') or item.get('in_catalog'):
                    continue
                if mid in unpriced_map:
                    unpriced_map[mid]['origin'] = 'both'
                    if sid not in unpriced_map[mid]['sources']:
                        unpriced_map[mid]['sources'].append(sid)
                else:
                    unpriced_map[mid] = {'id': mid, 'origin': 'discovered', 'sources': [sid]}

        unpriced_models = []
        matched_unpriced = 0
        dynamic_unpriced = 0
        checked_set = set(raw.get('unpriced_checked_ids') or ())
        or_checked = bool(or_entry.get('checked_at'))
        for mid in sorted(unpriced_map):
            info = unpriced_map[mid]
            source_hint = next((s for s in info['sources'] if s in DISCOVERY_IDS), '')
            quoted = find_openrouter_quote_for_model(
                mid, source_hint, standard_by_id, anthropic_dash,
                exact_quotes_by_id=exact_by_id, unique_slug_quotes=unique_slugs,
            )
            any_match = quoted or find_openrouter_quote_for_model(
                mid, source_hint, all_or_standard, all_or_dash,
                exact_quotes_by_id=all_or_exact, unique_slug_quotes=all_or_slugs,
            )
            if quoted:
                match_status = 'quoted'
                matched_unpriced += 1
            elif any_match and not any_match.get('quote_available'):
                match_status = 'dynamic'
                dynamic_unpriced += 1
            elif or_checked or mid in checked_set:
                match_status = 'unmatched'
            else:
                match_status = 'unchecked'
            unpriced_models.append({
                **info,
                'checked': or_checked or mid in checked_set,
                'match_status': match_status,
                'openrouter_quote': {
                    'id': quoted['id'],
                    'name': quoted.get('name') or quoted['id'],
                    **{f: quoted[f] for f in FIELDS},
                    'source': quoted['source'],
                } if quoted else None,
            })

        return {
            'order': list(PROVIDER_IDS),
            'sources': sources_out,
            'schedule': raw['schedule'],
            'last_checked': raw['last_checked'],
            'running': running,
            'unpriced_models': unpriced_models,
            'unpriced_summary': {
                'total': len(unpriced_models),
                'matched': matched_unpriced,
                'dynamic': dynamic_unpriced,
                'unmatched': sum(1 for item in unpriced_models if item['match_status'] == 'unmatched'),
                'unchecked': sum(1 for item in unpriced_models if item['match_status'] == 'unchecked'),
                'last_lookup_at': raw.get('unpriced_lookup_at') or or_entry.get('checked_at'),
            },
        }


class ProviderSyncManager:
    """Coordinates manual and scheduled source checks and OpenRouter auto-sync."""

    def __init__(self, store, price_store, default_prices, *, fetchers=None, on_prices_updated=None):
        self.store = store
        self.price_store = price_store
        self.default_prices = default_prices
        self.fetchers = fetchers or FETCHERS
        self.on_prices_updated = on_prices_updated
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.running = False

    def _fetch_one(self, sid, api_key):
        meta = PROVIDERS[sid]
        if meta['requires_key'] and not api_key:
            return {'status': 'needs_key', 'error': 'API key required'}
        try:
            models = self.fetchers[sid](api_key)
            return {'status': 'ok', 'error': '', 'models': models}
        except (ProviderFetchError, ValueError, KeyError, TypeError) as error:
            return {'status': 'error', 'error': _redact(error, api_key)[:300]}

    def _unpriced_ids(self, observed_models=None, *, price_store=None):
        snapshot = self.store.state()
        target_price_store = price_store or self.price_store
        overrides = target_price_store.overrides()
        ids = {
            mid for mid in (observed_models or ())
            if isinstance(mid, str) and mid and mid != 'unknown' and not _is_model_priced(mid, self.default_prices, overrides)
        }
        for sid in DISCOVERY_IDS:
            entry = snapshot['sources'][sid]
            dismissed = set(entry.get('dismissed_ids') or ())
            for item in entry.get('models') or ():
                if isinstance(item, dict) and isinstance(item.get('id'), str):
                    mid = item['id']
                    if mid not in dismissed and not _is_model_priced(mid, self.default_prices, overrides):
                        ids.add(mid)
        return sorted(ids)

    def _auto_sync(self, observed_models, *, price_store=None, unpriced_ids=None):
        state = self.store.state()
        if not state['schedule'].get('auto_sync_openrouter'):
            return None
        return self.sync_matched(
            observed_models=set(observed_models or ()) | set(unpriced_ids or ()),
            price_store=price_store,
            keep_official_openai=True,
        )

    def sync_matched(self, *, observed_models=None, price_store=None, keep_official_openai=False, include_discovered=False):
        target_price_store = price_store or self.price_store
        overrides = target_price_store.overrides()
        discovered_ids = set()
        snapshot = self.store.state()
        if include_discovered:
            for sid in DISCOVERY_IDS:
                entry = snapshot['sources'][sid]
                dismissed = set(entry.get('dismissed_ids') or ())
                for item in entry.get('models') or ():
                    if isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'] not in dismissed:
                        discovered_ids.add(item['id'])
        observed_ids = {candidate for model in (observed_models or ()) for candidate in model_price_candidates(model)}
        known_all = set(self.default_prices) | set(overrides) | observed_ids | discovered_ids
        quotes = snapshot['sources']['openrouter']['models']
        entries = []
        seen_targets = set()
        for quote in quotes:
            if not isinstance(quote, dict) or not quote.get('quote_available'):
                continue
            target = match_local_model(quote, known_all, self.default_prices)
            if quote.get('variant') and target != quote['id']:
                continue
            if not target or target in seen_targets:
                continue
            if keep_official_openai:
                default = self.default_prices.get(target, {})
                canonical = default.get('alias', target)
                source = self.default_prices.get(canonical, {}).get('source', '')
                if source.startswith('https://developers.openai.com/api/docs/models/'):
                    continue
            seen_targets.add(target)
            entries.append({
                'model': target,
                **{f: quote[f] for f in FIELDS},
                'source': quote['source'],
                'description': quote.get('name') or quote['id'],
                'channel_model': quote['id'],
            })
        result = target_price_store.sync_channel_prices(entries, channel='openrouter')
        if result['synced'] and self.on_prices_updated:
            self.on_prices_updated()
        return result

    def lookup_unpriced_models(self, *, observed_models=None, force=False, price_store=None):
        """Query OpenRouter when unpriced models are detected and return match summary."""
        with self._run_lock:
            snapshot = self.store.state()
            target_price_store = price_store or self.price_store
            unpriced = self._unpriced_ids(observed_models, price_store=target_price_store)
            if not unpriced and not force:
                return {'checked': False, 'unpriced_count': 0, 'matched': []}
            checked_before = set(snapshot.get('unpriced_checked_ids') or ())
            new_unpriced = [m for m in unpriced if m not in checked_before]
            or_checked_at = snapshot['sources']['openrouter'].get('checked_at') or 0
            or_stale = (not or_checked_at) or (time.time() - or_checked_at > 900)
            if force or (unpriced and (new_unpriced or or_stale)):
                with self._state_lock:
                    self.running = True
                try:
                    outcome = self._fetch_one('openrouter', snapshot['sources']['openrouter']['api_key'])
                    self.store.record_results({'openrouter': outcome}, reset_next=False)
                finally:
                    with self._state_lock:
                        self.running = False
            self.store.mark_unpriced_checked(unpriced)
            if self.store.state()['sources']['openrouter']['status'] == 'ok':
                self._auto_sync(observed_models, price_store=target_price_store, unpriced_ids=unpriced)
            pub = self.public_state(target_price_store, self.default_prices, observed_models or ())
            matched = [item for item in pub['unpriced_models'] if item.get('openrouter_quote')]
            return {'checked': True, 'unpriced_count': len(unpriced), 'new_unpriced': new_unpriced, 'matched': matched}

    def start_unpriced_lookup_if_needed(self, *, observed_models=None):
        with self._state_lock:
            if self.running:
                return False
        snapshot = self.store.state()
        unpriced = self._unpriced_ids(observed_models)
        if not unpriced:
            return False
        checked_before = set(snapshot.get('unpriced_checked_ids') or ())
        has_new = any(m not in checked_before for m in unpriced)
        if not has_new:
            return False

        def _worker():
            try:
                self.lookup_unpriced_models(observed_models=observed_models, force=False)
            except Exception as exc:
                print(f'[provider-sync] unpriced lookup error: {exc}', flush=True)

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def refresh(self, source_ids=None, *, scheduled=False, observed_models=None, price_store=None):
        with self._run_lock:
            snapshot = self.store.state()
            if scheduled:
                targets = self.store.claim_due()
                if not targets:
                    return None
            else:
                if source_ids is None:
                    targets = [sid for sid in PROVIDER_IDS if snapshot['sources'][sid]['enabled']]
                else:
                    if not isinstance(source_ids, list):
                        raise ValueError('Source list must be an array')
                    targets = []
                    for sid in source_ids:
                        if sid not in PROVIDERS:
                            raise ValueError(f'Unsupported provider source: {sid}')
                        if sid not in targets:
                            targets.append(sid)
                if not targets:
                    raise ValueError('Select at least one source to check')
            with self._state_lock:
                self.running = True
            try:
                keys = {sid: snapshot['sources'][sid]['api_key'] for sid in targets}
                results = {}
                with ThreadPoolExecutor(max_workers=min(len(targets), 5)) as pool:
                    futures = {sid: pool.submit(self._fetch_one, sid, keys[sid]) for sid in targets}
                    for sid, fut in futures.items():
                        results[sid] = fut.result()
                all_enabled = [sid for sid in PROVIDER_IDS if snapshot['sources'][sid]['enabled']]
                reset_next = not scheduled and set(all_enabled).issubset(set(targets))
                self.store.record_results(results, reset_next=reset_next)
                unpriced = self._unpriced_ids(observed_models, price_store=price_store)
                checked_before = set(snapshot.get('unpriced_checked_ids') or ())
                needs_or_lookup = (
                    'openrouter' not in results
                    and snapshot['sources']['openrouter']['enabled']
                    and bool(unpriced)
                    and (any(m not in checked_before for m in unpriced) or not snapshot['sources']['openrouter'].get('checked_at'))
                )
                if needs_or_lookup:
                    or_outcome = self._fetch_one('openrouter', snapshot['sources']['openrouter']['api_key'])
                    results['openrouter'] = or_outcome
                    self.store.record_results({'openrouter': or_outcome}, reset_next=False)
                if unpriced:
                    self.store.mark_unpriced_checked(unpriced)
                if results.get('openrouter', {}).get('status') == 'ok':
                    self._auto_sync(observed_models, price_store=price_store, unpriced_ids=unpriced)
                return results
            finally:
                with self._state_lock:
                    self.running = False

    def start_scheduled(self, *, observed_models=None):
        with self._state_lock:
            if self.running:
                return False
        raw = self.store.state()
        sched = raw['schedule']
        if not sched.get('enabled') or int(time.time()) < sched.get('next_at', 0):
            return False
        if not any(raw['sources'][sid]['enabled'] for sid in PROVIDER_IDS):
            return False

        def _worker():
            try:
                self.refresh(scheduled=True, observed_models=observed_models)
            except Exception as exc:
                print(f'[provider-sync] error: {exc}', flush=True)

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def public_state(self, price_store=None, default_prices=None, observed_models=None):
        return self.store.public_state(
            price_store or self.price_store,
            self.default_prices if default_prices is None else default_prices,
            observed_models or (),
            running=self.running,
        )
