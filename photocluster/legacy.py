"""Explicit, verified migration of an idle legacy server; never force termination."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler

import psutil

from .client import inspect_service, port_available
from .config import ROOT, DATA


class MigrationError(RuntimeError):
    pass


def matches(process, port):
    """Only a plain, same-user, same-checkout Uvicorn process is eligible."""
    expected = ['-m', 'uvicorn', 'photocluster.app:app', '--host', '127.0.0.1', '--port', str(port)]
    try:
        args = process.cmdline()
        env = process.environ()
        cache = Path(env.get('PHOTOCLUSTER_DATA_DIR', str(ROOT / 'data'))).expanduser().resolve()
        return (args[1:] == expected and Path(args[0]).name.lower() in ('python', 'python3', 'python.exe', 'python3.11', 'python3.12', 'python3.13')
                and Path(process.cwd()).resolve() == ROOT.resolve()
                and process.username() == psutil.Process().username()
                and cache == DATA.resolve())
    except (psutil.Error, OSError):
        return False


def idle(base):
    opener = build_opener(ProxyHandler({}))
    try:
        for endpoint in ('status', 'sync-status'):
            with opener.open(base + '/api/' + endpoint, timeout=3) as response:
                data = json.load(response)
            if data.get('running') is not False:
                raise MigrationError('busy')
    except MigrationError:
        raise
    except (OSError, ValueError):
        raise MigrationError('unavailable') from None


def identify(port):
    base = f'http://127.0.0.1:{port}'
    info = inspect_service(base)
    if not info or info.get('application') != 'PhotoCluster' or info.get('managed'):
        raise MigrationError('identity')
    owners = {c.pid for c in psutil.net_connections('tcp')
              if c.status == psutil.CONN_LISTEN and c.laddr.port == port}
    if len(owners) != 1 or None in owners:
        raise MigrationError('identity')
    process = psutil.Process(owners.pop())
    if not matches(process, port):
        raise MigrationError('identity')
    idle(base)
    return process


def cooperative_stop(port):
    target = identify(port)
    created = target.create_time()
    base = f'http://127.0.0.1:{port}'
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        # Runs only in a disposable helper. Do not detach the user's GUI/terminal.
        kernel.FreeConsole()
        if not kernel.AttachConsole(target.pid):
            raise MigrationError('no_console')
        try:
            if not kernel.SetConsoleCtrlHandler(None, True):
                raise MigrationError('no_console')
            ids = (ctypes.c_uint32 * 128)()
            count = kernel.GetConsoleProcessList(ids, len(ids))
            allowed = {target.pid, os.getpid()}
            # Windows venv launchers may share their child's console.
            parent = target.parent()
            if parent and matches(parent, port):
                allowed.add(parent.pid)
            if not count or count > len(ids) or not set(ids[:count]) <= allowed:
                raise MigrationError('shared_console')
            # Refresh identity and activity immediately before the cooperative signal.
            if not matches(target, port) or target.create_time() != created:
                raise MigrationError('identity')
            idle(base)
            if not kernel.GenerateConsoleCtrlEvent(0, 0):
                raise MigrationError('no_console')
            time.sleep(.2)
        finally:
            kernel.FreeConsole()
    else:
        idle(base)
        if not matches(target, port) or target.create_time() != created:
            raise MigrationError('identity')
        target.send_signal(signal.SIGINT)
    # On POSIX a non-child may remain a zombie until its own parent reaps it.
    # That process has exited and cannot own the listening socket anymore.
    deadline = time.monotonic() + 30
    while True:
        try:
            if not target.is_running() or target.status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        if time.monotonic() >= deadline:
            raise MigrationError('timeout')
        time.sleep(.1)
    if not port_available(base):
        raise MigrationError('port_busy')


def migrate(port):
    """Called after explicit GUI confirmation; helper verifies everything again."""
    if not 1 <= int(port) <= 65535:
        raise MigrationError('identity')
    with tempfile.TemporaryDirectory(prefix='photocluster-migrate-') as folder:
        result = Path(folder) / 'result.json'
        python = sys.executable
        if os.name == 'nt' and python.lower().endswith('pythonw.exe'):
            python = str(Path(python).with_name('python.exe'))
        subprocess.run([python, '-m', 'photocluster.legacy', str(port), str(result)], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, timeout=55)
        if not result.exists():
            raise MigrationError('unavailable')
        data = json.loads(result.read_text('utf-8'))
        if not data.get('ok'):
            raise MigrationError(data.get('error', 'unavailable'))


if __name__ == '__main__':
    output = Path(sys.argv[2])
    try:
        cooperative_stop(int(sys.argv[1]))
        data = {'ok': True}
    except MigrationError as exc:
        data = {'ok': False, 'error': str(exc)}
    except Exception:
        data = {'ok': False, 'error': 'unavailable'}
    output.write_text(json.dumps(data), 'utf-8')
