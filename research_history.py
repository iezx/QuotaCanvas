"""Bounded, authenticated-via-server transcripts for model-price research."""
import copy
import json
from pathlib import Path
import re
import threading
import time
import uuid

from remote_access import secure_write


class ResearchHistory:
    MAX_RUNS = 10
    MAX_MESSAGES = 100
    MAX_TEXT = 20000

    def __init__(self, path):
        self.path, self.lock = Path(path), threading.RLock()
        self._runs, self._last_write = None, 0.0

    def _load(self):
        if self._runs is not None:
            return self._runs
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            value = []
        if not isinstance(value, list):
            raise ValueError('Invalid research history')
        self._runs = value
        return self._runs

    def _save(self, runs, *, force=True):
        self._runs = runs[:self.MAX_RUNS]
        # Token deltas can arrive many times per second. Serve them from memory
        # immediately and checkpoint periodically; final status always flushes.
        if force or time.monotonic() - self._last_write >= .5:
            secure_write(self.path, json.dumps(self._runs, ensure_ascii=False))
            self._last_write = time.monotonic()

    def recover(self):
        with self.lock:
            runs = self._load()
            unfinished = [run for run in runs if run['status'] == 'running']
            for run in unfinished:
                run.update(status='interrupted', finished_at=int(time.time()), error='Server restarted before this research run finished')
                run['revision'] += 1
            if unfinished:
                self._save(runs)

    def create(self, agent, model, prompt):
        now = int(time.time())
        run = {'id': uuid.uuid4().hex, 'agent': agent, 'model': model, 'status': 'running',
               'started_at': now, 'finished_at': None, 'error': '', 'revision': 1,
               'messages': [{'id': 'prompt', 'role': 'user', 'text': prompt, 'timestamp': now}],
               'truncated': False, 'session_id': None}
        with self.lock:
            self._save([run, *self._load()])
        return copy.deepcopy(run)

    @staticmethod
    def _find(runs, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
            raise ValueError('Invalid research ID')
        run = next((run for run in runs if run['id'] == run_id), None)
        if run is None:
            raise ValueError('Research run not found')
        return run

    def read(self, run_id):
        with self.lock:
            return copy.deepcopy(self._find(self._load(), run_id))

    def list(self):
        with self.lock:
            return [{key: value for key, value in run.items() if key not in ('messages',)} for run in self._load()]

    def message(self, run_id, role, text, *, key=None, append=False):
        if role not in ('user', 'assistant') or not isinstance(text, str) or not text:
            return
        with self.lock:
            runs = self._load(); run = self._find(runs, run_id)
            message = next((m for m in run['messages'] if key is not None and m['id'] == key), None)
            if message is None:
                message = {'id': key or uuid.uuid4().hex, 'role': role, 'text': '', 'timestamp': int(time.time())}
                run['messages'].append(message)
            value = message['text'] + text if append else text
            message['text'] = value[:self.MAX_TEXT]
            if len(value) > self.MAX_TEXT:
                run['truncated'] = True
            if len(run['messages']) > self.MAX_MESSAGES:
                run['messages'] = [run['messages'][0], *run['messages'][-(self.MAX_MESSAGES - 1):]]
                run['truncated'] = True
            run['revision'] += 1
            self._save(runs, force=not append)

    def session(self, run_id, session_id):
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', session_id):
            return
        with self.lock:
            runs = self._load(); run = self._find(runs, run_id)
            if run.get('session_id') == session_id:
                return
            run['session_id'] = session_id; run['revision'] += 1
            self._save(runs)

    def finish(self, run_id, status, error=''):
        with self.lock:
            runs = self._load(); run = self._find(runs, run_id)
            run.update(status=status, error=error, finished_at=int(time.time()), revision=run['revision'] + 1)
            self._save(runs)
