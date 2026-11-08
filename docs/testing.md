# Testing Viso

## Initial test environment

Run `scripts/start.ps1 -Ephemeral`. The profile lives only in the Python process. The lock screen in the interface is a simulation. Setup dependencies are isolated in `.venv` and `node_modules`.

The default launch without `-Ephemeral` keeps one encrypted test profile in `.viso/profile.dpapi`. The startup terminal and **Profile storage** metric identify the active mode.

## Automated checks

```powershell
.\scripts\test.ps1
```

This downloads three optional public example portraits into the git-ignored `tests/.fixtures/`, runs Python's unittest suite against the actual ONNX models, and builds/type-checks the frontend. Test storage uses temporary directories or explicit memory-only profiles.

Coverage includes:

- Different photos of the same person match; another identity does not.
- Empty frames, multiple faces, invalid images, and mixed-identity enrollment are rejected.
- Open → closed → reopened eye sequence, final open-eye confirmation, wink/closed/unknown rejection, stale evidence, blink timeout, and attempt expiry.
- Guided pose sequence, steady holds, wrong angles/person, closed eyes, expiry, cancellation, and finish-only persistence.
- Real MediaPipe eye measurements and mirrored yaw sign on fixtures; repeated matching photos never unlock.
- Client-supplied eye/blink/pose claims cannot override backend measurements.
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
| Enroll via webcam | Center, left, right, up, down prompts; each measured angle held ~0.5 s before capture |
| Stay facing forward at the left/right prompt | The next pose is not captured |
| Close either eye / show a different person during enrollment | Current hold resets; sample is not captured |
| Cancel enrollment / Escape / hide tab mid-enrollment | Incomplete samples discarded; no profile saved |
| Inspect a frame | Face box and timing appear; simulated state is unchanged |
| Match enrolled face | Prompt for a blink; unlock only after both eyes reopen and remain open |
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

Version 0.2 passed 36 backend tests with the pinned MediaPipe 0.10.32 package, the TypeScript/production build, and Python dependency checks. Real-model fixtures verify same-person similarity, different-person rejection, open-eye measurements, mirrored pose, and repeated-photo blocking. Injected observations test the complete blink and five-pose state machines deterministically; they do not establish real-camera accuracy.

Browser checks verified photo rejection despite similarity 1.000, a portrait-backed synthetic camera reaching the blink prompt and expiring without unlocking, and automatic neutral-pose capture followed by the left-turn prompt. Canceling guided enrollment removed the overlay, left no saved profile, and made the canceled finish endpoint return 404. This synthetic source exercises capture/UI plumbing; reloading the test page restored native camera APIs and released the test stream.

Physical webcam permissions, eyelid detection across lighting/glasses, natural blink capture, and directional calibration still need testing with your camera. Start with the scenarios above. Record missed blinks and closed-eye false positives separately from identity mismatch. This is a functional test bench, not an anti-spoofing benchmark.

## Test fixture sources

`scripts/download_test_fixtures.py` fetches `obama.jpg`, `obama2.jpg`, and `biden.jpg` from the examples in `ageitgey/face_recognition`, pinned to commit `9f3061aaeed9a8756d2c970f5dfe066617a8281d`. They are test inputs only and are not included in the app distribution or user enrollment.
