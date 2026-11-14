# Architecture

[← Documentation](README.md) · [Security & privacy](security.md) · [Development](development.md)

## Current: native Windows application

```text
Viso.exe — C# / WPF, .NET Framework 4.8 (x64)
  ├─ Embedded XAML, native window/control/file-dialog stack
  ├─ Your face / Unlock test / Image lab / Activity / Settings
  ├─ Eased transforms, 80-tick enrollment ring, reduced-motion handling
  └─ UTF-8 JSON over redirected child-process stdin/stdout
                    │ private pipes, no listening port
Python native worker (backend/viso/native.py)
  ├─ DirectShow-first camera thread, bounded startup fallback, six-frame queue
  ├─ 15 Hz preview events, coalesced before WPF presentation
  ├─ Serialized recognition and enrollment/attempt commands
  ├─ Explicit native prompt acknowledgment discards pre-prompt camera frames
  └─ Existing SandboxService, ONNX/MediaPipe models and DPAPI store
```

`scripts/start.ps1` builds and launches the native app. The installed Windows C# compiler builds the x64 executable without a new runtime dependency or SDK. The process client drains diagnostics, bounds request timeouts, fails pending requests on worker exit, and shuts down the worker on window close. Camera access is opt-in and released on page changes, completion, minimizing, session lock, and close. Cancellation uses a UI generation counter as well as worker-owned session revocation; late responses cannot advance a newer operation.

The native worker emits `ready` when its command transport/profile store is available, then initializes models on a background thread and emits `engine_ready` (including on initialization failure). Status exposes separate `loading` and `ready` engine flags; inference actions remain gated until models load successfully. WPF device enumeration runs off the UI thread and overlaps worker startup. Shutdown waits for initialization before closing the engine.

[Release ZIPs](releases.md) and the [complete installer](installer.md) include a private `runtime/python.exe`; source checkouts use `.venv/Scripts/python.exe` as the fallback. Both launch `backend/run_native.py` with `-I -B -u` and an explicit `--data-dir`: only the payload root is explicitly added to Python's import path, environment/user-site overrides are ignored, and bytecode caches are disabled. Python reads verified model bytes before passing them to OpenCV/MediaPipe, avoiding narrow Windows filename APIs for Unicode paths.

UI preferences (`desktop.json`) are separate from face data (`profile.dpapi`). Installed desktop state lives in the current user's `%LOCALAPPDATA%\Viso`; source/portable copies retain `.viso/`. `AppPaths` selects the directory, and preferences, worker storage and account-link import use that same choice. There is no automatic profile migration. Source-build session exports add allowlisted runtime/camera diagnostics to messages and times, excluding images/vectors, credentials, profile metadata and raw diagnostic exceptions. Existing event text can contain a profile name or an error path and needs review before sharing. The DPAPI profile format is unchanged. The private pipes are a desktop transport, not a privileged pre-login authentication boundary.

The complete installer verifies compiler-pinned helper/manifest hashes and every file in a fresh protected staging tree, then initializes the bundled runtime before stopping an existing service. It swaps directories with a protected backup and atomically written recovery journal, preserves account records, starts the automatic LocalSystem service and registers only Viso. Inno owns shortcuts/uninstall registration; the deployment helper owns payload installation/recovery/removal. Setup requires experimental sign-in consent, performs no enrollment/account linking/camera capture, and refuses locked upgrades or pending Viso file deletion rather than silently restarting. See [installer lifecycle and open validation gates](installer.md).

### Optional native Windows sign-in

```text
Viso Settings (current user) ── link/status/unlink ─┐
                                                │ bounded local named pipe
LogonUI → VisoCredentialProvider.dll ── verify ───┤ Viso.SignIn.v1
                                                ▼
VisoSignInService.exe (LocalSystem, Program Files)
  ├─ Impersonated caller SID; LogonUI-only credential release
  ├─ Local/Microsoft account password validation through LogonUser
  ├─ Per-SID machine-DPAPI records in protected ProgramData
  ├─ Revision-checked commit/release and serialized vault mutations
  └─ One prewarmed Job-contained Python process (-I -B), consumed once per scan
        ├─ Fixed 0.55 match threshold; current-model camera profile
        ├─ Service-owned shared Camera capture and fresh blink acknowledgment
        └─ Acceptance → one-use local/MSA Windows credential serialization
```

