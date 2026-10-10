"""Download the public CLIP image encoder. Photos never leave this computer."""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REVISION='d15189d7028b43f1d3e65039190477f6af591c2a'
SHA256='583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--proxy',default='');args=parser.parse_args()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':args.proxy,'https':args.proxy}) if args.proxy else urllib.request.ProxyHandler())
    revision=REVISION;folder=ROOT/'data/models';folder.mkdir(parents=True,exist_ok=True)
    target=folder/'clip-vision-int8.onnx';temp=target.with_suffix('.download')
    url=f'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/{revision}/onnx/vision_model_quantized.onnx'
    digest=hashlib.sha256();count=0
    with opener.open(url,timeout=60) as source,temp.open('wb') as output:
        while chunk:=source.read(1024*1024):
            output.write(chunk);digest.update(chunk);count+=len(chunk)
            if count%(10*1024*1024)==0:print(f'{count//1024**2} MB',flush=True)
    if digest.hexdigest()!=SHA256:
        temp.unlink(missing_ok=True)
        raise RuntimeError('Model checksum mismatch; the existing model was not replaced.')
    import onnxruntime as ort
    ort.disable_telemetry_events()
    ort.InferenceSession(str(temp),providers=['CPUExecutionProvider'])
    temp.replace(target)
    metadata=dict(model='Xenova/clip-vit-base-patch32',revision=revision,sha256=digest.hexdigest(),bytes=count,source=url)
    (folder/'clip-vision.json').write_text(json.dumps(metadata,indent=2),'utf-8')
    print(json.dumps(metadata),flush=True)
if __name__=='__main__':main()
