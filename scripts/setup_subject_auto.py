"""Install the complete local subject pipeline; no photo uploads."""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photocluster.config import DATA

MODEL=DATA/'models/subject-routing.onnx'
REVISION='5ee62e06f5f4cd68a1c2f3bc5dc9805e827d37df'
SHA256='ea8f4497b0e3ee86f43b6a6fd38884e25f960979a1debb5c4e1ee6a22e80d111'
URL=f'https://huggingface.co/deepghs/anime_classification/resolve/{REVISION}/mobilenetv3_v1.5_dist/model.onnx'


def install_router(proxy='',progress=lambda count:None):
    MODEL.parent.mkdir(parents=True,exist_ok=True)
    if MODEL.exists():
        with MODEL.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()==SHA256:return
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':proxy,'https':proxy}) if proxy else urllib.request.ProxyHandler())
    temporary=MODEL.with_suffix('.download')
    try:
        digest=hashlib.sha256();count=0
        with opener.open(URL,timeout=45) as source,temporary.open('wb') as output:
            while chunk:=source.read(1024*1024):
                output.write(chunk);digest.update(chunk);count+=len(chunk);progress(count)
        if digest.hexdigest()!=SHA256:raise RuntimeError('Model checksum mismatch')
        import onnxruntime as ort
        ort.disable_telemetry_events()
        ort.InferenceSession(str(temporary),providers=['CPUExecutionProvider'])
        temporary.replace(MODEL)
        MODEL.with_suffix('.json').write_text(json.dumps(dict(source=URL,revision=REVISION,sha256=SHA256,license='MIT')),'utf-8')
    finally:temporary.unlink(missing_ok=True)


def install(proxy='',progress=lambda count:None):
    from scripts import setup_subject,setup_character
    completed=0
    for fn in (setup_subject.install,setup_character.install,install_router):
        current=0
        def report(count):
            nonlocal current
            current=count;progress(completed+count)
        fn(proxy,report)
        completed+=current


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--proxy',default='')
    install(parser.parse_args().proxy,lambda n:print(f'{n/1024**2:.1f} MB',flush=True))
