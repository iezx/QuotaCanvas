"""Publish complete static-page snapshots on local storage."""
from __future__ import annotations

import os
from html.parser import HTMLParser
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time
import uuid
from urllib.parse import unquote, urlsplit


class _StaticReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.urls.append(attrs['src'])
        if tag == 'link' and {'stylesheet', 'icon'} & set((attrs.get('rel') or '').lower().split()) and attrs.get('href'):
            self.urls.append(attrs['href'])


class StaticWebCache:
    def __init__(self, source: Path, base: Path, *, interval=2):
        self.source = Path(source)
        self.base = Path(base)
        source = self.source.resolve()
        base = self.base.resolve()
        if base == source or source in base.parents:
            raise ValueError('静态缓存目录不能位于网页源目录中')
        self.current = self.base / 'current'
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._applied = None
        self._pending = None
        self._error = None
        self._lock = threading.Lock()

    def usable(self):
        try:
            if not self.current.is_symlink():
                return False
            target = os.readlink(self.current)
            if '/' in target or not target.startswith('snapshot-'):
                return False
            folder = self.base / target
            index = folder / 'index.html'
            return not folder.is_symlink() and folder.is_dir() and not index.is_symlink() and index.is_file() and index.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _inventory(self):
        def failed(error):
            raise error
        if not stat.S_ISDIR(self.source.stat().st_mode):
            raise NotADirectoryError('网页源目录不可用')
        files = {}
        for folder, directories, names in os.walk(self.source, onerror=failed, followlinks=False):
            directory = Path(folder)
            for name in directories:
                if (directory / name).is_symlink():
                    raise ValueError('网页源目录不能包含符号链接')
            for name in names:
                path = directory / name
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('网页源目录只能包含普通文件')
                if info.st_size == 0 and path.suffix.lower() in ('.html', '.js', '.css', '.svg'):
                    raise ValueError('网页源文件为空，等待构建完成')
                files[path.relative_to(self.source)] = self._signature(info)
        if Path('index.html') not in files or files[Path('index.html')][2] == 0:
            raise ValueError('网页源目录缺少有效首页')
        return files

    def refresh(self, *, require_stable=False):
        """Only publish after every file was read and the source remained stable."""
        with self._lock:
            inventory = self._inventory()
            if inventory == self._applied and self.usable():
                self._pending = None
                return False
            if require_stable and self.usable() and inventory != self._pending:
                self._pending = inventory
                return False
            self.base.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.current.exists() and not self.current.is_symlink():
                raise ValueError('静态缓存入口已被其他文件占用')
            stage = Path(tempfile.mkdtemp(prefix='snapshot-', dir=self.base))
            link = self.base / ('.current-' + uuid.uuid4().hex)
            published = False
            try:
                for relative, expected in inventory.items():
                    source = self.source / relative
                    destination = stage / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source.open('rb') as src, destination.open('wb') as dst:
                        if self._signature(os.fstat(src.fileno())) != expected:
                            raise OSError('网页源文件在同步期间发生变化')
                        shutil.copyfileobj(src, dst)
                        if self._signature(os.fstat(src.fileno())) != expected:
                            raise OSError('网页源文件在同步期间发生变化')
                self._validate_references(stage, inventory)
                if self._inventory() != inventory:
                    raise OSError('网页源目录在同步期间发生变化')
                os.symlink(stage.name, link)
                os.replace(link, self.current)
                published = True
                self._applied = inventory
                self._pending = None
            finally:
                link.unlink(missing_ok=True)
                if not published:
                    shutil.rmtree(stage, ignore_errors=True)
            try:
                self._cleanup(stage.name)
            except OSError as error:
                print(f'[web-cache] 旧快照清理失败：{type(error).__name__} errno={error.errno}', flush=True)
            return True

    @staticmethod
    def _validate_references(stage, inventory):
        for page in (p for p in inventory if p.suffix.lower() == '.html'):
            parser = _StaticReferences()
            parser.feed((stage / page).read_text(encoding='utf-8'))
            for url in parser.urls:
                parsed = urlsplit(url)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                path = unquote(parsed.path)
                if path.startswith(('/api/', '/cdn-cgi/')):
                    continue
                relative = Path(os.path.normpath(path.lstrip('/') if path.startswith('/') else str(page.parent / path)))
                if relative.is_absolute() or '..' in relative.parts or relative not in inventory:
                    raise ValueError('网页引用的静态资源不完整')

    def _cleanup(self, active):
        snapshots = sorted((p for p in self.base.glob('snapshot-*') if p.is_dir() and not p.is_symlink()),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        # Keep the previous generation and snapshots created in the last minute.
        for path in snapshots[2:]:
            if path.name != active and path.stat().st_mtime < time.time() - 60:
                shutil.rmtree(path, ignore_errors=True)

    def _report(self, error):
        kind = (type(error).__name__, getattr(error, 'errno', None))
        if kind != self._error:
            print(f'[web-cache] 同步失败：{kind[0]} errno={kind[1]}；保留上次完整页面', flush=True)
            self._error = kind

    def start(self):
        try:
            self.refresh(require_stable=self.usable())
        except (OSError, ValueError) as error:
            if not self.usable():
                raise
            self._report(error)

        def monitor():
            while not self._stop.wait(self.interval):
                try:
                    updated = self.refresh(require_stable=True)
                    if self._error and updated:
                        print('[web-cache] 源文件已恢复，页面同步继续', flush=True)
                        self._error = None
                except (OSError, ValueError) as error:
                    self._report(error)

        self._thread = threading.Thread(target=monitor, daemon=True)
        self._thread.start()
        return self.current

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
