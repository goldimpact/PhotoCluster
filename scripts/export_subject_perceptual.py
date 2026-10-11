"""Build an optional local ONNX DreamSim encoder from audited local resources.

Run in an isolated export environment (torch, dreamsim==0.2.1, peft==0.17.1,
onnx, onnxruntime). Provide an official DreamSim DINOv2 checkpoint directory and
a local checkout of facebookresearch/dinov2. Does not download resources or read
media. The normal app needs only ONNX Runtime, not these build dependencies.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

FILES = {
    'dinov2_vitb14_pretrain.pth': '0b8b82f85de91b424aded121c7e1dcc2b7bc6d0adeea651bf73a13307fad8c73',
    'dinov2_vitb14_single_lora/adapter_model.safetensors': '65647818a0474f341fdb6122ae45b7505358b91b671384a8faaf25ed22b6dba0',
    'dinov2_vitb14_single_lora/adapter_config.json': '5bc562f11bd9d0984f8fc7e4aa72ed024b51b864b53005da65f65c6d591dc838',
}
DINO_REVISION = '7764ea0f912e53c92e82eb78a2a1631e92725fc8'
SOURCE = 'https://github.com/ssundaram21/dreamsim/releases/download/v0.2.1-checkpoints/dreamsim_dinov2_vitb14_checkpoint.zip'


def export(weights, dino_source, output):
    weights, dino_source, output = map(lambda p: Path(p).resolve(), (weights, dino_source, output))
    for name, digest in FILES.items():
        with (weights/name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('Unexpected checkpoint hash: '+name)
    if not (dino_source/'dinov2/hub/backbones.py').is_file():
        raise ValueError('Provide an audited local DINOv2 source checkout')
    sys.path.insert(0, str(dino_source))
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    def deny(*args, **kwargs):raise RuntimeError('Export does not allow network access')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    import numpy as np
    import torch
    import onnxruntime as ort
    from dreamsim import dreamsim
    from dreamsim.feature_extraction.extractor import ViTExtractor
    from dinov2.hub.backbones import dinov2_vitb14

    def local_model(model_type, load_dir):
        if model_type != 'dinov2_vitb14':raise ValueError('Unexpected model')
        model = dinov2_vitb14(pretrained=False)
        model.load_state_dict(torch.load(weights/'dinov2_vitb14_pretrain.pth', map_location='cpu', weights_only=True), strict=True)
        return model
    ViTExtractor.create_model = staticmethod(local_model)
    torch.set_num_threads(8)
    original, _ = dreamsim(pretrained=True, device='cpu', cache_dir=str(weights), dreamsim_type='dinov2_vitb14')
    merged = original.merge_and_unload()

    class Encoder(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.backbone = merged.extractor_list[0].model
        def forward(self, pixels):
            mean = pixels.new_tensor([.485,.456,.406])[None,:,None,None]
            std = pixels.new_tensor([.229,.224,.225])[None,:,None,None]
            value = self.backbone.forward_features((pixels-mean)/std)['x_prenorm'][:,0]
            return torch.nn.functional.normalize(value-value.mean(-1,keepdim=True),dim=-1)
    encoder = Encoder().eval()
    torch.manual_seed(17); batch = torch.rand(4,3,224,224)
    with torch.inference_mode():expected = merged.embed(batch).numpy()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.export.onnx')
    try:
        torch.onnx.export(encoder, batch[:1], str(temporary), input_names=['pixels'], output_names=['embedding'],
                          dynamic_axes={'pixels':{0:'batch'},'embedding':{0:'batch'}}, opset_version=17, dynamo=False)
        ort.disable_telemetry_events(); options=ort.SessionOptions(); options.intra_op_num_threads=4
        runner = ort.InferenceSession(str(temporary), sess_options=options, providers=['CPUExecutionProvider'])
        actual = runner.run(None, {'pixels':batch.numpy()})[0]
        error = float(np.abs(expected-actual).max())
        if not np.allclose(expected, actual, atol=1e-4):raise ValueError('Export parity check failed')
        del runner
        with temporary.open('rb') as stream:digest = hashlib.file_digest(stream,'sha256').hexdigest()
        temporary.replace(output)
        output.with_suffix('.json').write_text(json.dumps(dict(source=SOURCE, input_sha256=FILES,
            recommended_dino_revision=DINO_REVISION, sha256=digest, synthetic_max_error=error,
            license='DreamSim MIT; DINOv2 Apache-2.0', feature='prenorm CLS, channel-center, L2, RGB bicubic224'),indent=2),'utf-8')
    finally:
        temporary.unlink(missing_ok=True)
    print('Export verified. Synthetic max error:', error)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights',required=True)
    parser.add_argument('--dino-source',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(); export(args.weights,args.dino_source,args.output)
