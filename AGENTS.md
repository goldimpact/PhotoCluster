# Working on PhotoCluster

Read this file before making changes. These are repository instructions for AI
coding agents, not a reusable SKILL.md package. Explicit user instructions take
precedence. Do not assume a phone, CUDA device, model or browser is available.

## Product boundaries

- Android via ADB is the implemented device backend. iOS is planned and untested;
  do not advertise it as supported. Focus on Windows/Linux Android workflows;
  macOS and iOS work is deferred until hardware is available.
- Classification folders are virtual views. Never create them on a phone, import
  files into them, or choose phone destinations implicitly.
- Delete only explicitly selected phone files after a reviewed operation preview.
  Move only to discovered, existing real phone directories; never overwrite.
- Keep SHA-256 revalidation, path/symlink checks, device identity, expiring
  single-use operation tokens and scan/operation exclusion intact.
- Update all references to an operated file, including the catalog, groups and
  ungrouped media. A remaining singleton belongs in ungrouped media.
- Every member must match its group's reference directly. Avoid transitive
  similarity chains. Similarity and model scores are not deletion guarantees.

## Privacy and safety

- All inference and media analysis stay local. Never add upload, remote inference,
  telemetry, external fonts or third-party UI scripts. Downloading dependencies
  or an optional documented public model is distinct from uploading user data.
- Never commit data/, logs, media, device serials, private paths, exported results,
  feature vectors, model weights, operation journals or personal benchmark reports.
  Keep synthetic test media generated in temporary directories.
- Never test deletion or moving on a real user's phone. Mock ADB operations.
  Do not stop an active scan or clear existing caches merely to test a change.
- Preserve loopback binding and Host/Origin checks. This app is not a hosted
  multi-user service. Images use in-memory previews; video/recovery temporary
  files need bounded lifetimes, cancellation and lease cleanup.

## Code map and compatibility

- photocluster/app.py: API and origin guards; service.py: inventory, scan and
  publication; adb.py: MediaStore/transport; operations.py: phone mutations.
- vision.py / variants.py / semantic.py: recognition; index.py / pair_cache.py /
  acceleration.py / geometry_gpu.py: retrieval, caching and optional acceleration.
- subject.py is experimental automatic DINOv2 region grouping, not validated
  character identity recognition. Preserve direct-reference checks, zero duplicate
  savings and model SHA/version isolation; do not claim cross-style accuracy without data.
- character.py adds optional CCIP for single-character anime imagery, not a general
  identity solution. Preserve upstream preprocessing/distance scale, separate model
  license and cache identity. Do not gate CCIP matches on DINO or colour equality.
- subject_auto.py is the single user-facing subject workflow. Do not reintroduce
  category/model selectors. It uses frame-specific routing for supplemental evidence;
  every input retains the general route. Version all contributing models/policies,
  preserve original-reference checks, and never advertise universal identity accuracy.
- cache.py cleanup is local and allowlisted, requires an expiring preview token,
  rejects scans/syncs, shares the operation lock and invalidates pending file plans.
  Keep models, settings, journals, unknown files and other instances; never call ADB.
- media.py / video.py: recovery and temporary original lifetimes.
- web/: plain browser JavaScript/CSS, no production build or npm dependency.
- config.py owns host data/model paths. Windows uses .venv and Linux .venv-linux.
  WSL defaults to data/wsl; never reuse Windows feature paths in a Linux cache.
  adb.py supports one PHOTOCLUSTER_ADB executable override and WSL adb.exe fallback;
  Windows adb pull destinations need wslpath conversion. Keep streams binary.
- server.py/runtime.py own managed startup/exit; desktop.py is optional Tk control.
  Shutdown must wait for admitted requests (including response bodies) and the scan
  thread, preserve cache writes, and reject new work. Never force-kill discovered
  PIDs or infer successful shutdown from a network error. Legacy migration requires
  explicit confirmation, exact listener/user/workspace/command/cache validation,
  idle scan/sync status, and a cooperative interrupt. On Windows refuse shared
  consoles containing unrelated processes; never broaden the signal target.
- Read relevant tests before changing behavior. Keep bounded memory/work queues
  and CPU fallbacks; do not trade recognition thresholds for undocumented speed.
- If extraction, matching or model semantics change, inspect feature versions,
  Service result signatures, semantic.VERSION and rules.pair_version together.
  Do not reuse stale positive/negative matches across rule/model versions. UI-only
  language changes must not invalidate media caches or alter stored identifiers.
- New groups publish only after a full successful scan. During scans or after
  stop/error, label previous results explicitly; never imply they are live groups.

## Localization

- Keep Chinese and English copy together in web/locales/en.js. Chinese source
  strings are keys. Use I18n.t for literals, I18n.msg tagged templates for messages,
  and I18n.html for trusted HTML templates. Escape user values with esc as before;
  translation is not HTML sanitization. Never translate interpolated file paths.
- API display strings are mapped only in explicit fields by web/locales/api-en.js;
  identifiers, filenames, paths and saved caches stay unchanged. Add mappings for
  new application-owned backend messages; preserve external diagnostic text.
- Static index.html is localized once before data loads. Do not add a blanket
  MutationObserver translator. Language reload preserves scan settings/filters;
  the server job continues. Verify destructive confirmations in both languages.
- The desktop passes a one-shot `lang=zh|en` URL choice; consume it before rendering
  so later in-page language changes win. Preserve recent speed samples across language
  reloads only for the same job/phase, translating clocks without inventing samples.

## Verification

Python 3.11+ and Node 20+:

```text
python -m pip install -r requirements.txt
npm ci
python -m pytest -q
npm test
git diff --check
```

Use .venv/Scripts/python.exe on Windows and .venv-linux/bin/python on Linux.
scripts/check_android.py is an explicit,
read-only real-phone check with temporary caches. Do not run it automatically in CI.
Core tests use synthetic media and mocked devices. FFmpeg/model/CUDA tests skip when unavailable; do not
download a model just to force those tests to run. A jsdom or VM test verifies
logic, not real browser layout. State visual-testing limits honestly.

Before a public commit, inspect the staged file list and staged content, verify
data/ and local artifacts are ignored, and run the relevant tests. Before publishing,
review README claims and dependency/model license notices. Never force-push or
rewrite published history unless the user explicitly requests it.
