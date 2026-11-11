"""Read bounded JSON event lines from a local agent process with a hard deadline."""
import json
import os
import queue
import signal
import subprocess
import threading
import time


def run_research_process(command, cwd, on_event, timeout=240):
    events = queue.Queue(maxsize=16)
    stopped = threading.Event()
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               start_new_session=os.name != 'nt', bufsize=0,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def emit(value):
        while not stopped.is_set():
            try:
                events.put(value, timeout=.2)
                return
            except queue.Full:
                pass

    def read():
        pending = b''
        discard = False
        try:
            while not stopped.is_set():
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if not discard and len(line) <= 1_000_000:
                        emit(line)
                    discard = False
                if len(pending) > 1_000_000:
                    pending = b''
                    discard = True
            if pending and not discard:
                emit(pending)
        except (OSError, ValueError):
            pass  # The reader may be interrupted by deadline cleanup.
        finally:
            emit(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    last = {}
    try:
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                raw = events.get(timeout=min(.2, max(.001, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if raw is None:
                break
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(event, dict):
                on_event(event)
                if event.get('event') == 'result' or event.get('type') == 'result' or 'models' in event or 'structured_output' in event:
                    last = event
        process.wait(timeout=max(.001, deadline - time.monotonic()))
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
        return last
    finally:
        stopped.set()
        # A helper can keep stdout open after the CLI leader exits. Always clean
        # up our own process group, not only when process.poll() is None.
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(timeout=1)
        process.stdout.close()  # Unbuffered FileIO does not wait on a reader lock.