`signin/Provider` implements V2 user-associated tiles for local and personal Microsoft accounts, for logon and workstation unlock. Linked account-record presence is a default-selection hint; the service still validates the full account binding. Tile selection starts one background scan. A message-only window dispatches status/prompt callbacks on LogonUI's apartment, and only an accepted credential triggers `CredentialsChanged` plus default auto-serialization. Cancellation invalidates generation-tagged pending UI updates and pipe work. Failed scans do not automatically restart until a new selection; the arrow remains an explicit retry. Local credentials use `CredProtectW` and a packed `KERB_INTERACTIVE_UNLOCK_LOGON`; Microsoft accounts use `CRED_PACK_PROTECTED_CREDENTIALS | CRED_PACK_ID_PROVIDER_CREDENTIALS`. Windows' Negotiate authentication package makes the final authentication decision.

The unreleased startup update retains one model-only standby according to Windows session state, rather than a timed lease. It keeps models while the console or another connected session needs sign-in. Unknown state permits retention, never authentication. Sign-in releases the standby when no other connected session needs it; suspend and service disposal release all workers. Revision-guarded state queries cannot restore an obsolete standby after a newer notification.

The standby reads each model once and passes those verified bytes to OpenCV/MediaPipe. Blank-input inference initializes native execution before readiness, without a profile, eye calibration or camera access. Initialization has a 30-second deadline; failed preparation retires the standby. Each scan consumes and destroys its worker. A replacement loads only while sign-in is needed and no worker is active. Cold requests report model loading immediately. One camera semaphore, cancellable attempt deadlines, Job containment and vault revision checks still apply.

Logon, unlock, logoff and disconnect increment the affected session's verification generation and close its worker and result pipe. This also cancels pending Viso results when another provider signs the user in. Other connected sessions retain their own verification generation. Previously delivered credentials remain subject to the provider's one-use rules.

The provider registers suspend/resume and `GUID_SESSION_DISPLAY_STATUS` notifications on its UI-thread message window. Suspend/display-off revokes credentials, worker generations and queued callbacks. Interactive resume/display return rearms a selected tile once; maintenance wake alone and repeated notifications do not reopen the camera. Service power generations and pre-suspend pipe/Job closure prevent earlier verification from releasing credentials after wake. The native desktop cancels operations and clears preview/timer state on power changes.

The SCM service PID authenticates the pipe server; pipe impersonation identifies clients. Only a SYSTEM `System32\LogonUI.exe` caller in an interactive session may request credentials. Account linking validates the password and requires the resulting SID to match the caller. The service accepts no supplied frames or success claims. Prompt acknowledgment comes from LogonUI, and the worker discards pre-prompt samples through the existing native pipeline.

Unlink/relink invalidates older record revisions and pending account-link commits, including an unlink before the first record is saved. Vault mutation and final credential release are serialized. An already released credential is valid once for at most ten seconds; deselection/disconnect/serialization clears it. Pipe closure cancels silent inference, and service shutdown/worker deadlines close the kill-on-close Job Object. Account data goes only to the appropriate Windows serialization path; the Python process never receives passwords.

Machine-scope DPAPI supports pre-login decryption. Administrator/SYSTEM-only file ACLs provide the necessary storage isolation, and the installer verifies ownership, access grants, and reparse points before retaining existing records. Installed code and the private Python runtime live under protected Program Files. Managed password strings are short-lived but cannot be guaranteed zeroed. See [setup and limitations](windows-signin.md) for deployment details and verification status.

### Native motion

