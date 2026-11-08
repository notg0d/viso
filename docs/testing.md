# Testing Viso

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
- Neutral-hold calibration, relative target feedback, and mandatory recentering between directional samples.
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
| Enroll via webcam | Follow the directional light; ring sectors fill after ~0.35 s holds, return to center between turns |
| Lift chin during enrollment/unlocking | Eyes remain readable with small turns and gaze toward camera; bounded calibration may show Tilt adjusted |
| Tilt upward without blinking | Prompt remains; head movement alone cannot satisfy a blink |
| Blink / wink / close both eyes while chin is raised | Bilateral blink can progress; wink/closed final eyes cannot unlock or supply enrollment samples |
| Finish guided enrollment | Ticks merge into a solid ring before the overlay clears; profile saved once |
| Reduced-motion preference | Static ring, progress, and text guidance; no moving light sweeps |
| Stay facing forward at the left/right prompt | The next pose is not captured |
| Close either eye / show a different person during enrollment | Current hold resets; sample is not captured |
| Cancel enrollment / Escape / minimize mid-enrollment | Incomplete samples discarded; no profile saved |
| Inspect an image | Face quality, eye state, similarity, and timing appear; simulated state is unchanged |
| Match enrolled face | Prompt for a blink; unlock only after both eyes reopen and remain open |
| Shift/turn slightly while scanning | Small tracked score dips briefly pause; a fresh passing match resumes within 200 ms |
| Move slightly after blinking | A brief score dip restarts open-eye confirmation, rather than immediately requiring another blink |
| Move out of frame / switch people / keep producing weak matches | Challenge resets; recovery cannot extend itself or authorize unlock |
| Re-enroll with v0.4 | Recognition metric shows multi-angle matching; old profiles keep centroid matching until re-enrolled |
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
| Switch page, minimize, or lock Windows | Camera released; scan canceled |
| Deny camera access / unplug camera | Actionable error; image testing still available |
| Change threshold | Prior attempt invalidated; the next attempt uses the new threshold |
| Delete enrollment | Profile removed, attempts revoked, enrollment available again |
| Restart in ephemeral mode | No profile restored |
| Restart in persistent mode | Same Windows user restores encrypted profile |
| Recognition worker exits unexpectedly | Native error appears; close and reopen Viso |

## Development verification

The current native/sign-in implementation passes **94 backend tests** (including three one-shot sign-in worker tests) plus the native C#/WPF build and smoke check. The native smoke check opens all five pages, captures actual WPF raster output, checks minimum window size and reduced-motion completion, verifies button gating, runs real blank-frame inference, and performs real image enrollment → matching-photo rejection → deletion through the C# process client. The latter also verifies a Unicode profile name. Camera capture is not started by automated visual checks. Physical-webcam enrollment, driver disconnect behavior, and natural blink timing still need a live-camera check.

Native rendering regressions are recorded in `test-results/native/rendering.json`: 30 pixel checks cover circular preview fill/mirroring with 4:3, 16:9, and portrait inputs, plus visible profile-name text in editable and active-enrollment states. They run at 1040/780 window widths and 100%/150%/200% raster scales. Full-window captures also exercise the shared text-box template and a decoded portrait inside the enrollment ring.

## Windows sign-in validation

```powershell
.\scripts\build-signin.ps1 -Test
.\scripts\test-signin-runtime.ps1
```

The component tests do not install a provider/service, open a camera, or use real account passwords. Verified coverage:

- C++ `/W4 /WX` provider build and actual DLL COM activation without registry registration.
- Local and Microsoft-account credential packing/decryption for both logon and unlock, including Unicode synthetic passwords; unsupported scenarios and empty credentials rejected.
- V2 user/SID association, local/MSA filtering, preserving default provider selection, and withholding serialization without verification.
- **43 C# service/protocol checks:** bounded framing, malformed UTF-8, account-name rules, DPAPI round trips, record/filename SID binding, current revision checks, pending-link revocation after unlink/relink, real Windows pipe impersonation, and rejecting a lookalike service PID.
- Acknowledgment relay ordering and pipe-disconnect cancellation even when recognition is silent.
- **11 deployment checks:** owner/access rules for retained data and executable files, reparse-point rejection, and atomic protected-directory creation with rejection of an existing path.
- Packaged Python import isolation, model hashes/loading and actual blank-frame inference; **3 real subprocess checks** cover accepted/rejected synthetic profiles and Job Object cleanup through the service's worker class.
- Native Settings build/smoke coverage, alongside the existing 30 rendering regression checks.

The packaged-runtime checks run as the development user, not LocalSystem. Administrator installation/uninstallation, real `LogonUser` password validation, and the following integrated scenarios remain **unverified**:

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
| Install, uninstall, reboot, reinstall with/without retained links | Only Viso registrations/files change; locked DLL cleanup completes after reboot |
| Photo/video/virtual camera presentation and varied lighting/glasses | Record false accepts/rejects; existing blink tests do not establish anti-spoofing effectiveness |

