# PhotoCluster

**English** | [简体中文](README.zh-CN.md)

Find duplicate and similar **images, GIFs and videos** on an Android phone from
your computer. Review results in virtual folders, view originals, and choose which
phone files to delete or move. All analysis runs locally.

**Current focus:** Windows and Linux desktop hosts with Android over ADB.
See the [Linux / WSL guide](docs/LINUX.md) for setup and verification boundaries.
**macOS and iOS are deferred; iOS access is not implemented.**

## How it works

If your phone has `a/1.jpg` and `b/2.gif`, they can appear together in a virtual
group. Classification leaves both files at their original paths. Deleting a selected
file deletes that specific original on the phone; moving requires an existing real
phone folder. You cannot add files to virtual groups.

- Same-source variants: rotation, mirroring, scaling, stretching, local overlays,
  optional perspective and mild warp correction. Warp correction is expensive and
  off by default.
- Semantic similarity: an optional local CLIP model groups related scenes across
  images, animation frames and video keyframes. It compares whole-image appearance;
  it does not reliably identify one character across fan art, redrawings and memes.
  A broader threshold may mix different subjects rather than resolve their identity.
- Fast, enhanced and relaxed near-duplicate modes for comparing copies.
- **Automatic subjects (experimental):** a separate local DINOv2 encoder compares
  whole images and overlapping regions, without selecting examples. It works on
  images, GIFs and sampled video frames; character identities across radically
  different fan art remain unvalidated. Choose this mode and use **Install / check
  subject model** to download its pinned model (about 24 MB). Classification stays offline.
  This mode also offers **Anime characters · CCIP** (about 150 MB, upstream OpenRAIL),
  trained for identity similarity in single-character anime images across poses and
  styles without requiring identical colors. Multiple characters, animal mascots
  and extreme parodies may work poorly. It is not general object identity recognition.
  Engines have separate versioned feature caches; incremental scanning is sufficient.
- **Local cache** in the scan panel shows storage usage and offers confirmed cleanup
  of results, analysis, or the whole media inventory. Phone originals, installed
  models, settings and operation journals are kept. Model/version changes invalidate
  affected vectors and grouping results; compatible previews can still be reused.
- Ungrouped media and damaged-file review cards; originals on demand, looping
  viewer navigation, pointer-centered zoom and side-by-side comparison.
- Date/count/size sorting, search, page jumps, incremental caches and speed charts.
- Chinese / English UI: choose **语言 / Language** in the header. The preference is
  remembered. Switching reloads the view and preserves scan settings, album selection
  and filters; a background scan continues. Open viewers close and file selections
  must be made again. This does not invalidate media caches.
  Recent speed samples survive language reloads for the same job and phase. Long
  polling gaps remain gaps, not invented speeds; the page still briefly reloads.

Recognition is heuristic. Severe deformation, low texture, short scenes between
sampled frames or candidate limits can cause missed matches. Similarity scores are
not duplicate probabilities. Nothing is deleted automatically.

## Quick start (Windows)

For a graphical workflow, after installing the prerequisites below, double-click
**PhotoCluster.cmd**. The bilingual control window offers **Start and open**, **Open
interface**, **Exit application**, dependency repair and local logs. Initial setup
installs dependencies; later launches reuse the environment. The browser opens only
after the service is ready. The window reports when its process has stopped.
The launcher remembers its language and passes it to newly opened pages. The log
window tails updates every 500 ms, with vertical/horizontal scrollbars and a jump
to latest control; reading older lines does not force the view back to the bottom.

The page also shows connection status and **Exit PhotoCluster**. Closing a browser
tab does not stop the service or interrupt a scan. Confirmed exit stops classification,
preserves completed caches, waits for active file operations/reads and closes previews.
An unexpected connection failure is not reported as a successful exit.

For older instances, click **Switch to managed startup** in the control window.
Finish scans and close previews first; do not operate from other tabs during the
switch. It validates an idle, same-user, same-project Uvicorn process and sends a
cooperative interrupt, verifies exit, then starts the managed service. No force
termination is used. If safe migration is unavailable, the window explains a
system-restart fallback without requiring terminal commands.

