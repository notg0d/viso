# Architecture

## Current: recognition sandbox

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
  ├─ Server-owned five-pose enrollment, stable hold before capture
  ├─ Attempt: identity → blink → reopen → open-eye confirmation → unlocked
  └─ Current-user DPAPI template storage, or memory-only storage
```

OpenCV's CPU DNN backend executes the ONNX models. Python provides a quick, inspectable test harness on the available Windows toolchain; the model files and recognition math are portable to a later native implementation. The React UI is suitable for a future desktop shell.

The enrollment ring and light sweeps are a React/CSS adaptation of Glance's MIT-licensed onboarding animation. Source revision and attribution are in `THIRD_PARTY_NOTICES.md`.

## Recognition behavior

- Enrollment: 5 guided camera poses or 1–5 image samples. Every sample must contain exactly one usable face with both eyes open.
- Every pair of enrollment samples must have cosine similarity of at least 0.50. The profile retains their normalized mean and up to five individual view embeddings. Matching uses the greater of centroid similarity and the second-highest view similarity: the multi-view path requires two enrolled views to independently pass the selected threshold. A single unusually high view score cannot override a failed centroid.
- Default match threshold: 0.55, adjustable between 0.35 and 0.90 in the test bench.
- Camera attempts need 3 open-eye identity matches over at least 150 ms, followed by a fresh blink after the prompt. One sampled bilateral closure suffices, including a brief blink immediately after the prompt. Both eyes must reopen within 0.8 seconds, then remain open for a second confirmation at least 120 ms later.
- Identity is measured on every initial, closed/uncertain-eye, reopening, recovery, and confirmation frame. While waiting with both eyes open, SFace results can be reused for less than 200 ms when the face-box overlap is at least 0.80 IoU with the previous tracked box and at least 0.65 with the last fully matched box. This follows small consecutive movements without moving the identity anchor or extending its deadline. Face detection, quality gates, and eye measurements still run on every sample. The API marks these fast frames with `identity_checked: false`; the UI labels their similarity as a recent match.
- Clear mismatches, unusable faces, missing eye tracking, or gaps over 1 second discard challenge progress. A narrow borderline-score recovery rule is described below. A blink prompt expires after 6 seconds and needs new open-eye identity evidence.
- Attempts expire after 20 seconds. A new attempt cancels the old one. Deleting a profile revokes attempts.
- Image tests expose identity scores but always stay locked; setting a permissive threshold does not bypass the blink challenge.

These thresholds are initial test settings, not a validated authentication operating point. Integration-test portraits demonstrate behavior, not a population-wide false-accept/false-reject rate. A blink challenge rejects an unchanged still photo in functional tests, but does not establish video-replay or generated-video resistance. Camera frames arrive through the sandbox HTTP API, which cannot attest a physical camera.

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

`CameraSampler` uses video-frame callbacks and a reused JPEG canvas independently of HTTP requests. Sampling targets 20 Hz, retaining at most six recent frames; camera frames older than 450 ms are discarded before sending. Batches contain images and monotonic millisecond offsets relative to starting the attempt. The server validates finite, strictly increasing offsets, a six-frame limit, and a receipt-time window of -250 to +750 ms to allow initial request transit. Blink durations use capture time rather than the speed at which a buffered batch is processed. Wall-clock expiry remains server-enforced.

The backend stops a batch when it first issues a blink prompt. A challenge counter tells the UI to discard pre-prompt samples, including after challenge retries. Unlock can only occur on the **last** frame of a batch, with both eyes open and a fresh identity measurement; a later closed/uncertain frame cannot be hidden behind earlier open evidence. Abort/stop releases the queue and video callback. These timestamps and frames are sandbox client input, not proof of a physical camera or replay resistance.

### Guided enrollment

The backend chooses center → subject's left → subject's right → up → down, requiring a brief return to neutral between directional captures. Positive yaw is the subject's left, positive pitch is chin down; the browser mirrors only the preview. The neutral hold's median pose establishes a pitch/yaw baseline. Turns target 16° ±6° yaw; up/down target 12° ±5° pitch relative to neutral, with limits on other axes. Three observations spanning at least 350 ms, with pose drift ≤5°, are required for a capture. Each pose stores the normalized average embedding of its stable hold instead of only the last frame. Identity consistency is checked against both previous poses and frames in the current hold at ≥0.50 cosine similarity.

The 80-tick ring shows a median-of-three measured pose relative to neutral with a six-tick-wide live turn band. Four directional sectors light only after the server captures the matching angle; center pulses the whole ring. Layered, pointer-transparent light ribbons travel toward the requested direction after a 360 ms delay. A pose change, recenter, cancellation, or completion removes the previous sweep. Ticks merge into a solid ring on completion, shown for 1.1 seconds after saving. Reduced-motion settings keep static guidance and disable animation. Validation uses actual individual poses, not smoothed display values or animation progress. Feedback distinguishes chin movement, left/right correction, recentering, and unwanted sideways tilt. Wrong poses/faces or closed eyes reset the current hold. A 90-second timeout or cancellation discards unfinished samples. Only the explicit finish endpoint writes the profile once all five poses are complete.

The SFace model ID and 128-dimensional embedding format are unchanged, so old persistent profiles still use their original centroid score. Re-enrollment is required to retain individual views, which previous versions discarded. New guided profiles also record pose labels/angles in encrypted metadata. The public profile exposes `matching: "multi-view"` or `"centroid"`.

## Local data and transport

The service binds only to loopback. Host/origin validation, no cross-origin response headers, a per-process mutation token, bounded requests, and a content security policy keep the development API scoped to the local UI. It is not a privileged authentication API or a hostile-local-process boundary.

Frames and embeddings are not included in API logs. Loaded browser images remain in page memory until cleared or the page closes. The service stores profile metadata, the centroid, and up to five enrollment-view embeddings. All vectors are excluded from public API responses and encrypted together under DPAPI in persistent mode. Session-event export includes timestamps and decision messages, never face vectors or images.

Persistent sandbox templates use `CryptProtectData` with current-user scope. DPAPI protects data at rest; other processes running as that Windows user are not excluded. On non-Windows systems, or with `--ephemeral`, enrollment is memory-only. A corrupted or incompatible profile is retained until explicitly reset.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Engine state, public profile, storage mode, session token |
| POST | `/api/enroll` | Image-lab enrollment `{name, source: "image", images}` |
| POST | `/api/enrollments` | Start guided camera enrollment `{name}` |
| POST | `/api/enrollments/{id}/frame` | Measure `{image}` and capture only the requested stable pose |
| POST | `/api/enrollments/{id}/finish` | Save a completed five-angle profile |
| DELETE | `/api/enrollments/{id}` | Discard unfinished enrollment |
| DELETE | `/api/profile` | Delete the profile and invalidate attempts |
| POST | `/api/analyze` | Inspect `{image}` without an unlock decision |
| POST | `/api/attempts` | Start `{source, threshold}` |
| POST | `/api/attempts/{id}/frame` | Evaluate `{image}` for that simulated attempt |
| POST | `/api/attempts/{id}/frames` | Evaluate 1–6 `{image, offset_ms}` camera samples in order |
| DELETE | `/api/attempts/{id}` | Cancel an attempt |

Mutating requests require the `X-Viso-Token` from `/api/status`. Image values are JPEG/PNG data URLs. Eye states, pose values, and blink claims supplied by a client are ignored: the backend measures them. Responses expose measurements and simulated state, not an operating-system authentication capability. The UI requires `liveness: "blink-and-open-eyes"` and `camera_pipeline: "buffered-v1"` before enabling tests.

## Windows milestones

1. **Recognition sandbox (current):** real enrollment/matching, explicit simulated unlock, repeatable image tests, Windows data-at-rest storage.
2. **Liveness evaluation:** labeled live/photo/screen/video samples; evaluate an anti-spoofing model and randomized motion challenges against measured error rates.
3. **Native recognition host:** C++ service using the same ONNX models and a camera source independent of a logged-in browser. Retain preprocessing/score parity tests.
4. **Credential Provider prototype in a Windows VM:** add a custom sign-in tile for a dedicated local test account. The provider submits a valid Windows credential after the native service's decision. This still requires credential storage/release design.
5. **Desktop packaging:** enrollment UI shell, installer/service lifecycle, recovery and update handling, then additional account types.

The sandbox HTTP API and current-user DPAPI store are not the pre-login service interface. Pre-login key availability, service identity, authenticated IPC, per-attempt freshness, cancellation, multi-user isolation, and camera ownership must be designed for the native service.

### Native sign-in test environment

Use a disposable Windows 11 VM with a dedicated local account and a snapshot before Credential Provider installation. First test provider enumeration and ordinary password submission, then connect recognition. Camera passthrough depends on the hypervisor; deterministic image fixtures can test the recognition host before passthrough is configured. Windows Sandbox is suitable for disposable UI trials but a rebootable VM is the better fit for logon-provider work.

No Credential Provider, Windows service, registry registration, or VM has been installed by milestone 1.
