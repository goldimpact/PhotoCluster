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

Automatic subject routing also uses the MIT-licensed
[deepghs/anime_classification](https://huggingface.co/deepghs/anime_classification)
`mobilenetv3_v1.5_dist` model. The pinned revision is
`5ee62e06f5f4cd68a1c2f3bc5dc9805e827d37df` and SHA-256 is
`ea8f4497b0e3ee86f43b6a6fd38884e25f960979a1debb5c4e1ee6a22e80d111`.
Its image-style output only enables supplemental evidence. It does not establish
subject identity, single-character presence, or guaranteed model applicability.

Optional perceptual candidate verification uses the DINOv2-B/14 single-branch
checkpoint from [DreamSim](https://github.com/ssundaram21/dreamsim) (MIT), with
[DINOv2](https://github.com/facebookresearch/dinov2) (Apache-2.0) as its backbone.
The local export tool verifies checkpoint SHA-256 values and numerical parity.
No upstream source or weights are bundled. PyTorch, torchvision, DreamSim, PEFT
and ONNX are optional export dependencies, not runtime requirements. Standard
runtime inference uses ONNX Runtime. Perceptual scores are not identity probabilities.
## Optional complementary subject encoder

SigLIP 2 Base (`google/siglip2-base-patch16-224`) is published under Apache-2.0.
The optional ONNX conversion is from `onnx-community/siglip2-base-patch16-224-ONNX`,
revision `ba1f3b0843f24bc5417d38e19c37b287d719b2f4`, `vision_model_quantized.onnx`.
SHA-256: `5f2b401c1a4fc095702a5d45348e17ad46c4f87064085365b43c6e8eaa5c0070`.
Weights are downloaded separately and are not included in this repository.
The upstream model card is https://huggingface.co/google/siglip2-base-patch16-224
and the paper is https://arxiv.org/abs/2502.14786.
This is a visual semantic encoder, not a validated universal identity recognizer.

## Optional larger character refinement encoder

`deepghs/ccip_onnx/ccip-caformer_b36-24/model_feat.onnx` derives from CCIP and is
published under OpenRAIL, separately from this project's MIT license. The installer
pins revision `eb2acdd29af1703388d3d0c04221add322bc9110` and SHA-256
`c1e7333a55c2ad9e03cd340c635e96c9c1d86f0836fa7eae65720e7c9c94ee51`.
Review https://huggingface.co/deepghs/ccip and https://huggingface.co/deepghs/ccip_onnx
before redistributing model weights. Weights are optional and not bundled.
This character encoder is not a general identity recognition guarantee.

## Optional supplemental domain classifier

[`deepghs/anime_real_cls`](https://huggingface.co/deepghs/anime_real_cls),
`mobilenetv3_v1.4_dist/model.onnx`, is published under OpenRAIL, separately from
the project's MIT license. Revision: `097a6c1e9e62866a435810c883a45a7cb2c7077d`.
SHA-256: `c02d68cc7f56dbcbcd4f41a10df190385c1f963f22c4eefb8d162869800ed3b0`.
Weights are optional, downloaded separately and not bundled. Its anime/real
labels describe an image domain; they do not establish subject identity or
single-character presence. Review the upstream license before redistribution.

## Optional local context detector

[`deepghs/anime_face_detection`](https://huggingface.co/deepghs/anime_face_detection)
lists MIT for `face_detect_v1.4_n/model.onnx`. Pinned revision:
`784dc4c0bb692351ddcdbe6131a050b17d3025d5`; SHA-256:
`fd860b650a4377046842c3cd80d01b0b408bdfbdb4acee5759630f82c6ef04a9`.
The installer downloads weights separately; no model or upstream implementation
is bundled. The model card describes a YOLOv8-based anime face detector. Review
upstream provenance and license terms before redistributing weights. A detected
face is a localization cue, not subject identity; other encoders retain their
own licenses, including CCIP's OpenRAIL terms.

## Optional additional identity encoder

`deepghs/ccip_onnx/ccip-v2-caformer_s36-10/model_feat.onnx` is published under
OpenRAIL, separately from the project's MIT license. Revision:
`eb2acdd29af1703388d3d0c04221add322bc9110`; SHA-256:
`484ad463f569ab95308cf47e91ba358b01c40bc53289b90b950b94fcde7f2628`.
Weights are optional and not bundled. Review the upstream CCIP/CCIP ONNX model
cards and license before redistributing weights. Joint agreement among identity
encoders does not establish a universal or independently calibrated accuracy.
