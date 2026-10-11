"""Explicit, allowlisted local cache cleanup. Never traverse phone or model paths."""
import re
import secrets
import stat
import time
from contextlib import closing


FILES = {
    'results': ('groups.json', 'match-cache.json'),
    'analysis': ('geometry-pairs.sqlite3', 'geometry-pairs.sqlite3-wal', 'geometry-pairs.sqlite3-shm',
                 'catalog.sqlite3', 'catalog.sqlite3-wal', 'catalog.sqlite3-shm'),
    'library': ('catalog.json', 'errors.json'),
}


def _regular(path, root):
    # Check lexical ancestors as well as the resolved target (Windows junctions too).
    for part in (path, *path.parents):
        if part == root:
            break
        try:
            info = part.lstat()
        except FileNotFoundError:
            return False  # SQLite WAL files can disappear after a checkpoint.
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('缓存目录包含链接，已拒绝清理')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('缓存路径不在当前实例目录内')
    return path.is_file()


def inventory(service):
    root = service.data.absolute()
    paths = {name: [] for name in ('results', 'analysis', 'library', 'models')}
    for kind, names in FILES.items():
        for name in names:
            p = root / name
            if p.exists() and _regular(p, root):
                paths[kind].append(p)
    for folder, kind in (('matches', 'results'), ('thumbnails', 'analysis'), ('models', 'models')):
        directory = root / folder
        if directory.exists():
            _regular(directory, root)
            # Cache directories are flat. Unknown/nested content is not deleted.
            for p in directory.iterdir():
                known = (folder=='models' or
                         folder=='matches' and re.fullmatch(r'[a-f0-9]{64}\.json',p.name) or
                         folder=='thumbnails' and (re.fullmatch(r'[a-f0-9]{64}\.(?:jpg|npz|frames\.npz|variants\.npz|clip\.npz)',p.name) or
                         re.fullmatch(r'(?:embeddings|subjects|characters|subject-routing)\.sqlite3(?:-wal|-shm)?',p.name)))
                if known and _regular(p, root):
                    paths[kind].append(p)
    return paths


def summary(service):
    with service.lock:
        paths = inventory(service)
        def size(p):
            try:return p.stat().st_size
            except FileNotFoundError:return 0
        return dict(categories={kind: dict(files=sum(1 for p in items if p.exists()), bytes=sum(size(p) for p in items))
                                for kind, items in paths.items()},
                    busy=bool(service.status['running'] or service.sync_status['running']),
                    location=str(service.data.resolve()))


class CacheManager:
    def __init__(self, service, operations):
        self.service, self.operations = service, operations
        self.plans = {}

    def _idle(self):
        if self.service.status['running'] or self.service.sync_status['running']:
            raise ValueError('请等待扫描或同步结束后再清理缓存')

    def preview(self, scope):
        if scope not in ('results', 'analysis', 'all'):
            raise ValueError('未知缓存清理范围')
        with self.service.lock:
            self._idle()
            usage = summary(self.service)
            kinds = ['results'] + (['analysis'] if scope != 'results' else []) + (['library'] if scope == 'all' else [])
            token = secrets.token_urlsafe(32)
            self.plans = {token: (scope, time.monotonic())}
            return dict(token=token, scope=scope, bytes=sum(usage['categories'][k]['bytes'] for k in kinds),
                        files=sum(usage['categories'][k]['files'] for k in kinds))

    def execute(self, token):
        s = self.service
        with s.lock:
            self._idle()
            plan = self.plans.pop(token, None)
            if not plan or time.monotonic()-plan[1] > 300:
                raise ValueError('缓存清理预览已过期，请重新选择')
            scope = plan[0]
            paths = inventory(s)  # Preflight ALL targets before changing anything.
            targets = paths['results'] + (paths['analysis'] if scope != 'results' else [])
            if scope == 'all':
                targets += paths['library']
            # Keep the live SQLite database; clear rows and compact through SQLite.
            targets = [p for p in targets if not p.name.startswith('catalog.sqlite3')]
            self.operations.plans.clear()
            s.result = {'groups': [], 'summary': None}
            s.save('groups.json', s.result)
            failures = 0
            for p in targets:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    failures += 1
            if scope != 'results':
                with closing(s.connect()) as con, con:
                    con.execute('DELETE FROM features'); con.execute('DELETE FROM skipped')
                    con.commit(); con.execute('VACUUM')
                from . import vision, variants
                for fn in (vision.local_features, vision.comparison_image, vision.comparison_statistics,
                           variants.load, variants.frame_image, variants.target_statistics):
                    fn.cache_clear()
                s.save('errors.json', [])
            if scope == 'all':
                s.catalog = {'serial': None, 'photos': []}
                s.save('catalog.json', s.catalog)
            s.save('groups.json', s.result)
            s.update(phase='idle', message='缓存已清理，请重新分类', done=0, total=0, errors=0)
            return dict(failed=failures, usage=summary(s))
