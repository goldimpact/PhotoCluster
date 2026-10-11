"""Real isolated process lifecycle; never connects to or modifies a phone."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def test_managed_process_reuses_instance_locks_cache_and_exits(tmp_path):
    root=Path(__file__).resolve().parents[1];port=free_port()
    env=dict(os.environ,PHOTOCLUSTER_DATA_DIR=str(tmp_path),PHOTOCLUSTER_ACCELERATOR='cpu')
    args=[sys.executable,'-m','photocluster.server','--no-browser','--port',str(port)]
    opener=build_opener(ProxyHandler({}));url=f'http://127.0.0.1:{port}'
    process=subprocess.Popen(args,cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    snapshot=None
    try:
        for _ in range(120):
            try:
                with opener.open(url+'/api/runtime',timeout=.3) as response:snapshot=json.load(response)
                break
            except OSError:
                assert process.poll() is None,'Server exited before readiness'
                time.sleep(.1)
        assert snapshot and snapshot['managed']
        duplicate=subprocess.run(args,cwd=root,env=env,capture_output=True,timeout=15)
        assert duplicate.returncode==0 and b'already running' in duplicate.stdout
        other=subprocess.run(args[:-1]+[str(free_port())],cwd=root,env=env,capture_output=True,timeout=15)
        assert other.returncode!=0 and b'cache is already used' in other.stderr
        with opener.open(Request(url+'/api/runtime/exit',data=b'',headers={'X-PhotoCluster-Token':snapshot['token']}),timeout=5) as response:
            assert json.load(response)['stopping']
        assert process.wait(timeout=15)==0
    finally:
        if process.poll() is None:
            # Only our synthetic test process, never a discovered user service.
            process.terminate();process.wait(timeout=15)