One restrained motion language: cubic ease-out, 90–180 ms input feedback, 150 ms measured head tracking, 300 ms captured sectors, 320 ms page entrances, and a 420 ms completion ring. Only active enrollment/scanning attaches the ring's render callback. Disabling animations stops active timelines and resolves ring properties to their target values. Windows `ClientAreaAnimation` and the in-app reduced-motion preference both apply. Motion presents backend state; it never supplies pose, eye, identity, or completion evidence.

The native ring uses eight sectors: first-pass views fill blue and second-pass views turn green. Pen/brush resources are frozen and reused across renders, rebuilding only for a changed drawing size. Visual progress is finite and bounded, and rendered intensity is clamped before palette lookup: identity frame counts may exceed the minimum while waiting for their time gate, without overrunning drawing resources or altering verification state. Preview polling runs only while the camera is active. IPC cancels its unused 30-second timeout timer after every completed reply/model-readiness wait.

## Earlier browser recognition sandbox

```text
React / TypeScript UI
  ├─ Browser webcam capture or user-selected JPEG/PNG
  ├─ Reusable capture canvas; original detail retained up to 960 pixels
  ├─ Independent ~20 Hz video-frame sampling, up to 6 buffered frames
  └─ Same-origin JSON requests
                  │
          127.0.0.1:8765
                  │
Python sandbox service (one serialized inference/state owner)
  ├─ YuNet ONNX: 320-pixel detection, map face/landmarks to original resolution
  ├─ Reject zero/multiple faces and unusable crops
  ├─ SFace ONNX: alignment → 128 floats → L2 normalization
  ├─ Cosine similarity against the centroid and individual enrollment views
  ├─ MediaPipe Face Landmarker: eye blendshapes + eye geometry + head rotation
   ├─ Current server-owned circular enrollment (historical UI assumes five poses)
  ├─ Attempt: identity → blink → reopen → open-eye confirmation → unlocked
  └─ Current-user DPAPI template storage, or memory-only storage
```

OpenCV's CPU DNN backend executes the ONNX models. The native app reuses the tested Python recognition implementation directly through its worker; React is not part of the desktop runtime. The [earlier browser source on `test`](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md) and HTTP tests remain development references, excluded from `main`. The HTTP host serves `experiments/browser/dist/`; the archived guidance has not been ported to current circular enrollment.

The enrollment ring and light sweeps are a React/CSS adaptation of Glance's MIT-licensed onboarding animation. Source revision and attribution are in [third-party notices](../THIRD_PARTY_NOTICES.md).

## Recognition behavior

- Enrollment: neutral plus two eight-direction circuits (17 averaged camera views, at least 51 distinct observations), or 1–5 image samples. Every sample must contain exactly one usable face with both eyes open.
- Every pair of enrollment samples must have cosine similarity of at least 0.50. The profile retains their normalized mean and individual view embeddings. A contiguous float32 matcher is compiled once per profile. Circular profiles reduce repeated views to one maximum score per pose group; the multi-view override requires two distinct groups. Legacy profiles retain their centroid/second-highest-view rule. A single unusually high view score cannot override a failed centroid.
- Default match threshold: 0.55, adjustable between 0.35 and 0.90 in the test bench.
- Camera attempts need 3 open-eye identity matches over at least 150 ms, followed by a fresh blink after the prompt. One sampled bilateral closure suffices, including a brief blink immediately after the prompt. Both eyes must reopen within 0.8 seconds, then remain open for a second confirmation at least 120 ms later.
- Identity is measured on every initial, closed/uncertain-eye, reopening, recovery, and confirmation frame. While waiting with both eyes open, SFace results can be reused for less than 200 ms when the face-box overlap is at least 0.80 IoU with the previous tracked box and at least 0.65 with the last fully matched box. This follows small consecutive movements without moving the identity anchor or extending its deadline. Face detection, quality gates, and eye measurements still run on every sample. The API marks these fast frames with `identity_checked: false`; the UI labels their similarity as a recent match.
- Clear mismatches, unusable faces, missing eye tracking, or gaps over 1 second discard challenge progress. A narrow borderline-score recovery rule is described below. A blink prompt expires after 6 seconds and needs new open-eye identity evidence.
- Attempts expire after 20 seconds. A new attempt cancels the old one. Deleting a profile revokes attempts.
- Image tests expose identity scores but always stay locked; setting a permissive threshold does not bypass the blink challenge.

