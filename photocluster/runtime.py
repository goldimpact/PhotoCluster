"""Process-local lifecycle control; no PID killing and no phone mutations."""
import hashlib
import secrets
import threading

from .config import DATA, ROOT


def workspace_id():
    return hashlib.sha256((str(ROOT.resolve()) + '\0' + str(DATA.resolve())).encode()).hexdigest()


class Runtime:
    def __init__(self, managed=False):
        self.managed = managed
        self.token = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(16)
        self.lock = threading.Lock()
        self.stopping = False
        self.active = 0

    def snapshot(self):
        with self.lock:
            return dict(application='PhotoCluster', workspace=workspace_id(), instance=self.instance,
                        managed=self.managed, stopping=self.stopping, token=self.token)

    def request_exit(self):
        with self.lock:
            if not self.managed:
                raise ValueError('This instance is managed by an external command.')
            self.stopping = True

    def admit(self, path):
        with self.lock:
            if self.stopping and not path.startswith(('/api/runtime', '/api/video-release/')):
                return False
            self.active += 1
            return True

    def finished(self):
        with self.lock:
            self.active -= 1


class AdmissionMiddleware:
    """Count entire responses, including streaming bodies, before shutting down."""
    def __init__(self, app, owner):
        self.app, self.owner = app, owner

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        runtime = self.owner.state.runtime
        if not runtime.admit(scope['path']):
            from starlette.responses import JSONResponse
            return await JSONResponse({'detail': 'PhotoCluster is shutting down.'}, status_code=503)(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            runtime.finished()