See [Windows sign-in setup](windows-signin.md) for commands and account requirements.

## Historical browser verification

The verification below documents earlier releases, not the current native UI.

Version 0.5 passed **81 backend tests, 4 camera-sampler tests, and the TypeScript/production build** with MediaPipe 0.10.32. The 19 added tilt regressions cover bounded head-local eye geometry, invalid rotations, chin-up open-eye calibration, pose-bound relative and absolute blink evidence, either-eye closure, identity/gap resets, exclusion of inferred/cached frames from calibration, and effective API eye-state reporting in both flows. The existing real-model portrait checks still pass. Controlled geometry and injected observations do not establish physical-webcam accuracy; repeat the chin-up open/blink/wink scenarios on the actual camera.

The v0.5 production-browser check used a synthetic canvas stream and mocked enrollment responses. DOM and animation checks verified 80 ticks, four equal 20-tick sectors, all four sweep/turn-band directions, recentering, capture progress, cancellation, a single save, and completion cleanup after about 1.1 seconds. Escape also cleared the completion timer. Constrained 360/430/800/1280-pixel layouts stayed within the viewport; the small-screen ring was adjusted to give the instruction text more room. Forcing the reduced-motion stylesheet branch disabled ring/ribbon animation while keeping progress visible. Pixel screenshots were unavailable because the desktop screenshot tool could not capture the visible window, so visual appearance still needs a manual check. Reloading removed the mocks, released the synthetic stream, and restored native camera APIs; the reloaded page reported no console errors.

Version 0.4 passed **62 backend tests, 4 camera-sampler tests, and the TypeScript/production build** with the pinned MediaPipe 0.10.32 package. Real-model fixtures verify same-person similarity, different-person rejection, open-eye measurements, mirrored pose, and repeated-photo blocking. Injected observations test the complete blink and five-pose state machines deterministically, including a 50 ms sampled eye closure delivered in a batch; they do not establish real-camera accuracy.

A same-machine v0.3 comparison with v0.2 on three 960-pixel portraits measured median full-inference times of approximately **125→48 ms, 76→39 ms, and 69→36 ms**, preserving open-eye classifications on all three. These are local measurements, not a hardware-independent benchmark. The v0.3 synthetic-camera browser run exercised the buffered HTTP pipeline for 20 seconds without failed requests; it delivered about 15 sampled frames/s through the desktop browser transport, and fast eye-only frames took about 27 ms. The fixed portrait still expired without unlocking.

Browser checks verified photo rejection despite similarity 1.000, a portrait-backed synthetic camera reaching the blink prompt and expiring without unlocking, and automatic neutral-pose capture followed by the left-turn prompt. Canceling guided enrollment removed the overlay, left no saved profile, and made the canceled finish endpoint return 404. This synthetic source exercises capture/UI plumbing; reloading the test page restored native camera APIs and released the test stream.

The initial physical-camera feedback reported sluggish scanning, missed normal blinks, and unreliable enrollment. Version 0.3 addresses those paths with buffered capture, faster detection/eye tracking, relative blink closure, averaged enrollment holds, and smaller calibrated targets. Re-enroll and repeat the manual scenarios on the physical webcam to validate the changes across lighting/glasses. Record missed blinks and closed-eye false positives separately from identity mismatch. This is a functional test bench, not an anti-spoofing benchmark.

Follow-up feedback confirmed faster scanning but reported delays/failures with small head movements. Version 0.4 retains enrollment views, follows small box movements, and briefly pauses on borderline open-eye matches. The real-model motion checks rotate portraits by ±3–6°, translate by 8–16 pixels, and scale by 0.95–1.05: the same identity still passes, and the other identity stays below threshold. Deterministic recovery tests verify that weak final frames cannot unlock and that recovery cannot extend its deadline. Natural head turns and blinks still need validation on the physical webcam after re-enrolling for multi-view matching.

The v0.4 browser check enrolled two reference views and exercised a translated/rotated synthetic portrait for 20 seconds. Matching stayed above the default threshold (approximately 0.895–0.935), fast eye tracking remained active, and the attempt expired without unlocking or failed requests. Separate rotation probes found a blink coefficient changing from 0.270 to 0.304 on an open-eye portrait, motivating the narrow near-open pause. Its regression tests require full identity, bound the pause to 200 ms, reject winks/low EAR and combined weak identity, and require a new strict-open interval before unlocking. The browser fixture was deleted and native camera APIs restored afterward.

## Test fixture sources

`scripts/download_test_fixtures.py` fetches `obama.jpg`, `obama2.jpg`, and `biden.jpg` from the examples in `ageitgey/face_recognition`, pinned to commit `9f3061aaeed9a8756d2c970f5dfe066617a8281d`. They are test inputs only and are not included in the app distribution or user enrollment.