These thresholds are initial test settings, not a validated authentication operating point. Integration-test portraits demonstrate behavior, not a population-wide false-accept/false-reject rate. A blink challenge rejects an unchanged still photo in functional tests, but does not establish video-replay or generated-video resistance. The sandbox HTTP API accepts client frames; the Windows sign-in worker captures its own camera frames, but does not attest physical-camera hardware or exclude virtual camera drivers.

### Small-motion recovery

A fully measured score up to 0.06 below the selected threshold (and at least 0.35) may **pause** a camera attempt if both eyes are measured open, the face overlaps the last matched box by at least 0.65 IoU, and that match was at most 200 ms ago. The API reports `recovering: true`. Such frames add no identity, calibration, or blink evidence and do not refresh the previous match. Recovery requires a fresh passing match within that same deadline and spatial bound. Sustained weak frames, large jumps, missing faces, and closed/uncertain/unknown eyes on a weak frame reset immediately or when the fixed deadline expires.

A narrow eye-measurement jitter case may also pause initial matching, blink prompting, or final confirmation under the same deadline and face-box bound: identity must fully pass, both EAR values must be at least 0.18, and the largest blink coefficient must be just above 0.30 and no higher than 0.34. This remains an **uncertain** measurement, never open-eye or blink evidence. Weak identity and uncertain eyes cannot be combined for recovery. A low EAR, stronger closure, or unknown tracking does not qualify.

A recovery frame during final confirmation clears the confirmation timer while retaining the already measured blink. A recovered match must begin a new open-eye confirmation interval of at least 120 ms. Closing either eye or losing eye tracking still resets the challenge. The last frame of a batch must pass the full match threshold and open-eye checks; cached or borderline scores cannot authorize an unlock. Image-source tests never use motion recovery.

### Eye state and pose

`attention.py` runs the version-1 float16 MediaPipe Face Landmarker in stateless IMAGE mode, with up to two faces to detect ambiguity. Its landmarks must associate with the same YuNet face. There is no cross-person tracking/smoothing state. The two eye-blink coefficients and eye aspect ratios (EAR) must agree:

- Strict open: both blink coefficients ≤0.30, both corrected EAR ≥0.18, and both screen EAR ≥0.14.
- Closed: both blink coefficients ≥0.60 and both EAR ≤0.21.
- At least three strictly measured open-eye identity frames establish median eye references (at most 12 retained). A brief closure can also count when **both** blink coefficients rise by ≥0.20 to ≥0.35 and **both** corrected EAR values fall to ≤72% of baseline and ≤0.21. Relative closure compares only reference poses within 10° on every axis. Absolute and relative closure evidence must also be within 10° of the last open frame's pose; a large head turn cannot substitute for the blink. Gradual open-eye turns update that pose anchor without training on inferred eye states.
- Chin-up open classification may use at least three strict-open references: pitch must be −35° to −8°, yaw within ±25°, roll within ±20°; references must be within 12° yaw/roll and 22° pitch. Each coefficient must stay ≤min(0.45, reference+0.15), each corrected EAR ≥max(0.18, 90% of reference), and each raw EAR ≥0.14. This bounded path operates in both enrollment and unlocking, including final confirmation. It cannot override a closed/unknown classification. Inferred-open frames never train it, and references never cross sessions or identities.
- Other intermediate/disagreeing measurements, including a wink, remain uncertain. Missing/invalid landmarks and excessive pose are unknown.

Model predictions can be wrong; glasses, occlusion, lighting, and different eyelid geometry require real-camera evaluation. The final open-eye check is mandatory and never inferred from identity similarity.

