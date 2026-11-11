# Earlier browser validation

[← Documentation](../README.md) · [Current validation](../testing.md) · [Historical browser package on `test`](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md)

The records below document earlier releases, not the current native UI. Controlled geometry, injected observations, mocked browser responses, and portrait-backed synthetic cameras do not establish physical-webcam accuracy or anti-spoofing effectiveness.

## Version 0.5

Version 0.5 passed **81 backend tests, 4 camera-sampler tests, and the TypeScript/production build** with MediaPipe 0.10.32. The 19 added tilt regressions cover bounded head-local eye geometry, invalid rotations, chin-up open-eye calibration, pose-bound relative and absolute blink evidence, either-eye closure, identity/gap resets, exclusion of inferred/cached frames from calibration, and effective API eye-state reporting in both flows. The existing real-model portrait checks still passed. Chin-up open/blink/wink scenarios still needed repetition on the actual camera.

The v0.5 production-browser check used a synthetic canvas stream and mocked enrollment responses. DOM and animation checks verified 80 ticks, four equal 20-tick sectors, all four sweep/turn-band directions, recentering, capture progress, cancellation, a single save, and completion cleanup after about 1.1 seconds. Escape also cleared the completion timer. Constrained 360/430/800/1280-pixel layouts stayed within the viewport; the small-screen ring was adjusted to give the instruction text more room. Forcing the reduced-motion stylesheet branch disabled ring/ribbon animation while keeping progress visible. Pixel screenshots were unavailable because the desktop screenshot tool could not capture the visible window, so visual appearance still needed a manual check. Reloading removed the mocks, released the synthetic stream, and restored native camera APIs; the reloaded page reported no console errors.

## Version 0.4

Version 0.4 passed **62 backend tests, 4 camera-sampler tests, and the TypeScript/production build** with the pinned MediaPipe 0.10.32 package. Real-model fixtures verify same-person similarity, different-person rejection, open-eye measurements, mirrored pose, and repeated-photo blocking. Injected observations test the complete blink and five-pose state machines deterministically, including a 50 ms sampled eye closure delivered in a batch; they do not establish real-camera accuracy.

Follow-up feedback confirmed faster scanning but reported delays/failures with small head movements. Version 0.4 retained enrollment views, followed small box movements, and briefly paused on borderline open-eye matches. Real-model motion checks rotated portraits by ±3–6°, translated by 8–16 pixels, and scaled by 0.95–1.05: the same identity still passed, and the other identity stayed below threshold. Deterministic recovery tests verified that weak final frames could not unlock and that recovery could not extend its deadline. Natural head turns and blinks still needed validation after re-enrolling for multi-view matching.

The v0.4 browser check enrolled two reference views and exercised a translated/rotated synthetic portrait for 20 seconds. Matching stayed above the default threshold (approximately 0.895–0.935), fast eye tracking remained active, and the attempt expired without unlocking or failed requests. Separate rotation probes found a blink coefficient changing from 0.270 to 0.304 on an open-eye portrait, motivating the narrow near-open pause. Its regression tests require full identity, bound the pause to 200 ms, reject winks/low EAR and combined weak identity, and require a new strict-open interval before unlocking. The browser fixture was deleted and native camera APIs restored afterward.

## Version 0.3 and initial feedback

A same-machine v0.3 comparison with v0.2 on three 960-pixel portraits measured median full-inference times of approximately **125→48 ms, 76→39 ms, and 69→36 ms**, preserving open-eye classifications on all three. These are local measurements, not a hardware-independent benchmark. The v0.3 synthetic-camera browser run exercised the buffered HTTP pipeline for 20 seconds without failed requests; it delivered about 15 sampled frames/s through the desktop browser transport, and fast eye-only frames took about 27 ms. The fixed portrait still expired without unlocking.

Browser checks verified photo rejection despite similarity 1.000, a portrait-backed synthetic camera reaching the blink prompt and expiring without unlocking, and automatic neutral-pose capture followed by the left-turn prompt. Canceling guided enrollment removed the overlay, left no saved profile, and made the canceled finish endpoint return 404. This synthetic source exercises capture/UI plumbing; reloading the test page restored native camera APIs and released the test stream.

Initial physical-camera feedback reported sluggish scanning, missed normal blinks, and unreliable enrollment. Version 0.3 addressed those paths with buffered capture, faster detection/eye tracking, relative blink closure, averaged enrollment holds, and smaller calibrated targets. Physical retesting across lighting/glasses remained necessary; missed blinks and closed-eye false positives should be recorded separately from identity mismatch. This was a functional test bench, not an anti-spoofing benchmark.

## Fixture provenance

The public portrait sources remain documented in [current testing](../testing.md#test-fixture-sources) and the [shared fixture index on `test`](https://github.com/notg0d/viso/blob/test/tests/README.md). The archived five-pose frontend has not been ported to the current circular backend.
