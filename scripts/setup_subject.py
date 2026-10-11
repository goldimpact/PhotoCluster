"""Install a pinned local DINOv2 encoder; no media is sent over the network."""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from photocluster.config import DATA

MODEL = DATA / 'models/dinov2-small-int8.onnx'
REVISION = 'c2bb04a51fab207c420665f1946016107bffc701'
SHA256 = '3afdc8bc63b50558d6e5770f5b799bb82455c2311183a2de43803f343a29d917'
URL = f'https://huggingface.co/Xenova/dinov2-small/resolve/{REVISION}/onnx/model_quantized.onnx'


def install(proxy='', progress=lambda count: None):
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if MODEL.exists():
        with MODEL.open('rb') as f:
            if hashlib.file_digest(f, 'sha256').hexdigest() == SHA256:
                return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}) if proxy else urllib.request.ProxyHandler())
    temporary = MODEL.with_suffix('.download')
    try:
        digest = hashlib.sha256(); count = 0
        with opener.open(URL, timeout=45) as source, temporary.open('wb') as output:
            while chunk := source.read(1024*1024):
                output.write(chunk); digest.update(chunk); count += len(chunk); progress(count)
        if digest.hexdigest() != SHA256:
            raise RuntimeError('Model checksum mismatch')
        import onnxruntime as ort
        ort.disable_telemetry_events()
        ort.InferenceSession(str(temporary), providers=['CPUExecutionProvider'])
        temporary.replace(MODEL)
        MODEL.with_suffix('.json').write_text(json.dumps(dict(source=URL, revision=REVISION, sha256=SHA256)), 'utf-8')
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--proxy', default='')
    install(parser.parse_args().proxy, lambda n: print(f'{n/1024**2:.1f} MB', flush=True))
    print('Subject model ready. Analysis stays local.')