XYZ eye landmarks use image-width scaling for MediaPipe Z. The validated head rotation transforms camera coordinates into the head-local eye plane. Corrected EAR is the larger of screen and local EAR, capped at 125% of screen EAR; this preserves frontal behavior while bounding depth-model errors. Tiny/offscreen/nonfinite landmarks and invalid rotation matrices are rejected. The pose limits remain ±35° yaw/pitch and ±25° roll. Responses include `left_raw_ear`, `right_raw_ear`, and `eye_method` (`measured`, `pose-calibrated`, or `relative-blink`) and are serialized after the session applies calibration.

Unlock references train only on fully matched strict-open frames in the initial or blink-prompt phases; cached identity frames cannot train them. Lost identity, unknown eyes, expired/stale tracking, or challenge resets discard them. Enrollment checks the earlier captured/held samples and a temporary identity anchor before applying eye calibration, and discards references on missing/changed identity, unknown eyes, gaps over a second, or expiry. No eye reference is persisted in the profile.

### Capture timing

The native capture thread retains up to six immutable raw BGR frames at the driver's negotiated cadence, sampling at up to 40 Hz. Only the desktop preview is encoded: at most 15 Hz, a 720-pixel long edge, JPEG quality 80. Sign-in disables preview encoding entirely. Recognition uses the original frame up to a 960-pixel long edge, and repeated polling of one captured frame cannot advance enrollment. Native timestamps use the same process monotonic clock as the attempt. Stop drops retained images before waiting on the driver; a late read cannot repopulate the stopped queue.

Current source startup tries negotiated DirectShow, default DirectShow and default Media Foundation once each, serially, within one 12-second budget. A nonempty BGR uint8 frame is mandatory; failed handles are released before fallback. Blocked calls retain the one-owner restriction and 3-second stop join; release failures prohibit reuse. Streaming interruption never triggers fallback or resumes old evidence. Numeric indices can differ between backends; physical/multi-camera mapping is unverified. The public v0.8.1 ZIP retains its earlier capture implementation; the authorized `ac7ce8b` source installation includes this change.

`CameraSampler` uses video-frame callbacks and a reused JPEG canvas independently of HTTP requests. Sampling targets 20 Hz, retaining at most six recent frames; camera frames older than 450 ms are discarded before sending. Batches contain images and monotonic millisecond offsets relative to starting the attempt. The server validates finite, strictly increasing offsets, a six-frame limit, and a receipt-time window of -250 to +750 ms to allow initial request transit. Blink durations use capture time rather than the speed at which a buffered batch is processed. Wall-clock expiry remains server-enforced.

The backend stops a batch when it first issues a blink prompt. A challenge counter tells the UI to discard pre-prompt samples, including after challenge retries. Unlock can only occur on the **last** frame of a batch, with both eyes open and a fresh identity measurement; a later closed/uncertain frame cannot be hidden behind earlier open evidence. Abort/stop releases the queue and video callback. These timestamps and frames are sandbox client input, not proof of a physical camera or replay resistance.

### Guided enrollment

The backend calibrates center, then runs left → up-left → up → up-right → right → down-right → down → down-left twice, requiring recentering only between circuits. Positive yaw is the subject's left, positive pitch is chin down; only the preview is mirrored. The neutral hold's median pose establishes a pitch/yaw baseline. Cardinal targets use ±14° yaw or ±10° pitch, diagonals ±10° yaw/±7° pitch. Bounded rectangular windows and separate normalized angular sectors reject neutral/cardinal substitutes for diagonals. Roll remains within ±18°. Three distinct observations spanning at least 240 ms, with pose drift ≤9°, are required per averaged view. Recenter accepts ±9° yaw/pitch, with two observations across 120 ms. Identity consistency is checked against previous views and current-hold frames at ≥0.50 cosine similarity. Eyes must still be open.

The native 80-tick ring shows a median-of-three measured pose relative to neutral and a directional glow, with eight sectors colored from captured server views. Reduced motion keeps static pose/progress/text feedback. Validation uses actual poses, not smoothed display values or animation progress. Wrong poses/faces or closed eyes reset the current hold. A 90-second timeout or cancellation discards unfinished samples. Only the explicit finish endpoint writes a profile once all 17 views are complete. The earlier browser ring remains a historical five-pose UI, not the circular-enrollment frontend.

