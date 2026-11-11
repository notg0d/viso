# Changelog

[Project overview](README.md) · [Validation evidence](docs/testing.md) · [Measurements](docs/performance.md)

The 0.8.1 desktop has an experimental Windows ZIP release; earlier entries describe development builds. Work is validated on `test`, then production source/documentation is synchronized to `main` without test sources, runners/fixtures, benchmarks, or the historical browser bench. Desktop and separately installed sign-in components can have different versions.

## Unreleased — documentation and repository organization

- Screenshot-led README with a short native quick start and clearer simulator/sign-in distinction.
- Documentation index, onboarding, troubleshooting, security/privacy, development, script, and contribution guides.
- Earlier validation separated into `docs/history/`.
- Historical browser source, configuration, lockfile, and sampler tests isolated in `experiments/browser/`; the optional HTTP host now serves its nested `dist/`.
- Local Markdown link/anchor/asset checker. Native runtime paths, model/dependency versions, local data, and installed Windows components are unchanged.
- Validation passed 113 Python tests, four browser sampler tests, and the browser TypeScript/production build; local documentation links/assets were checked. Test/tool/browser files remain on `test` only; shared guides and validation records are included on `main`.

## Desktop 0.8.1 — 2026-11-11

### Runnable Windows package

- Extract-and-run Windows x64 ZIP with `Viso.exe`, private CPython, the pinned recognition dependency closure, verified models, redistribution notices, source/version metadata, and SHA-256 manifests.
- Isolated desktop worker startup selects the bundled runtime or the source checkout's `.venv`; ignores Python environment/path injection and creates no bytecode caches.
- Unicode-safe in-memory model loading, after extraction testing reproduced OpenCV's non-ASCII Windows path failure.
- Package excludes user enrollment/account credentials, tests/fixtures, browser assets, pip, unrelated installed packages, and development leftovers. Existing local data and installed Windows sign-in are not modified.
- Separate Windows sign-in installation is not included. Requires Windows 10/11 x64 and .NET Framework 4.8; the executable is unsigned. [Download and run](docs/releases.md).
- Release gate validates the extracted production executable/runtime outside the repository, including Unicode paths, isolated imports, inference, private IPC, both storage-mode startups, and worker cleanup. Regression coverage and release validation helpers remain on `test` only.

### Fixed

- Unlock-test ring crash when valid identity frame counts exceed the minimum before the elapsed-time gate completes.
- Visual progress is finite/coerced, animation uses coerced targets, and rendered intensity is bounded before cached-color lookup. Identity, threshold, timing, and blink rules are unchanged.

### Verified scope

The regression reproduced the exception before the fix; **111 Python tests** and **63 native raster/resource cases** passed afterward. Static/animated high-streak and circular UI captures were inspected. The production desktop is **0.8.1.0** and excludes rendering-test helpers. No physical-camera test was performed for this hotfix.

This is desktop-only. Installed sign-in remains **0.8.0**; no reinstall, re-enrollment, or relinking is required for the rendering fix. [Full record](docs/testing.md#081-desktop-unlock-rendering-hotfix).

## Desktop / sign-in 0.8.0 — 2026-11-11

### Added and changed

- Neutral calibration plus two eight-direction enrollment circuits: **17 averaged views**, at least **51 distinct open-eye observations**, diagonal coverage, and interpass recentering.
- Eight-sector ring fills blue on pass one and green on pass two, with static reduced-motion guidance.
- Cached float32 matching, with two **distinct pose groups** required for a multi-view override; existing five-view profiles remain compatible.
- Frozen ring resources, canceled unused IPC timers, stopped idle preview polling, and release of stopped camera buffers.
- Model-only standby workers expire after 60 seconds and retire on suspend, initialization failure, or disposal.
- Selected-tile rearming on interactive wake/display return, with pre-sleep credential/evidence revocation and no maintenance-wake/retry loop.

### Deployment and limits

The authorized administrator upgrade retained the encrypted account link, checked 19 installed file hashes, preserved other provider registrations, and verified x64 registration, automatic LocalSystem startup, and 25 installed-runtime checks. These runtime checks ran as the elevated development user, not LocalSystem. No restart was needed.

Physical circular enrollment, current-build authentication, long sleep/hibernate/Modern Standby, reboot, Microsoft-account, and multi-user behavior remain unverified. Re-enroll and explicitly **Link / update account** for the new circular snapshot. The gesture is not TrueDepth or a measured accuracy gain. [Research and deployment record](docs/enrollment-resume-research.md).

## Desktop / sign-in 0.7.1 — 2026-11-08

- Single-open DirectShow resolution negotiation avoided driver restarts; the local first-frame measurements improved from one **4.489 s** baseline to approximately **1.05 s** on the development camera.
- Fresh one-use credentials survive Windows' successful-verification tile refresh without extending their original expiry; deselection/teardown still revoke them.
- Earlier automatic local-account unlock was confirmed without pressing the arrow. This does not validate subsequent sign-in builds. [Historical native evidence](docs/history/native-validation.md).

## Earlier native and browser development

- **0.7 native:** asynchronous status/model startup, raw camera recognition, model-only one-shot prewarm, shorter stable holds, and provider automatic-selection/callback improvements. [Measurements](docs/performance.md#earlier-07-improvements).
- **0.5 browser:** bounded chin-up eye geometry/calibration and pose-local blink references.
- **0.4 browser:** individual enrollment views, multi-angle matching, small-motion tracking/recovery, and final fresh confirmation.
- **0.3 browser:** buffered capture, faster detection/eye tracking, relative blink detection, and averaged neutral-calibrated enrollment holds.

The browser versions are historical experiments, not the current native frontend. [Earlier validation](docs/history/browser-validation.md) · [Browser package on `test`](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md).
