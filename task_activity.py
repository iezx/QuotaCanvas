"""Incremental local-log output throughput; no prompts or log paths leave this module."""
from collections import deque
from contextlib import closing
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
from zstandard import ZstdError
from remote_access import secure_write
from usage_logs import agy_model, dsh_events, dsh_journals, logged_model

WINDOW_SECONDS = 30
MAX_BYTES = 1024 * 1024


def timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0


class TaskActivity:
    def __init__(self, codex_home, agy_home, claude_home, *, history_path=None, dsh_home=None):
        self.homes = [Path(codex_home), Path(agy_home), Path(claude_home)]
        self.files = {}
        self.dsh_home = Path(dsh_home) if dsh_home is not None else None
        self.dsh_files = {}
        self._agy_backfilled = False
        self.discovered = float('-inf')
        self.lock = threading.Lock()
        self.history_path = Path(history_path) if history_path is not None else None
        self._history, self._history_dirty = None, False

    def _load_history(self):
        if self._history is None:
            try:
                self._history = json.loads(self.history_path.read_text(encoding='utf-8')) if self.history_path else []
            except FileNotFoundError:
                self._history = []
            if not isinstance(self._history, list):
                self._history = None
                raise ValueError('Invalid task history')
        return self._history

    def history(self):
        with self.lock:
            rows = self._load_history()
            if not self._agy_backfilled:
                self._backfill_agy(rows)
                self._agy_backfilled = True
            return list(rows)

    def _backfill_agy(self, rows):
        missing = {}
        for row in rows:
            if row.get('source') == 'agy' and not row.get('model'):
                missing.setdefault(row.get('session_id'), []).append(row)
        for path in (self.homes[1] / 'brain').glob('*/.system_generated/logs/transcript.jsonl'):
            pending = missing.get(path.parents[2].name)
            if not pending:
                continue
            changes = []
            try:
                with path.open(encoding='utf-8', errors='replace') as log:
                    for line in log:
                        try:
                            record = json.loads(line)
                            model = agy_model(record)
                            stamp = timestamp(record.get('created_at') or record.get('timestamp'))
                        except (ValueError, AttributeError):
                            continue
                        if model and stamp:
                            changes.append((stamp, model))
            except OSError:
                continue
            changes.sort()
            for row in pending:
                for stamp, model in reversed(changes):
                    if stamp <= row['completed_at']:
                        row['model'] = model
                        self._history_dirty = True
                        break

    def _finish(self, state, stamp, payload=None):
        payload = payload or {}
        if state['model'] == 'codex-auto-review':
            return
        start = timestamp(payload.get('started_at')) or state['started_at']
        duration = payload.get('duration_ms')
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration > 0:
            duration /= 1000
            start = start or stamp - duration
        else:
            duration = stamp - start if start and stamp > start else None
        key = f"{state['source']}:{state['id']}:{state['turn'] or start or stamp}"
        rate = state['output_tokens'] / duration if duration and state['usage_complete'] else None
        row = {name: state[name] for name in ('source', 'model', 'output_tokens', 'status')}
        row.update(id=key, session_id=state['id'], started_at=start, completed_at=stamp,
                   duration_seconds=round(duration, 3) if duration else None,
                   average_tokens_per_second=round(rate, 2) if rate is not None else None,
                   partial=not state['usage_complete'])
        rows = self._load_history()
        previous = next((item for item in rows if item.get('id') == key), None)
        if previous == row:
            return
        self._history = sorted([row, *[item for item in rows if item.get('id') != key]],
                               key=lambda item: item['completed_at'], reverse=True)[:500]
        self._history_dirty = True

    def _discover(self, now):
        if now - self.discovered < 5:
            return
        self.discovered = now
        codex, agy, claude = self.homes
        candidates = [('codex', path) for path in (codex / 'sessions').glob('**/*.jsonl')]
        candidates += [('agy', path) for path in (agy / 'brain').glob('*/.system_generated/logs/transcript.jsonl')]
        candidates += [('cc', path) for path in (claude / 'projects').glob('**/*.jsonl')]
        recent = []
        for source, path in candidates:
            try:
                modified = path.stat().st_mtime
                if modified >= now - 600:
                    recent.append((modified, source, path))
            except OSError:
                continue
        selected = {path: source for _, source, path in sorted(recent, reverse=True)}
        self.files = {path: self.files.get(path) or self._state(source, path)
                      for path, source in selected.items()}
        selected_dsh = sorted(dsh_journals(self.dsh_home) if self.dsh_home else [], key=lambda entry: entry[1].st_mtime, reverse=True)
        self.dsh_files = {path: self._read_dsh(path, stat)
                          for path, stat in selected_dsh[:32] if stat.st_mtime >= now - 7 * 86400}
        # Long-running sessions may have their model context outside the initial tail.
        database = codex / 'state_5.sqlite'
        if database.is_file():
            try:
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.1)) as connection:
                    for rollout, model in connection.execute('SELECT rollout_path, model FROM threads ORDER BY updated_at DESC LIMIT 64'):
                        state = self.files.get(Path(rollout or ''))
                        if state and model and not state['model']:
                            state['model'] = model
            except (sqlite3.Error, OSError, ValueError):
                pass

    def _read_dsh(self, path, stat):
        sig = (stat.st_mtime_ns, stat.st_size)
        cached = self.dsh_files.get(path)
        if cached and cached[0] == sig:
            return cached
        state = self._state('dsh', path)
        state['id'] = path.parent.name
        try:
            for kind, stamp, turn, reason, model, counts in dsh_events(path):
                state['updated_at'] = max(state['updated_at'], stamp)
                if model and kind != 'compaction/summary':
                    state['model'] = model
                if kind == 'turn/start':
                    self._reset(state, str(turn), stamp)
                elif kind == 'assistant/message' and counts is not None and state['turn'] == str(turn):
                    state['output_tokens'] += counts[-1]
                    if counts[-1]:
                        state['events'].append((stamp, counts[-1]))
                elif kind == 'turn/end' and state['turn'] == str(turn):
                    state['status'] = 'completed' if isinstance(reason, dict) and reason.get('kind') == 'completed' else 'stopped'
                    self._finish(state, stamp)
        except (OSError, ZstdError):
            return cached or (None, state)
        return sig, state

    @staticmethod
    def _state(source, path):
        return {'source': source, 'id': path.parents[2].name if source == 'agy' else path.stem,
                'offset': 0, 'pending': b'', 'model': '', 'turn': '', 'output_tokens': 0,
                'events': deque(), 'seen': {}, 'records': False, 'legacy_total': None,
                'status': 'running', 'updated_at': 0, 'started_at': None, 'usage_complete': False}

    @staticmethod
    def _reset(state, turn, stamp):
        state.update(turn=turn, output_tokens=0, events=deque(), seen={}, records=False,
                     status='running', started_at=stamp, usage_complete=stamp is not None)

    def _record(self, state, obj):
        if not isinstance(obj, dict):
            return
        source, kind = state['source'], obj.get('type')
        stamp = timestamp(obj.get('timestamp') or obj.get('created_at'))
        if not stamp:
            return
        state['updated_at'] = max(stamp, state['updated_at'])
        payload = obj.get('payload') or {}
        if not isinstance(payload, dict):
            return
        output, key, finished = None, '', False
        if source == 'codex':
            event = payload.get('type') if kind == 'event_msg' else ''
            if event == 'task_started':
                self._reset(state, payload.get('turn_id'), stamp)
            elif event in ('task_complete', 'turn_aborted'):
                state['status'] = 'completed' if event == 'task_complete' else 'stopped'
                self._finish(state, stamp, payload)
            elif kind in ('session_meta', 'turn_context'):
                state['model'] = logged_model(payload) or state['model']
            elif event == 'thread_settings_applied':
                state['model'] = logged_model(payload.get('thread_settings') or {}) or state['model']
            elif kind == 'token_usage_record':
                turn = payload.get('turn_id')
                if turn and turn != state['turn']:
                    self._reset(state, turn, None)
                usage = payload.get('usage') or {}
                state['model'] = logged_model(payload) or logged_model(usage) or state['model']
                output = usage.get('output_tokens')
                key = payload.get('response_id') or str(stamp)
                state['records'] = True
                total = (payload.get('turn_token_usage') or {}).get('output_tokens')
                if isinstance(total, int) and total >= 0:
                    state['output_tokens'] = total
                    state['usage_complete'] = True
            elif event == 'token_count' and not state['records']:
                info = payload.get('info') or {}
                total = (info.get('total_token_usage') or {}).get('output_tokens')
                if isinstance(total, int):
                    previous = state['legacy_total']
                    output = max(0, total - previous) if previous is not None and total >= previous else (info.get('last_token_usage') or {}).get('output_tokens')
                    state['legacy_total'] = total
        elif source == 'agy':
            state['model'] = agy_model(obj) or state['model']
            if kind == 'USER_INPUT':
                self._reset(state, str(stamp), stamp)
            elif kind == 'PLANNER_RESPONSE':
                output = obj.get('output_tokens')
                if obj.get('status') == 'DONE' and obj.get('content') and not obj.get('tool_calls'):
                    state['status'], finished = 'completed', True
        elif source == 'cc':
            if kind == 'user' and not obj.get('isMeta'):
                content = (obj.get('message') or {}).get('content')
                tool_result = isinstance(content, list) and any(isinstance(item, dict) and item.get('type') == 'tool_result' for item in content)
                if not tool_result:
                    self._reset(state, str(stamp), stamp)
            elif kind == 'assistant':
                message = obj.get('message') or {}
                output = (message.get('usage') or {}).get('output_tokens')
                state['model'] = logged_model(message) or logged_model(obj) or state['model']
                key = message.get('id') or str(stamp)
                if message.get('stop_reason') == 'end_turn':
                    state['status'], finished = 'completed', True
        if isinstance(output, int) and output >= 0:
            previous = state['seen'].get(key, 0) if key else 0
            delta = max(0, output - previous)
            if key:
                state['seen'][key] = max(previous, output)
            if delta:
                state['events'].append((stamp, delta))
                if source != 'codex' or not state['records'] or not isinstance((payload.get('turn_token_usage') or {}).get('output_tokens'), int):
                    state['output_tokens'] += delta
        if finished:
            self._finish(state, stamp)

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self._discover(now)
            tasks = []
            for path, state in self.files.items():
                try:
                    with path.open('rb') as stream:
                        size = stream.seek(0, 2)
                        if size < state['offset']:
                            state = self.files[path] = self._state(state['source'], path)
                        start = max(state['offset'], size - MAX_BYTES)
                        stream.seek(start)
                        if start > state['offset']:
                            if state['source'] == 'agy' and not state['model']:
                                # Read only model markers in the prefix before replaying the current tail.
                                stream.seek(0)
                                while stream.tell() < start:
                                    line = stream.readline()
                                    try:
                                        state['model'] = agy_model(json.loads(line)) or state['model']
                                    except (ValueError, AttributeError):
                                        continue
                                stream.seek(start)
                            stream.readline()  # Skip a possibly cut JSON record.
                            state['pending'] = b''
                        data = state['pending'] + stream.read(MAX_BYTES)
                        state['offset'] = stream.tell()
                    lines = data.split(b'\n')
                    state['pending'] = lines.pop()
                    for line in lines:
                        try:
                            self._record(state, json.loads(line))
                        except (ValueError, TypeError, AttributeError, OverflowError):
                            continue  # Partially written or unsupported log record.
                except OSError:
                    continue
            states = [*self.files.values(), *(state for _, state in self.dsh_files.values())]
            for state in states:
                while state['events'] and state['events'][0][0] <= now - WINDOW_SECONDS:
                    state['events'].popleft()
                if not state['updated_at'] or state['updated_at'] < now - 600:
                    continue
                if state['model'] == 'codex-auto-review':
                    continue
                status = state['status']
                if status == 'running' and now - state['updated_at'] > 60:
                    status = 'waiting'
                rate = sum(count for stamp, count in state['events'] if now - WINDOW_SECONDS < stamp <= now) / WINDOW_SECONDS if status in ('running', 'waiting') else 0
                tasks.append({key: state[key] for key in ('id', 'source', 'model', 'output_tokens', 'updated_at', 'started_at')}
                             | {'status': status, 'tokens_per_second': round(rate, 2)})
            tasks.sort(key=lambda task: (task['status'] not in ('running', 'waiting'), -task['updated_at']))
            if self._history_dirty and self.history_path is not None:
                secure_write(self.history_path, json.dumps(self._history, ensure_ascii=False))
                self._history_dirty = False
            return {'generated': now, 'window_seconds': WINDOW_SECONDS, 'tasks': tasks[:12]}
