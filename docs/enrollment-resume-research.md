# Circular enrollment, resource ownership and wake recovery

[← Documentation](README.md) · [Current validation](testing.md) · [Measured performance](performance.md)

The findings below describe the **pre-0.8 implementation at research time**, followed by implementation/deployment records. Statements about missing behavior are historical, not the current architecture.

Research performed 2026-11-11, before implementation. The search integration returned HTTP 402; the primary documents below were fetched directly. No camera, account passwords or real biometric profiles were used for research/automated validation.

## Findings and decisions

1. **Enrollment:** Apple documents two gentle circular head movements, not five isolated turns. Viso currently stores five averaged holds, has no diagonal targets, and requires recentering between turns. Use a neutral calibration followed by two eight-direction circuits (17 averaged views, at least 51 distinct open-eye observations). Keep modest yaw/pitch, quality checks, identity consistency, timing checks and bounded motion. Recenter only between circuits. A stationary frontal image cannot satisfy the direction coverage. Store embeddings, not images.
2. **Recognition:** More frames alone do not establish higher accuracy. Pose coverage and averaging can reduce noisy/underrepresented views, but increasing the number of independent match opportunities can also increase false accepts. Keep the existing 0.55 sign-in threshold and fresh blink/open-eye challenge. Require two *different pose groups* to support a multi-view override: repeated views of one direction must not supply two votes. Preserve legacy five-view profiles. Physical head-turn and impostor testing is still necessary; do not claim a quantified accuracy gain.
3. **Security boundary:** Apple's TrueDepth uses depth/IR and Secure Enclave processing. Viso uses experimental RGB recognition. Copying the enrollment gesture does not confer Face ID anti-spoofing or false-accept performance. No automatic online template learning and no relaxed liveness checks.
4. **Memory:** The raw camera deque is already bounded to six frames (up to 16.6 MB at 960×960 RGB). The recognition hot path nevertheless rebuilds/normalizes every stored vector each frame; compile one small contiguous float32 matcher per profile instead. Successful desktop IPC calls leave 30-second delay timers alive; cancel losing timers. The ring allocates 80 brushes/pens on every render; cache frozen drawing resources. Stop idle preview polling when the camera is off. Service model-only prewarm currently lives indefinitely and never observes initialization failure; retire unused/faulted standby processes with a bounded lease, prewarm on session lock, and preserve one-shot worker isolation. Do not force GC or trim working sets: that hides allocations and can increase wake latency.
5. **Wake bug:** `Credential.attempted` stays true after timeout; a selected tile can survive suspend without a new `SetSelected`. No provider power notifications or service `OnPowerEvent` handler exist. Register explicit suspend/resume and display-state notifications on the provider's message-only UI window. On suspend/display-off, revoke credentials, generations and callbacks. Resume interaction/display-on rearms a selected tile once, never a general retry loop. Automatic maintenance wake alone must not open the camera. Service suspend invalidates connections and destroys workers; generation checks prevent pre-suspend recognition from releasing credentials. Desktop power events cancel operations, release preview/camera resources and leave the simulator locked.

## Primary sources

