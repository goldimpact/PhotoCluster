import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.request import build_opener, ProxyHandler

import pytest

from photocluster import legacy
from photocluster.client import port_available


def test_identity_checks_workspace_command_user_and_cache(monkeypatch,tmp_path):
    monkeypatch.setattr(legacy,'ROOT',tmp_path)
    monkeypatch.setattr(legacy,'DATA',tmp_path/'data')
    user=legacy.psutil.Process().username()
    args=['python','-m','uvicorn','photocluster.app:app','--host','127.0.0.1','--port','8765']
    env={};cwd=tmp_path
    proc=SimpleNamespace(cmdline=lambda:args,environ=lambda:env,cwd=lambda:str(cwd),username=lambda:user)
    assert legacy.matches(proc,8765)
    args.append('--reload');assert not legacy.matches(proc,8765);args.pop()
    cwd=tmp_path/'other';assert not legacy.matches(proc,8765);cwd=tmp_path
    env['PHOTOCLUSTER_DATA_DIR']=str(tmp_path/'other');assert not legacy.matches(proc,8765)


def test_busy_legacy_is_not_signalled(monkeypatch):
    monkeypatch.setattr(legacy,'inspect_service',lambda base:{'application':'PhotoCluster','legacy':True})
    monkeypatch.setattr(legacy.psutil,'net_connections',lambda *args:[SimpleNamespace(pid=123,status='LISTEN',laddr=SimpleNamespace(port=8765))])
    monkeypatch.setattr(legacy.psutil,'Process',lambda pid:SimpleNamespace())
    monkeypatch.setattr(legacy,'matches',lambda *args:True)
    monkeypatch.setattr(legacy,'idle',lambda base:(_ for _ in ()).throw(legacy.MigrationError('busy')))
    with pytest.raises(legacy.MigrationError,match='busy'):legacy.cooperative_stop(8765)


def test_real_idle_uvicorn_can_migrate_without_force(tmp_path):
    root=Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=dict(os.environ,PHOTOCLUSTER_DATA_DIR=str(tmp_path),PHOTOCLUSTER_ACCELERATOR='cpu')
    kwargs={}
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        kwargs=dict(creationflags=subprocess.CREATE_NEW_CONSOLE,startupinfo=startup)
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','photocluster.app:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**kwargs)
    base=f'http://127.0.0.1:{port}';opener=build_opener(ProxyHandler({}))
    try:
        for _ in range(120):
            try:
                with opener.open(base+'/api/runtime',timeout=.3) as r:assert not json.load(r)['managed']
                break
            except OSError:
                assert proc.poll() is None
                time.sleep(.1)
        else:pytest.fail('Test server did not start')
        result=tmp_path/'migration.json'
        helper=subprocess.run([sys.executable,'-m','photocluster.legacy',str(port),str(result)],cwd=root,env=env,
                              capture_output=True,timeout=50)
        assert result.exists(),helper.stderr.decode(errors='replace')
        assert json.loads(result.read_text())=={'ok':True}
        proc.wait(timeout=10)
        assert port_available(base)
    finally:
        if proc.poll() is None:
            # Only our isolated synthetic server, never a discovered user service.
            proc.terminate();proc.wait(timeout=10)
