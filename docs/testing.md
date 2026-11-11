# Testing Viso

[← Documentation](README.md) · [Development commands](development.md#validate-changes) · [Performance evidence](performance.md)

## Validation snapshot

Recorded on **2026-11-11, `test` branch**. Desktop **0.8.1** and installed sign-in **0.8.0** are separate builds. The earlier [physical 0.7.1 results](history/native-validation.md) and [browser experiments](history/browser-validation.md) are historical, not current-build authentication evidence.

The documentation/browser-layout update adds two static-host regressions to the 111-test hotfix baseline. Commands below use temporary or memory-only test state; a passing suite does not authorize installation or establish biometric accuracy.

## Unreleased camera compatibility and diagnostics

The [pinned Windows Face Unlock source review](windows-face-unlock-review.md) informed serial startup fallback and explicit, privacy-conscious Activity export. These source changes are **not in the published v0.8.1 ZIP** and do not modify the installed 0.8.0 sign-in components, encrypted account links or enrollment.

Validated on **2026-11-11**, using synthetic drivers, temporary/memory-only state and the existing public portrait fixtures:

- **135 Python tests passed:** the 119-test packaging baseline plus 16 new fallback/diagnostic regressions. Actual shared `Camera` tests cover negotiated/default DirectShow, last-choice Media Foundation, constructor rejection, failed/invalid initial reads, mandatory valid frames, one shared deadline, blocked-constructor timeout, cancellation during startup, release-before-fallback, release-failure retirement, no streaming reopen, immutable raw samples, preview-free capture and read-only/private diagnostic snapshots. Existing 30 fps sampling, stop/read races, fresh prompt/eye rules, real-model inference and encrypted storage coverage remain passing.
- **Native WPF smoke passed**, including all **63 raster/resource cases**, real isolated-worker diagnostics and Activity export shape/version checks, stale-generation camera-error rejection, both enrollment circuits, reduced motion, minimum layouts, control gating and image enrollment/photo rejection/deletion. `test-results/native/diagnostics.json` records a camera-off snapshot; Activity and minimum-layout captures were inspected.
- **Sign-in build/component checks passed:** actual C++ DLL activation/lifecycle tests, **59 C# service/protocol checks**, **11 deployment ownership/ACL/reparse checks** and **25 packaged service-to-Python checks** against a newly copied private runtime containing the changed shared backend. Import isolation, checksums, real blank-frame inference, standby/suspend/Job cleanup remain passing. This is not an installation or a LocalSystem physical-camera test.

Run on `test`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\scripts\build-native.ps1 -SmokeTest
.\scripts\build-signin.ps1 -Test
.\scripts\test-signin-runtime.ps1
```

No physical camera, real account password, privileged installation, automatic locking or new dependency was used. Fallback success/latency on real drivers and cross-backend camera-index mapping remain unverified. A blocked native call cannot be forcibly canceled by the Python startup budget; no second handle is opened while it is stuck. Existing sleep/reboot/MSA/multi-user and presentation-attack manual gates still apply. Test files and added smoke-only assertions remain on `test`; production changes and this evidence record are promoted separately.

## 0.8.1 runnable Windows packaging

[Release packaging](releases.md) adds a private Python runtime, dependency/model notices, provenance and hash manifests, and an isolated worker entry point. Extraction testing reproduced OpenCV's Unicode Windows filename failure; verified model buffers now avoid that path API. Recognition rules and model/dependency pins are unchanged.

The package gate extracts the actual production ZIP outside the repository, into a spaces/Unicode path, with an unrelated working directory. It checks payload hashes/exclusions, exact dependency inventory, poisoned Python environment isolation, blank/portrait inference, synthetic DPAPI persistence, image enrollment/photo rejection over private IPC, the actual production `EngineClient`, WPF model-ready startup in ephemeral and normal modes, and graceful child cleanup. Test sources/helpers are never placed in the ZIP or `main`.

Source checks include the existing **113 Python tests**, six synthetic dependency-packager regressions, the **63 WPF raster/resource cases**, and the **25 packaged service-to-Python checks** for the shared packaging helper. No physical camera, installed service/provider changes, real account credentials, or existing enrollment is used. Final artifact validation must pass from committed production sources before upload. A separate clean Windows machine and physical current-build authentication are not covered.

## 0.8.1 desktop unlock-rendering hotfix

The user's 0.8.0 Unlock test crash was identified in Windows' .NET Runtime event log as `IndexOutOfRangeException` in `EnrollmentRing.OnRender`. Fast valid identity frames can produce `streak > required` while the 150 ms time gate is still pending; an unclamped progress ratio overran the cached pen palette. A new WPF regression reproduced the same exception before the fix.

The ring now coerces visual progress to finite bounds, animates toward the coerced targets and clamps rendered intensity. Recognition state, frame counts, elapsed-time requirements, threshold and blink/open-eye checks are unchanged. Validation passed **111 Python tests** and **63 WPF raster/resource cases**, including 27 new cases: seven above-minimum streak checks, 15 invalid/extreme progress checks, four animation cases sampled at four frames each and one invalid-animation-target case. Actual static/animated high-streak and circular-enrollment screenshots were inspected. No physical camera or account changes were used by these checks. The production desktop executable is rebuilt as **0.8.1.0**; the installed sign-in provider/service/runtime remain the previously verified 0.8.0 build because this fix changes only desktop rendering.

## 0.8.0 circular enrollment, wake and resource update (test branch)

The user-authorized 0.8.0 upgrade is installed on the development machine. The existing encrypted account link and desktop enrollment were retained without relinking. Automated checks use synthetic profiles/credentials, temporary storage and public portrait fixtures; they do not open the physical camera. Research preceded implementation: [primary sources, validation gates and deployment verification](enrollment-resume-research.md).

Current validation covers:

- **113 Python tests after repository organization:** the 111-test hotfix baseline plus two HTTP static-host/path regressions. Coverage includes two eight-direction circuits and interpass recentering, distinct/stale-frame rejection, averaged holds, wink/closed-eye/wrong-person rejection, encrypted circular profile roundtrip, strict new/legacy profile validation, distinct-group matching, matcher reuse/release, finite-norm validation and stop/read resource races. The fast-frame regression confirms that a streak above the minimum still needs the time gate and fresh blink. The existing real-model identity/blink/motion suites remain intact.
- **C++ provider build/actual DLL activation:** synthetic suspend, interactive/maintenance resume and display notifications; one fresh attempt without a new `SetSelected`; duplicate/out-of-order notification suppression; pre-sleep credential serialization rejection; deselection, window recreation, registration cleanup and unload. Event sinks abort before real service/camera I/O.
- **59 C# service/protocol checks:** existing protocol/account/vault/peer protections plus suspend pipe cancellation, power-generation rejection before worker acquisition, successful/failed deadlines and idempotent service disposal.
- **11 deployment ownership/ACL/reparse checks**, without installing/registering the provider or service.
- **25 packaged service-to-Python checks**, plus isolated imports, model checksums and real blank-frame inference: circular profile acceptance/rejection, model-only prewarm, real timed standby retirement, stale timer callbacks, suspend Job cleanup, standby consumption/replacement and failed-initialization cleanup.
- **Native WPF build/smoke:** five pages, real model IPC, circular first/second-pass screenshots, power interruption cleanup, and **63 raster/resource cases** (30 preview/name checks, six circular/resource checks and 27 unlock-progress regressions). Screenshots were inspected at standard and minimum sizes. No physical camera is started.
- **Repeatable synthetic matcher benchmark:** [timings, traced allocations and measured standby footprint](performance.md). It does not quantify biometric accuracy or full-app memory savings.

Run the commands below on `test`; test sources/runners and the archived browser bench are intentionally absent from `main`. This document is retained on both branches as an evidence record. A pass is not permission to install the prototype or a substitute for the manual long-sleep matrix.

## Initial test environment

Run `scripts/start.ps1 -Ephemeral`. This launches the native WPF app with a memory-only Python recognition worker. The lock screen in the interface is a simulation. Python dependencies are isolated in `.venv`; the native build uses the installed Windows .NET Framework.

The default launch without `-Ephemeral` keeps one encrypted test profile in `.viso/profile.dpapi`. The **On-device by design** readout and Settings profile details identify the active mode.

## Automated checks

```powershell
.\scripts\test.ps1
```

This downloads three public example portraits into the git-ignored `tests/.fixtures/`, runs Python's unittest suite against the actual ONNX models, then builds and smoke-tests the native app. Test storage uses temporary directories or explicit memory-only profiles. Native screenshots and the smoke report are written to `test-results/native/`.

Coverage includes:

- Different photos of the same person match; another identity does not.
- Empty frames, multiple faces, invalid images, and mixed-identity enrollment are rejected.
- Open → closed → reopened eye sequence, final open-eye confirmation, wink/closed/unknown rejection, stale evidence, blink timeout, and attempt expiry.
- Guided pose sequence, steady holds, wrong angles/person, closed eyes, expiry, cancellation, and finish-only persistence.
- Real MediaPipe eye measurements and mirrored yaw sign on fixtures; repeated matching photos never unlock.
- Client-supplied eye/blink/pose claims cannot override backend measurements.
- Brief sampled blinks survive batched delivery; pre-prompt evidence is discarded and the newest frame must have open eyes.
- Capture timestamp ordering/freshness, bounded buffers, duplicate-video-frame suppression, and sampling cancellation.
- Fast eye tracking refreshes identity within 200 ms and always performs full recognition on blink/reopening/confirmation frames.
- Neutral-hold calibration, relative target feedback, eight-direction coverage and mandatory recentering between circular passes.
- Multi-view consensus, rejection of single-view outliers, legacy-profile compatibility, encrypted view storage, and vector-free status responses.
- Brief borderline-match/near-open measurement recovery, fixed recovery deadlines, motion-following cache bounds, and fresh final confirmation after movement.
- Upward-tilt XYZ geometry, width-scaled depth on non-square images, bounded correction, and invalid/closed-eye geometry rejection.
- Pose-local blink references, calibrated chin-up reopening, rejection of tilt-only blink evidence and either-eye closure, and identity-local reference resets.
- Inferred-open frames cannot train/drift calibration; API responses reflect the effective session eye state.
- New scans invalidate old scans; profile deletion revokes active scans.
- DPAPI persistence, encrypted bytes, corrupted-profile handling, and deletion.
- Loopback API token, origin/host validation, malformed/oversized requests, and static-path traversal.
- Native pipe initialization, malformed-command recovery, real inference, and EOF shutdown.
- Native camera queue freshness, explicit prompt acknowledgment, cancellation, finish-only persistence, and photo rejection.

For the backend suite alone:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Real-model tests are marked skipped if the optional image fixtures have not been downloaded. `test.ps1` fetches them before running so the full suite executes.

## Manual scenarios

| Scenario | Expected behavior |
|---|---|
| Start with a fresh profile | Unlock button disabled until enrollment and an input are ready |
| Enroll via webcam | Follow two small eight-direction circles; sectors fill after three distinct observations across at least 0.24 s; recenter only between passes |
| Lift chin during enrollment/unlocking | Eyes remain readable with small turns and gaze toward camera; bounded calibration may show Tilt adjusted |
| Tilt upward without blinking | Prompt remains; head movement alone cannot satisfy a blink |
| Blink / wink / close both eyes while chin is raised | Bilateral blink can progress; wink/closed final eyes cannot unlock or supply enrollment samples |
| Finish guided enrollment | Ticks merge into a solid ring before the overlay clears; profile saved once |
| Reduced-motion preference | Static ring, progress, and text guidance; no moving light sweeps |
| Stay facing forward at the left/right prompt | The next pose is not captured |
| Hold a cardinal pose at a diagonal prompt | The diagonal view is not captured |
| Complete the first circle | Blue ring, brief recenter prompt; second circle turns sectors green |
| Close either eye / show a different person during enrollment | Current hold resets; sample is not captured |
| Cancel enrollment / Escape / minimize mid-enrollment | Incomplete samples discarded; no profile saved |
| Inspect an image | Face quality, eye state, similarity, and timing appear; simulated state is unchanged |
| Match enrolled face | Prompt for a blink; unlock only after both eyes reopen and remain open |
| Shift/turn slightly while scanning | Small tracked score dips briefly pause; a fresh passing match resumes within 200 ms |
| Move slightly after blinking | A brief score dip restarts open-eye confirmation, rather than immediately requiring another blink |
| Move out of frame / switch people / keep producing weak matches | Challenge resets; recovery cannot extend itself or authorize unlock |
| Re-enroll a legacy profile | New profile has circular coverage; old five-view profiles remain compatible; sign-in needs explicit relinking for the new snapshot |
| Blink normally immediately after the prompt | Brief bilateral closure is detected without a long eye hold |
| Keep both eyes closed for over 0.8 s | Blink challenge resets |
| Start with eyes closed, wink, or keep eyes open without blinking | No unlock |
| Lose face/eye tracking during the blink | Challenge resets |
| Close an eye during final confirmation | No unlock; challenge resets |
| Start a second unlock attempt | New blink required; previous blink evidence is not reused |
| Different face / no face | No unlock; live attempts expire at 20 seconds |
| Image lab: reference vs different photo of same person | Similarity can match; photo test remains locked |
| Image lab: another person | Rejected result; simulator stays locked |
| Multiple visible faces | Rejected; no dominant-face shortcut |
| Stop test / Escape | Scan canceled and simulator locked |
| Switch page, minimize, lock Windows, suspend or resume desktop | Camera released; preview polling stops; scan canceled; simulator locked |
| Deny camera access / unplug camera | Actionable error; image testing still available |
| Change threshold | Prior attempt invalidated; the next attempt uses the new threshold |
| Delete enrollment | Profile removed, attempts revoked, enrollment available again |
| Restart in ephemeral mode | No profile restored |
| Restart in persistent mode | Same Windows user restores encrypted profile |
| Recognition worker exits unexpectedly | Native error appears; close and reopen Viso |

## Development verification

The current native/sign-in implementation and reorganized HTTP host pass **113 backend tests** (including three one-shot sign-in worker tests and two static-host regressions) plus the native C#/WPF build and smoke check. Native checks open all five pages, inspect actual WPF output, verify eight-sector blue/green circular progress, bounded unlock progress, cached frozen resources, power interruption cleanup, minimum window size, reduced motion and control gating. Real blank-frame inference and image enrollment → matching-photo rejection → deletion exercise the C# process client and Unicode names. Automated checks do not start a physical camera. The [earlier camera startup and local-account unlock measurements](history/native-validation.md) do not verify the 0.8.0 sign-in update or 0.8.1 desktop hotfix; physical enrollment, lighting/glasses, long sleep and driver behavior remain manual gates.

Native rendering regressions are recorded in `test-results/native/rendering.json`: 63 cases include 30 pixel checks for circular preview fill/mirroring with 4:3, 16:9 and portrait inputs and visible profile-name text in editable/enrolling states. Those run at 1040/780 widths and 100%/150%/200% raster scales. Five cases check all eight sectors at pass boundaries and mid-pass; one checks frozen-resource reuse and immediate reduced-motion completion. The 27 hotfix cases cover above-minimum identity streaks, invalid/extreme progress and animation frames/targets. Full-window captures include both circuits and minimum layouts. The pre-fix crash reproduction is retained in git-ignored `test-results/native-crash-before/error.txt`.

## Windows sign-in validation

```powershell
.\scripts\build-signin.ps1 -Test
.\scripts\test-signin-runtime.ps1
```

The component tests do not install a provider/service, open a camera, or use real account passwords. Verified coverage:

- C++ `/W4 /WX` provider build and actual DLL COM activation without registry registration.
- Local and Microsoft-account credential packing/decryption for both logon and unlock, including Unicode synthetic passwords; unsupported scenarios and empty credentials rejected.
- V2 user/SID association, local/MSA filtering, preserving default provider selection, and withholding serialization without verification.
- Automatic-submit UI refresh retains a fresh verified result; serialization stays one-use, expiry is not renewed, and cancellation/teardown revoke it.
- **59 C# service/protocol checks:** bounded framing, malformed UTF-8, account-name rules, DPAPI round trips, record/filename SID binding, current revision checks, pending-link revocation after unlink/relink, Windows pipe impersonation, rejecting a lookalike service PID, suspend cancellation, stale power generations, deadline outcomes and service disposal.
- Acknowledgment relay ordering and pipe-disconnect cancellation even when recognition is silent.
- **11 deployment checks:** owner/access rules for retained data and executable files, reparse-point rejection, and atomic protected-directory creation with rejection of an existing path.
- Packaged Python import isolation, model hashes/loading and actual blank-frame inference; **25 real subprocess/service checks** cover accepted/rejected legacy/circular profiles, model-only prewarm, one-shot completion, standby leases/faults, suspend cleanup, replacement and Job Object exit.
- Native Settings build/smoke coverage, alongside 63 rendering/resource regression cases.

The packaged-runtime checks run as the development user, not LocalSystem. The authorized **0.8.0 administrator upgrade is installed**: the existing encrypted account link and other credential-provider registrations were unchanged, 19 installed binaries/backend/model files matched, x64 registration and automatic LocalSystem service startup passed, and all 25 checks passed against the installed runtime as the elevated development user. No restart was required. Actual local-account automatic unlock was confirmed only with the earlier build. The matrix below still requires current-build validation, including physical enrollment/unlock, long sleep, reboot, Microsoft accounts, multi-user races, failure cases and presentation attacks:

| VM scenario | Expected result |
|---|---|
| Link the signed-in local account; repeat with a personal Microsoft account | Correct password links only the caller SID; wrong password, another user's password, PIN and incomplete/photo enrollment fail |
| Lock and submit Viso; repeat after reboot | Service opens the camera from session 0; fresh matched blink/open sequence results in Windows authentication |
| Cancel, deselect tile, switch users, or disconnect camera during scan | No serialization from the canceled operation; worker exits; another scan can acquire camera |
| Two Windows users enrolled/linked | Separate records and selected-account matching; one face cannot authorize another account |
| Disable/relink while verification is in progress | Old revision cannot release a credential; relinking cannot undo a concurrent disable |
| Change local/MSA password | Old saved credential fails Windows authentication; normal sign-in and relinking restore Viso |
| Offline cached Microsoft-account sign-in | Behavior matches Windows' cached-password availability |
| Worker/service stopped, failed, or restarted; sleep/resume | Ordinary Windows options remain usable; a new Viso scan requires fresh verification |
| Leave Viso selected, sleep for 30+ minutes, wake interactively | One automatic fresh scan without pressing the arrow; pre-sleep success cannot serialize |
| Repeat with hibernate / supported Modern Standby / display-off only | One scan on interaction/display return; no automatic retry loop after failure |
| Automatic maintenance wake without user interaction | Camera remains off; ordinary sign-in options remain available |
| Leave unused standby idle for over 60 seconds | Worker exits; next selected scan may load models cold; session lock can prewarm again |
| Install, uninstall, reboot, reinstall with/without retained links | Only Viso registrations/files change; locked DLL cleanup completes after reboot |
| Photo/video/virtual camera presentation and varied lighting/glasses | Record false accepts/rejects; existing blink tests do not establish anti-spoofing effectiveness |

See [Windows sign-in setup](windows-signin.md) for commands and account requirements.

## Historical browser verification

The [0.3–0.5 records](history/browser-validation.md) now live in history. The [isolated browser package on `test`](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md) retains its four sampler tests and build commands. Those tests do not validate the archived five-pose guidance against the current circular backend.

## Test fixture sources

`scripts/download_test_fixtures.py` fetches `obama.jpg`, `obama2.jpg`, and `biden.jpg` from the examples in `ageitgey/face_recognition`, pinned to commit `9f3061aaeed9a8756d2c970f5dfe066617a8281d`. They are test inputs only and are not included in the app distribution or user enrollment.
