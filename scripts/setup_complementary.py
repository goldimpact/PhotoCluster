"""Optional public SigLIP 2 ONNX download. No media access or uploads."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photocluster.complementary import MODEL

REVISION='ba1f3b0843f24bc5417d38e19c37b287d719b2f4'
SHA256='5f2b401c1a4fc095702a5d45348e17ad46c4f87064085365b43c6e8eaa5c0070'
URL=f'https://huggingface.co/onnx-community/siglip2-base-patch16-224-ONNX/resolve/{REVISION}/onnx/vision_model_quantized.onnx'


def install(proxy='',progress=lambda count:None):
    MODEL.parent.mkdir(parents=True,exist_ok=True)
    if MODEL.exists():
        with MODEL.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()==SHA256:return
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':proxy,'https':proxy}) if proxy else urllib.request.ProxyHandler())
    temporary=MODEL.with_suffix('.download')
    try:
        digest=hashlib.sha256();count=0
        with opener.open(URL,timeout=45) as source,temporary.open('wb') as target:
            while chunk:=source.read(1024*1024):
                target.write(chunk);digest.update(chunk);count+=len(chunk);progress(count)
        if digest.hexdigest()!=SHA256:raise RuntimeError('Model checksum mismatch')
        import onnxruntime as ort
        ort.disable_telemetry_events()
        model=ort.InferenceSession(str(temporary),providers=['CPUExecutionProvider'])
        if 'pooler_output' not in {x.name for x in model.get_outputs()}:raise ValueError('Invalid complementary model output')
        del model
        temporary.replace(MODEL)
        MODEL.with_suffix('.json').write_text(json.dumps(dict(source=URL,revision=REVISION,sha256=SHA256,
            license='Apache-2.0',base_model='google/siglip2-base-patch16-224')),'utf-8')
    finally:temporary.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--proxy',default='')
    install(parser.parse_args().proxy,lambda n:print(f'{n/1024**2:.1f} MB',flush=True))
