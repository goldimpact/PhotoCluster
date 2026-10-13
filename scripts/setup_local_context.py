"""Optional local context detector download. No media access or uploads."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photocluster.local_context import MODEL

REVISION='784dc4c0bb692351ddcdbe6131a050b17d3025d5'
SHA256='fd860b650a4377046842c3cd80d01b0b408bdfbdb4acee5759630f82c6ef04a9'
URL=f'https://huggingface.co/deepghs/anime_face_detection/resolve/{REVISION}/face_detect_v1.4_n/model.onnx'


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
        if 'output0' not in {x.name for x in model.get_outputs()}:raise ValueError('Invalid local context output')
        del model
        temporary.replace(MODEL)
        MODEL.with_suffix('.json').write_text(json.dumps(dict(source=URL,revision=REVISION,sha256=SHA256,
            license='MIT',base_model='deepghs/anime_face_detection')),'utf-8')
    finally:temporary.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--proxy',default='')
    install(parser.parse_args().proxy,lambda n:print(f'{n/1024**2:.1f} MB',flush=True))
