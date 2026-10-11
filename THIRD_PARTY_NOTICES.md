# Third-party components

PhotoCluster's own code uses the [MIT license](LICENSE). Dependencies, tools and
model weights retain their own licenses; they are not relicensed by this project.
No ADB/FFmpeg executable or model weight is distributed in this repository.

| Component | Purpose | Upstream license / source |
| --- | --- | --- |
| FastAPI, Uvicorn, HTTPX, pytest | Local API and tests | MIT / BSD licenses; see each installed package |
| NumPy, SciPy, Pillow, threadpoolctl, psutil | Local media computation | BSD / HPND-style licenses; see package distributions |
| OpenCV | Features and geometry | Apache-2.0; bundled dependencies have separate notices |
| pillow-heif / libheif | HEIF decoding | BSD-3-Clause / LGPL-3.0; codec dependencies may differ |
| ONNX Runtime | Local model inference | MIT and included third-party notices |
| CuPy (optional) | CUDA acceleration | MIT; NVIDIA runtime terms also apply |
| Android Platform Tools / ADB | USB device access | Obtain from [Google](https://developer.android.com/tools/releases/platform-tools); distribution has its own terms |
| FFmpeg / FFprobe | Video and damaged-media decoding | [LGPL/GPL depending on build](https://ffmpeg.org/legal.html), and codec-specific terms |
| acorn, jsdom (development only) | JavaScript parsing and DOM tests | MIT and their transitive dependency notices |

The optional semantic model is the quantized ONNX image encoder from
[Xenova/clip-vit-base-patch32](https://huggingface.co/Xenova/clip-vit-base-patch32),
derived from [OpenAI CLIP](https://github.com/openai/CLIP) (MIT).
Review the model card and upstream license before redistributing weights or using
the model in another product. Model outputs are heuristic similarity suggestions.

The installer pins the model revision and checks its SHA-256 before loading it.
Its public source, revision and hash are recorded locally in
`data/models/clip-vision.json`. Weights are excluded from Git. Dependency installation
and explicit model download require network access; classification does not upload
media or call a hosted model.

The optional automatic subject mode uses quantized ONNX weights from
[Xenova/dinov2-small](https://huggingface.co/Xenova/dinov2-small), derived from
[facebook/dinov2-small](https://huggingface.co/facebook/dinov2-small) and
[DINOv2](https://github.com/facebookresearch/dinov2) (Apache-2.0).
`scripts/setup_subject.py` pins revision `c2bb04a51fab207c420665f1946016107bffc701`
and verifies SHA-256 before loading. Weights and download metadata remain in the
ignored local model directory. This general visual encoder is not a specialized
character identity classifier; the subject grouping mode is experimental.

The optional anime character engine uses
[deepghs/ccip_onnx](https://huggingface.co/deepghs/ccip_onnx),
`ccip-caformer-24-randaug-pruned`, derived from [CCIP](https://huggingface.co/deepghs/ccip).
Upstream declares **OpenRAIL**, not MIT or Apache-2.0. Model terms remain separate
from PhotoCluster's MIT code license; consult the upstream card before redistributing
weights. The public repository does not bundle model weights or evaluation images.
`setup_character.py` pins revision `eb2acdd29af1703388d3d0c04221add322bc9110` and
checks SHA-256 `4ea118d16496274f4f6e08d3afc768cc592389e8f7f32f8732ce2215c228ac5f`.
CCIP targets **single-character anime images**, not all objects or group scenes.
Preprocessing and distance semantics follow the upstream documentation; no
`imgutils`, PyTorch or remote inference dependency is added.
