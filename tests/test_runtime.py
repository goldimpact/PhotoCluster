import asyncio
import importlib
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
from photocluster.runtime import Runtime
from photocluster.server import watch
from photocluster.service import Service


def test_exit_requires_token_and_origin_and_rejects_new_work(tmp_path,monkeypatch):
    module=importlib.import_module('photocluster.app')
    runtime=Runtime(managed=True)
    monkeypatch.setattr(module.app.state,'runtime',runtime)
    monkeypatch.setattr(module,'service',Service(tmp_path))
    with TestClient(module.app) as client:
        assert client.get('/api/runtime').json()['managed']
        assert client.post('/api/runtime/exit').status_code==403
        assert client.post('/api/runtime/exit',headers={'X-PhotoCluster-Token':runtime.token,'Origin':'https://outside.example'}).status_code==403
        assert not runtime.stopping
        assert client.post('/api/runtime/exit',headers={'X-PhotoCluster-Token':runtime.token}).status_code==200
        assert module.service.cancel.is_set()
        assert client.get('/api/runtime').json()['stopping']
        assert client.post('/api/scan',json={'albums':[]}).status_code==503
        assert client.post('/api/operations/execute',json={'token':'fake'}).status_code==503
    assert runtime.active==0


def test_external_server_cannot_be_stopped_by_page(monkeypatch):
    module=importlib.import_module('photocluster.app');runtime=Runtime()
    monkeypatch.setattr(module.app.state,'runtime',runtime)
    with TestClient(module.app) as client:
        assert client.post('/api/runtime/exit',headers={'X-PhotoCluster-Token':runtime.token}).status_code==409
    assert not runtime.stopping


def test_shutdown_waits_for_scan_thread_and_entire_active_response():
    async def scenario():
        runtime=Runtime(managed=True);runtime.request_exit();runtime.active=1
        worker=SimpleNamespace(is_alive=lambda:True)
        service=SimpleNamespace(cancel=threading.Event(),status={'running':True},sync_status={'running':False},scan_thread=worker)
        server=SimpleNamespace(should_exit=False,started=True)
        module=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=runtime)),service=service)
        task=asyncio.create_task(watch(server,module,False,'http://127.0.0.1:9999'))
        await asyncio.sleep(.18)
        assert service.cancel.is_set() and not server.should_exit
        service.status['running']=False;runtime.active=0
        await asyncio.sleep(.18);assert not server.should_exit
        worker.is_alive=lambda:False
        await asyncio.wait_for(task,1)
        assert server.should_exit
    asyncio.run(scenario())
