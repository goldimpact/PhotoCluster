# Architecture and compatibility

The application is a loopback FastAPI service with a static, dependency-free
production UI. Android MediaStore supplies the inventory; ADB supplies originals
and explicitly confirmed file operations. There is no hosted inference service.

## Recognition

SHA-256 identifies identical files. Near-duplicate modes combine oriented perceptual
hashes, structure/color comparisons and optional SIFT alignment. Animation matching
in those modes uses stricter timeline samples; videos that are not identical should
use same-source or semantic modes.

Same-source variants use local feature candidates, affine/perspective fitting,
coverage checks and aligned regional structure/color verification. Mirrored feature
comparison, perspective and sparse residual warp correction are separately
selectable. Warp is off by default. GPU descriptor matching and content retrieval
have CPU fallbacks; geometric verification and INT8 model inference still use CPU.

Semantic mode uses the optional pinned CLIP image encoder to compare sampled frames
across formats. Related content does not imply a common original. Both approaches
require each group member to match its representative; they do not form unbounded
transitive chains. Candidate caps and frame sampling trade recall for bounded cost.

## Caches and publication

The private `data/` directory stores the inventory, thumbnails, recovered frames,
SQLite features/vectors/pair comparisons, saved groups and an operation journal.
File keys include device identity, path, size and modification time. Changes hidden
by unchanged size/timestamps require a full recomputation.

Result signatures include scope, mode, threshold, media set, algorithm version and
selected rules. Positive and negative geometry comparisons are directional and
versioned separately by rule combination. UI language is not part of these keys.
Changing recognition/model semantics requires reviewing all affected version keys.

Scans publish only a complete new result. Stopped/failed scans retain completed
feature work and previous results with explicit UI labeling. Ungrouped media are
successfully analyzed files without matches in the current scan scope and mode;
failed decoding belongs in review cards instead.

## File operations and previews

Operations use a short-lived, single-use preview token. Execution rechecks the
device, storage path, regular-file status and source content SHA-256. Moves reject
existing destinations. Deletion is permanent. All result/catalog references update
after success, and a singleton becomes ungrouped. Operations and scans are mutually
exclusive. This is not an atomic transaction against external phone applications.

Still/GIF originals are served from memory with no-store responses. The viewer
cancels stale requests, revokes Blob URLs and uses generation checks. Videos have
bounded temporary-file leases with close/release, keepalive and expiration. Recovery
also uses temporary files; forced process termination can leave those files behind.

## Localization

`web/locales/en.js` maps Chinese source copy to English. `I18n.t`, `I18n.msg` and
`I18n.html` translate trusted literal text before substituting application values.
Keep user-controlled values HTML-escaped where needed. Do not translate filenames.
Static HTML is translated once before media data is loaded. Backend display fields
are localized through `web/locales/api-en.js`; external decoder/OS diagnostics remain
verbatim. Stored caches and API identifiers remain language-independent.

Language changes reload the view, restore settings/filters and release previews;
they do not stop the backend scan or submit operations. Dialog/file selections are
not restored, so a previous operation cannot be accidentally confirmed after switching.

## Benchmarking

`benchmarks/cluster.py` uses an existing local feature cache.
`scripts/benchmark_hardware.py` compares local CPU/GPU workloads and records actual
hardware state. `benchmarks/scan.py` reads selected phone files without modifying them.
Their reports contain private cache identifiers: keep them in `data/`.
Do not benchmark alongside a user scan or describe cache-hit timing as cold throughput.
Private historical reports are not a reproducible public benchmark dataset.