The SFace model ID and 128-dimensional embedding format are unchanged. Legacy centroid/five-view profiles remain supported; re-enrollment is required for new circular coverage. New guided profiles record `enrollment_version: "circular-v1"`, ordered `template_groups`, per-pose observation counts and total observations. Loading/link validation rejects incomplete/unknown formats. The public profile exposes `matching: "multi-view"` or `"centroid"`, never vectors.

## Local data and transport

The optional HTTP sandbox host binds only to loopback. Host/origin validation, no cross-origin response headers, a per-process mutation token, bounded requests, and a content security policy keep the development API scoped to the local UI. It is not the LocalSystem sign-in service, a privileged authentication API, or a hostile-local-process boundary.

Frames and embeddings are not included in API logs. Loaded browser images remain in page memory until cleared or the page closes. The backend stores profile metadata, the centroid, and up to 17 circular camera-view embeddings (or up to five legacy/image views). All vectors are excluded from public API responses and encrypted together under DPAPI in persistent mode. Session-event export includes timestamps and decision messages, never face vectors or images.

Persistent sandbox templates use `CryptProtectData` with current-user scope. DPAPI protects data at rest; other processes running as that Windows user are not excluded. On non-Windows systems, or with `--ephemeral`, enrollment is memory-only. A corrupted or incompatible profile is retained until explicitly reset.

## Legacy HTTP API surface

This API belongs to the optional browser development host, not the desktop's private command pipe or the privileged sign-in protocol.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Engine state, public profile, storage mode, session token |
| POST | `/api/enroll` | Image-lab enrollment `{name, source: "image", images}` |
| POST | `/api/enrollments` | Start guided camera enrollment `{name}` |
| POST | `/api/enrollments/{id}/frame` | Measure `{image}` and capture only the requested stable pose |
| POST | `/api/enrollments/{id}/finish` | Save a completed two-circle profile |
| DELETE | `/api/enrollments/{id}` | Discard unfinished enrollment |
| DELETE | `/api/profile` | Delete the profile and invalidate attempts |
| POST | `/api/analyze` | Inspect `{image}` without an unlock decision |
| POST | `/api/attempts` | Start `{source, threshold}` |
| POST | `/api/attempts/{id}/frame` | Evaluate `{image}` for that simulated attempt |
| POST | `/api/attempts/{id}/frames` | Evaluate 1–6 `{image, offset_ms}` camera samples in order |
| DELETE | `/api/attempts/{id}` | Cancel an attempt |

Mutating requests require the `X-Viso-Token` from `/api/status`. Image values are JPEG/PNG data URLs. Eye states, pose values, and blink claims supplied by a client are ignored: the backend measures them. Responses expose measurements and simulated state, not an operating-system authentication capability. The UI requires `liveness: "blink-and-open-eyes"` and `camera_pipeline: "buffered-v1"` before enabling tests.

## Remaining Windows milestones

1. **Integrated VM validation:** real local/MSA linking, LogonUI enumeration, session-0 camera access, lock/unlock, cold boot, multi-user behavior, and install/update/removal across supported systems. The development-machine `ac7ce8b` source upgrade passed all 3,219 installed payload hashes, retained links/enrollment, registration checks and automatic LocalSystem startup. Actual current-build authentication, physical sleep and the new 0.8.2 installer lifecycle remain untested. Component tests themselves do not register a provider.
2. **Liveness evaluation:** labeled live/photo/screen/video samples and measured error rates; evaluate stronger presentation-attack detection and randomized challenges.
3. **Distribution hardening:** signed binaries, installer/update lifecycle exercised on supported Windows versions, and driver compatibility results.

Use a rebootable Windows VM with a snapshot and camera passthrough for integrated testing. Windows Sandbox can exercise the desktop UI but is not a substitute for reboot/logon-provider tests. See [validation commands](development.md#validate-changes); automated component results do not establish physical-camera accuracy or end-to-end sign-in latency.
