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
