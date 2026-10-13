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
- variant_cache.py indexes only retrieval metadata; validate source SHA, sampling,
  extractor version and archive stat before reuse. Keep descriptor archives
  authoritative, bounded extraction queues, input ordering, atomic NPZ writes and
  allowlisted cleanup. Query pair verdicts before decompressing cached descriptors.
- subject.py is experimental automatic DINOv2 region grouping, not validated
  character identity recognition. Preserve direct-reference checks, zero duplicate
  savings and model SHA/version isolation; do not claim cross-style accuracy without data.
- character.py adds optional CCIP for single-character anime imagery, not a general
  identity solution. Preserve upstream preprocessing/distance scale, separate model
  license and cache identity. Do not gate CCIP matches on DINO or colour equality.
- subject_auto.py is the single user-facing subject workflow. Do not reintroduce
  category/model selectors. A unified UI does not restrict internal models or
  strategies: evaluate complementary retrieval, localization and verification
  routes, including their shared errors; model agreement alone is not confidence.
  It uses frame-specific routing for supplemental evidence;
  every input retains the general route. Version all contributing models/policies,
  preserve original-reference checks, and never advertise universal identity accuracy.
  Inconsistent frame routes abstain. General verification needs distinct one-to-one
  region support; do not restore single-region maxima as the final acceptance rule.
  v12 general-route counterevidence requires both strong frame-domain gates and
  both identity encoders to disagree. Apply masks before frame selection in both
  initial proposals and general verification; preserve alternate valid frames.
  Do not turn a rejected frame into a whole-media veto or invalidate feature caches.
  Reference ordering breaks equal quality ties by content SHA and stable media
  key. Do not restore dependence on MediaStore enumeration or input permutations;
  hashes order work, never establish semantic identity.
- perceptual.py optionally verifies candidates with exported DreamSim ONNX features.
  Keep signals aligned to the same original frame pair, lazy bounded extraction,
  SHA/model/sampling isolation, and explicit basic/enhanced status when absent.
  Presets are development-calibrated; do not advertise a library-wide accuracy.
- complementary.py optionally adds local SigLIP 2 after the original consolidation.
  Preserve upstream bilinear preprocessing, same-frame three-signal verification,
  distinct region support for the general route, route-conflict abstention, bounded
  candidate retrieval and lazy cache isolation. Semantic similarity alone must not
  accept identity matches. Do not feed reviewer labels/names into inference.
- identity_refine.py optionally loads larger CCIP only after same-frame eligible
  identity, semantic and perceptual candidate checks. Keep its own model scale and
  cache identity; no unconditional whole-library extraction or route-conflict fallback.
  Supplemental whole merges need two disjoint cross-group correspondences as well
  as a common directly verified reference. Preserve source/target distinctness.
- domain_refine.py optionally supplements missed style routes after all original
  checks fail. Preserve the original first pass. Both frames need domain support,
  small AND large identity support, and same-frame semantic/perceptual evidence.
  Domain disagreement abstains; domain scores alone cannot accept identity.
  Keep raw probabilities in their separate cache; never unit-normalize them.
  v15 also disables the specialist gate per frame when real-domain probability
  is at least .90. Preserve the general route and ambiguous/character gates;
  the style classifier's 3d label does not establish specialist applicability.
- local_context.py optionally detects a single character context in the middle
  sampled frame. Never select one of multiple detected subjects. Retain source
  frame/crop coordinates, original-frame domain/support checks, both identity
  encoders and aligned perceptual/semantic evidence. Cache absent detections;
  bound cold work, memory and existing-member retrieval. This detector is not a
  general object recognizer; keep the unified UI and unchanged general route.
  Large local identity features are lazy after cheap evidence passes; preserve
  complete legacy records and partial-record resumption. Missing features are
  not negative verdicts. Reuse the stored crop/frame instead of redetecting.
- subject_merge.py may reselect an original media item as a common reference for
  established groups. Reverify every union member directly, including old references
  and earlier merged members; rewrite scores/frame evidence for the new reference.
  Candidate edges are not merge evidence. Preserve work bounds and cancellation.
  Partial regrouping also needs two distinct directly matching members from the
  other source group for each core member; reverify residual groups and preserve
  each file exactly once. Do not use human example names/IDs as inference rules.
- subject_singletons.py reviews only singletons against frozen existing groups:
  fixed original reference with local-context proof, at least four distinct-SHA
  peers, at least three/half peer support, unique qualifying retrieved target.
  Additions cannot support later additions; never transfer established members.
  Preserve scope, retrieval/verification budgets and abstention on incomplete
  ambiguity checks. Retrieval evidence alone is never an acceptance verdict.
  The alternate_identity route may use a frozen target's lower-quartile direct
  degree floor (at least three), only for <=64 distinct-SHA peers, within the
  same request budget. Keep ordinary local-context support requirements intact;
  incomplete statistics or oversized groups retain the strict half-peer rule.
  Check candidate support before computing density: already sufficient support
  or fewer than three peers needs no target-internal comparisons. Deferred
  statistics still share the budget and cannot bypass target ambiguity checks.
- identity_extra.py is optional CCIP v2 joint evidence, not universal identity.
  Require both frame-domain gates and same-frame small/large identity, semantic
  and perceptual evidence before lazy encoding; preserve independent model/cache
  identity, cold-work caps and cancellation. A budget miss is not a negative.
- cache.py cleanup is local and allowlisted, requires an expiring preview token,
  rejects scans/syncs, shares the operation lock and invalidates pending file plans.
  Keep models, settings, journals, unknown files and other instances; never call ADB.
- media.py / video.py: recovery and temporary original lifetimes.
- frame_policy.py versions dynamic-media sampling across catalog refresh, all
  embedding/router caches, variant features, pair verdicts and final results.
  Keep still-image caches compatible; upgrade legacy 64px animation samples on
  the next requested scan, not by clearing the library or background rescanning.
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
