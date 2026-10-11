"""Pinned optional CCIP character encoder; model weights use upstream OpenRAIL."""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photocluster.config import DATA

MODEL=DATA/'models/ccip-caformer-24.onnx'
REVISION='eb2acdd29af1703388d3d0c04221add322bc9110'
SHA256='4ea118d16496274f4f6e08d3afc768cc592389e8f7f32f8732ce2215c228ac5f'
URL=f'https://huggingface.co/deepghs/ccip_onnx/resolve/{REVISION}/ccip-caformer-24-randaug-pruned/model_feat.onnx'


def install(proxy='',progress=lambda count:None):
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
        MODEL.with_suffix('.json').write_text(json.dumps(dict(source=URL,revision=REVISION,sha256=SHA256,license='OpenRAIL (upstream model card)')),'utf-8')
    finally:temporary.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--proxy',default='')
    install(parser.parse_args().proxy,lambda n:print(f'{n/1024**2:.1f} MB',flush=True))
