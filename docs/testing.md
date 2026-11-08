# Testing Viso

## Initial test environment

Run `scripts/start.ps1 -Ephemeral`. The profile lives only in the Python process. The lock screen in the interface is a simulation. Setup dependencies are isolated in `.venv` and `node_modules`.

The default launch without `-Ephemeral` keeps one encrypted test profile in `.viso/profile.dpapi`. The startup terminal and **Profile storage** metric identify the active mode.

## Automated checks

```powershell
.\scripts\test.ps1
```

This downloads three optional public example portraits into the git-ignored `tests/.fixtures/`, runs Python's unittest suite against the actual ONNX models, runs camera-sampler tests with Node's built-in test runner, and builds/type-checks the frontend. Test storage uses temporary directories or explicit memory-only profiles.

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
- New scans invalidate old scans; profile deletion revokes active scans.
- DPAPI persistence, encrypted bytes, corrupted-profile handling, and deletion.
- Loopback API token, origin/host validation, malformed/oversized requests, and static-path traversal.

For the backend suite alone:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Real-model tests are marked skipped if the optional image fixtures have not been downloaded. `test.ps1` fetches them before running so the full suite executes.

## Manual scenarios

| Scenario | Expected behavior |
|---|---|
| Start with a fresh profile | Unlock button disabled until enrollment and an input are ready |
| Enroll via webcam | Move the dot into each target; hold ~0.35 s, return to center between turns |
| Stay facing forward at the left/right prompt | The next pose is not captured |
| Close either eye / show a different person during enrollment | Current hold resets; sample is not captured |
| Cancel enrollment / Escape / hide tab mid-enrollment | Incomplete samples discarded; no profile saved |
| Inspect a frame | Face box and timing appear; simulated state is unchanged |
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
| Switch page/input mode or hide tab | Camera tracks stopped; scan canceled |
| Deny camera access / unplug camera | Actionable error; image testing still available |
| Change threshold | Prior attempt invalidated; the next attempt uses the new threshold |
| Delete enrollment | Profile removed, attempts revoked, enrollment available again |
| Restart in ephemeral mode | No profile restored |
| Restart in persistent mode | Same Windows user restores encrypted profile |
| Restart service with an open UI | Refresh/reconnect before continuing mutations |

## Development verification

Version 0.4 passed **62 backend tests, 4 camera-sampler tests, and the TypeScript/production build** with the pinned MediaPipe 0.10.32 package. Real-model fixtures verify same-person similarity, different-person rejection, open-eye measurements, mirrored pose, and repeated-photo blocking. Injected observations test the complete blink and five-pose state machines deterministically, including a 50 ms sampled eye closure delivered in a batch; they do not establish real-camera accuracy.

A same-machine v0.3 comparison with v0.2 on three 960-pixel portraits measured median full-inference times of approximately **125→48 ms, 76→39 ms, and 69→36 ms**, preserving open-eye classifications on all three. These are local measurements, not a hardware-independent benchmark. The v0.3 synthetic-camera browser run exercised the buffered HTTP pipeline for 20 seconds without failed requests; it delivered about 15 sampled frames/s through the desktop browser transport, and fast eye-only frames took about 27 ms. The fixed portrait still expired without unlocking.

Browser checks verified photo rejection despite similarity 1.000, a portrait-backed synthetic camera reaching the blink prompt and expiring without unlocking, and automatic neutral-pose capture followed by the left-turn prompt. Canceling guided enrollment removed the overlay, left no saved profile, and made the canceled finish endpoint return 404. This synthetic source exercises capture/UI plumbing; reloading the test page restored native camera APIs and released the test stream.

The initial physical-camera feedback reported sluggish scanning, missed normal blinks, and unreliable enrollment. Version 0.3 addresses those paths with buffered capture, faster detection/eye tracking, relative blink closure, averaged enrollment holds, and smaller calibrated targets. Re-enroll and repeat the manual scenarios on the physical webcam to validate the changes across lighting/glasses. Record missed blinks and closed-eye false positives separately from identity mismatch. This is a functional test bench, not an anti-spoofing benchmark.

Follow-up feedback confirmed faster scanning but reported delays/failures with small head movements. Version 0.4 retains enrollment views, follows small box movements, and briefly pauses on borderline open-eye matches. The real-model motion checks rotate portraits by ±3–6°, translate by 8–16 pixels, and scale by 0.95–1.05: the same identity still passes, and the other identity stays below threshold. Deterministic recovery tests verify that weak final frames cannot unlock and that recovery cannot extend its deadline. Natural head turns and blinks still need validation on the physical webcam after re-enrolling for multi-view matching.

The v0.4 browser check enrolled two reference views and exercised a translated/rotated synthetic portrait for 20 seconds. Matching stayed above the default threshold (approximately 0.895–0.935), fast eye tracking remained active, and the attempt expired without unlocking or failed requests. Separate rotation probes found a blink coefficient changing from 0.270 to 0.304 on an open-eye portrait, motivating the narrow near-open pause. Its regression tests require full identity, bound the pause to 200 ms, reject winks/low EAR and combined weak identity, and require a new strict-open interval before unlocking. The browser fixture was deleted and native camera APIs restored afterward.

## Test fixture sources

`scripts/download_test_fixtures.py` fetches `obama.jpg`, `obama2.jpg`, and `biden.jpg` from the examples in `ageitgey/face_recognition`, pinned to commit `9f3061aaeed9a8756d2c970f5dfe066617a8281d`. They are test inputs only and are not included in the app distribution or user enrollment.