Install **Python 3.11+**, [ADB / Platform Tools](https://developer.android.com/tools/releases/platform-tools)
and [FFmpeg + FFprobe](https://ffmpeg.org/download.html), and add their executables
to `PATH`. Enable Android USB debugging, connect by USB and authorize this computer.
Check the connection with `adb devices`.

```powershell
git clone https://github.com/goldimpact/PhotoCluster.git
cd PhotoCluster
.\start.ps1
# Existing dependencies, no automatic browser opening:
.\start.ps1 -NoInstall -NoBrowser
```

Open **http://127.0.0.1:8765**. Click **Sync folders** to inspect phone albums, then
**Sync and classify**. Defaults: all phone albums, comparison across albums,
same-source variants, incremental update, mirror/perspective enabled, warp disabled.

The script creates `.venv` and installs Python dependencies. For semantic mode or
optional NVIDIA CUDA acceleration:

```powershell
.\start.ps1 -InstallModel
.\start.ps1 -InstallGpu
# Optional local proxy for dependency / model downloads:
.\start.ps1 -InstallModel -Proxy http://127.0.0.1:7897
# Force CPU execution:
.\start.ps1 -Accelerator cpu
```

The optional model is approximately 89 MB. Without it, same-source and near-duplicate
modes work; semantic mode explains how to install it. GPU support requires compatible
NVIDIA drivers and CUDA 12 runtime libraries. It falls back to CPU if unavailable.
CLIP inference currently uses CPU INT8; not every stage uses the GPU.

For subsequent launches without checking/installing dependencies:

```powershell
.\start.ps1 -NoInstall
```

On Linux with Python 3.11+, ADB and FFmpeg installed, run `bash start.sh --check`,
then `bash start.sh --no-install`. The Linux environment is `.venv-linux`.
WSL can reuse Windows `adb.exe`; its default cache is isolated in `data/wsl/`.
Linux desktop / WSLg users can run `bash PhotoCluster.sh` for the control window
(Tk is required for the selected Python). Headless users can use `bash start.sh`;
web exit works with that launcher too. `--no-browser` preserves a terminal-only flow.
Use `--port 8766` if Windows is already using port 8765. See the Linux guide for
Ubuntu 22.04 Python setup, USB permissions, proxy differences and explicit ADB selection.
`requirements-lock.txt` records the tested Windows Python 3.11 CPU dependency
snapshot; `requirements-gpu.txt` is separate. Node/npm are needed only for UI tests.

## Sync, review and manage

| Action | Effect |
| --- | --- |
| Sync folders | Read Android MediaStore, update inventory and remove stale result references; no similarity computation |
| Incremental update | Sync, analyze new/changed media, reuse compatible features and comparisons |
| Full recomputation | Reread all selected originals, recompute features and groups without old matching caches |
| Delete / move | Preview exact paths, confirm, revalidate content hashes, then operate on selected originals |

Scans use an inventory snapshot, not continuous phone monitoring. Files created
during a scan appear at the next sync. Results publish only after the entire scan
finishes. While running or after a stop/failure, the UI labels any previous results.

Deletion is **permanent, without a recycle bin**. Keep backups of important media.
Existing destinations are never overwritten. Successful operations update every
reference in the current results; singleton groups become ungrouped media. The app
notifies Android MediaStore, but phone galleries can take time to refresh. A batch
may partly succeed on disconnect; review each result. External apps can still change
a file between hash verification and the filesystem operation.

Android MediaStore includes readable, indexed local images and videos. Cloud-only
items, app-private data and unindexed / `.nomedia` content are outside this scope.
Empty folders absent from MediaStore are not offered as move destinations.

## Privacy and storage

There is no online recognition or translation API, photo upload or third-party UI
CDN. The app listens on loopback and checks Host/Origin. Do not expose it to a LAN
or the internet as a public service. Dependency installers and the explicit model
downloader access their public package/model sources; media processing stays local.

**`data/` is private:** it contains device IDs, phone paths, thumbnails, recovered
frames, feature vectors, models, groups, errors and an operation journal. Logs and
exported CSV/JSON also contain private metadata. None should be published with code.
Browser storage remembers language/rules and temporarily stores view settings when
switching language. Do not attach private exports or caches to public issues.

Original still images/GIFs are loaded into memory on demand (150 MB per-image viewer
limit), with Blob URLs released on switching/closing. Videos and damaged-media
recovery use temporary files. Video playback leases are released on close or expire
after inactivity. A killed process can leave temporary files; OS/browser memory
reclamation is not secure erasure. Images too damaged to decode remain listed with
a placeholder and diagnostic information.

## Development

```text
python -m pip install -r requirements.txt
npm ci
python -m pytest -q
npm test
```

Tests use synthetic media and mocked phone operations. CUDA, actual model inference
and FFmpeg checks skip if the corresponding dependency is unavailable. CI runs CPU
tests on Windows and Ubuntu. VM/jsdom tests cover frontend behavior, not real
browser rendering or real-device iOS support.

See [AGENTS.md](AGENTS.md) for AI coding instructions,
[architecture](docs/ARCHITECTURE.md) for implementation boundaries,
[recognition rules (Chinese)](docs/CLASSIFICATION-RULES.md) and
[speed chart (Chinese)](docs/SPEED-CHART.md).
Read-only benchmarks require your own local scan cache; reports stay in `data/`.
Old personal experiment reports and private baseline snapshots are not distributed.

## Roadmap and license

- First, improve Windows/Linux Android workflows and validation.
- Later, when hardware is available: macOS validation and iOS device discovery, permitted library access and file-management capabilities,
  followed by real-device validation. Android filesystem assumptions must not be
  carried over to iOS without checking platform permissions.
- Broader desktop/device compatibility and real-browser UI coverage.
- Recognition/throughput improvements with reproducible synthetic evaluations.

[MIT](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for dependencies,
FFmpeg/ADB and the separately downloaded model.
