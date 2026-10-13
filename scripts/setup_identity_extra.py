"""Optional additional CCIP v2 ONNX download. No media access or uploads."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photocluster.identity_extra import MODEL

REVISION='eb2acdd29af1703388d3d0c04221add322bc9110'
SHA256='484ad463f569ab95308cf47e91ba358b01c40bc53289b90b950b94fcde7f2628'
URL=f'https://huggingface.co/deepghs/ccip_onnx/resolve/{REVISION}/ccip-v2-caformer_s36-10/model_feat.onnx'


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
        if 'output' not in {x.name for x in model.get_outputs()}:raise ValueError('Invalid extra identity output')
        del model
        temporary.replace(MODEL)
        MODEL.with_suffix('.json').write_text(json.dumps(dict(source=URL,revision=REVISION,sha256=SHA256,
            license='OpenRAIL',base_model='deepghs/ccip')),'utf-8')
    finally:temporary.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--proxy',default='')
    install(parser.parse_args().proxy,lambda n:print(f'{n/1024**2:.1f} MB',flush=True))
