"""Managed local server: browser startup, duplicate detection and graceful exit."""
import argparse
import asyncio
import json
import webbrowser
from contextlib import contextmanager
from urllib.request import build_opener, ProxyHandler

from .config import DATA
from .runtime import Runtime, workspace_id
from .client import port_available


@contextmanager
def cache_lock():
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / 'service.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        import os
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('This cache is already used by a running PhotoCluster. Open that instance or choose another data directory.') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def existing(port):
    url = f'http://127.0.0.1:{port}'
    if port_available(url):
        return False
    else:
        try:
            with build_opener(ProxyHandler({})).open(url + '/api/runtime', timeout=2) as response:
                data = json.load(response)
            if data.get('application') == 'PhotoCluster' and data.get('workspace') == workspace_id() and not data.get('stopping'):
                return True
        except (OSError, ValueError):
            pass
        raise RuntimeError(f'Port {port} is occupied by another service or an older instance. Close it or choose --port with a different value.') from None


async def watch(server, module, open_browser, url):
    opened = False
    while not server.should_exit:
        state = module.app.state.runtime
        if server.started and not opened:
            opened = True
            print(f'PhotoCluster is running: {url}\nClose using Exit PhotoCluster in the page, or Ctrl+C here. Closing a browser tab does not stop it.', flush=True)
            if open_browser:
                await asyncio.to_thread(webbrowser.open, url)
        if state.stopping:
            # Repeat cancellation: a previously admitted request may start its scan late.
            module.service.cancel.set()
            worker = getattr(module.service, 'scan_thread', None)
            with state.lock:
                ready = state.active == 0
            if ready and not module.service.status['running'] and not module.service.sync_status['running'] and not (worker and worker.is_alive()):
                server.should_exit = True
                return
        await asyncio.sleep(.15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Invalid port')
    url = f'http://127.0.0.1:{args.port}'
    if existing(args.port):
        print(f'PhotoCluster is already running: {url}', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return
    with cache_lock():
        import uvicorn
        from . import app as module
        module.app.state.runtime = Runtime(managed=True)

        class Server(uvicorn.Server):
            def handle_exit(self, sig, frame):
                module.app.state.runtime.request_exit()
                print('Finishing current work and saving caches. Please wait…', flush=True)

        server = Server(uvicorn.Config(module.app, host=args.host, port=args.port))

        async def serve():
            task = asyncio.create_task(watch(server, module, not args.no_browser, url))
            try:
                await server.serve()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(serve())
        print('PhotoCluster has stopped. You can close this window.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