- [Apple: set up/use Face ID](https://support.apple.com/en-us/108411) — two circular scans, gentle motion, accessibility considerations.
- [Apple: Face ID advanced technology](https://support.apple.com/en-us/102381) — depth/IR, encrypted templates, attention and anti-spoofing distinction.
- [OpenCV: DNN face detection/recognition](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html) — aligned SFace features and cosine comparisons; benchmark thresholds vary by dataset and are not application-specific guarantees.
- [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python) — measured landmarks, blendshapes and pose matrices; synchronous processing vs frame-dropping livestream modes. Retain the current synchronous evidence lane.
- [Microsoft: RegisterSuspendResumeNotification](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registersuspendresumenotification) — explicit window/callback registration and unregister ownership.
- [Microsoft: PBT_APMRESUMEAUTOMATIC](https://learn.microsoft.com/en-us/windows/win32/power/pbt-apmresumeautomatic) — every resume, not evidence of user presence; interactive resume follows activity.
- [Microsoft: Power Setting GUIDs](https://learn.microsoft.com/en-us/windows/win32/power/power-setting-guids) — session display state for interactive apps; console display state for session 0; stop rendering while display is off.
- [Microsoft: ServiceBase.OnPowerEvent](https://learn.microsoft.com/en-us/dotnet/api/system.serviceprocess.servicebase.onpowerevent?view=netframework-4.8.1) — enable `CanHandlePowerEvent` and override power handling.
- [Microsoft: Task.Delay](https://learn.microsoft.com/en-us/dotnet/api/system.threading.tasks.task.delay?view=netframework-4.8.1) — cancellable delay overloads available on .NET Framework 4.8.

## Validation gates

- Deterministic two-circuit completion, diagonal coverage, duplicate/stale/closed-eye/wrong-identity rejection, cancellation, encrypted roundtrip, strict new/legacy profile validation and same-pose vote rejection.
- Full existing identity/blink suite; native render checks at small/HiDPI sizes and reduced motion.
- Actual provider DLL build/activation, synthetic power/display notifications, one restart per wake, no stale credential serialization, deselection/teardown cancellation, one-use original expiry.
- Service power generation/disconnect checks, standby cleanup, deadline failures and isolated-runtime validation.
- Repeatable synthetic matcher timing/allocation comparisons. Live long sleep, hibernate/Modern Standby and physical enrollment are manual gates. Building is not installing: installed Program Files service/provider/runtime must be upgraded separately with administrator consent.

## Implementation and automated results

Implemented on `test` as 0.8.0. Verified 110 Python tests, actual provider DLL activation/power regressions, 59 C# service/protocol checks, 11 deployment checks, 25 packaged service-to-Python checks and native WPF smoke checks with 36 raster/resource cases. Actual first/second-circle, reduced-motion and minimum-window screenshots were inspected. Power registration remains active during a fresh credential's short `UnAdvise`/`Advise` submission handoff, so suspend can revoke it even without a UI event sink.

The compiled 17-view matcher measured 536.12→21.63 µs (~24.8×) in the synthetic component comparison and occupies 9,288 array bytes. One warmed model-only worker in the pre-install packaged-runtime run measured ~165 MiB working set / ~459 MiB private memory; unused residency is now bounded by a 60-second lease. [Exact measurements and limitations](performance.md).

During implementation/automated validation, no physical camera, account relinking, commit or push was performed. The authorized installation is recorded separately below. Re-enrollment is needed for circular coverage; relinking explicitly copies that new profile into an installed service. Higher biometric accuracy, replay resistance and physical long-sleep recovery remain unverified.

## Authorized deployment verification

On 2026-11-11, the user authorized uninstalling the old sign-in components and installing 0.8.0. The administrator upgrade completed without a restart using `-KeepAccountLinks`. The existing encrypted account record was unchanged, other Windows credential-provider registrations were unchanged, and all 19 checked installed binaries/backend/model files matched the validated build. The x64 provider registration and automatic LocalSystem service startup were verified. The installed private runtime passed isolated imports/model checksums/blank-frame inference and all 25 service-to-Python checks, run as the elevated development user rather than LocalSystem. The desktop executable was rebuilt as 0.8.0.0. This deployment did not test actual authentication, physical enrollment or long sleep.

## Follow-up desktop hotfix

The user then reported an Unlock test crash. Windows' runtime log and a new native regression both identified an out-of-range pen lookup when a valid identity streak exceeds the minimum frame count before the elapsed-time gate completes. Desktop 0.8.1 bounds finite visual progress and rendered intensity without changing backend evidence or authentication requirements. The updated suite passed 111 Python tests and 63 native raster/resource cases; actual high-streak/static/animated and circular screenshots were inspected. The production desktop was rebuilt. Installed 0.8.0 sign-in components, account links and enrollment were not changed by the hotfix. See [hotfix verification](testing.md#081-desktop-unlock-rendering-hotfix).
