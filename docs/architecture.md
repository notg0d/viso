# Architecture

## Current: recognition sandbox

```text
React / TypeScript UI
  ├─ Browser webcam capture or user-selected JPEG/PNG
  ├─ Resize to at most 960 pixels on the longest side
  └─ Same-origin JSON requests
                  │
          127.0.0.1:8765
                  │
Python sandbox service (one serialized inference/state owner)
  ├─ YuNet ONNX: face box + five landmarks
  ├─ Reject zero/multiple faces and unusable crops
  ├─ SFace ONNX: alignment → 128 floats → L2 normalization
  ├─ Cosine similarity against the enrolled centroid
  ├─ MediaPipe Face Landmarker: eye blendshapes + eye geometry + head rotation
  ├─ Server-owned five-pose enrollment, stable hold before capture
  ├─ Attempt: identity → blink → reopen → open-eye confirmation → unlocked
  └─ Current-user DPAPI template storage, or memory-only storage
```

OpenCV's CPU DNN backend executes the ONNX models. Python provides a quick, inspectable test harness on the available Windows toolchain; the model files and recognition math are portable to a later native implementation. The React UI is suitable for a future desktop shell.

This is a fresh Viso implementation inspired by Glance's experience. Glance's Swift source and model weights are not bundled.

## Recognition behavior

- Enrollment: 5 guided camera poses or 1–5 image samples. Every sample must contain exactly one usable face with both eyes open.
- Every pair of enrollment samples must have cosine similarity of at least 0.50. The final template is their normalized mean.
- Default match threshold: 0.55, adjustable between 0.35 and 0.90 in the test bench.
- Camera attempts need 3 open-eye identity matches over at least 150 ms, followed by a fresh blink after the prompt. Closure must be detected at least 150 ms after the prompt; both eyes must reopen within 1.5 seconds, then remain open for a second confirmation at least 120 ms later.
- Every frame in the challenge must match the enrolled identity. Wrong/unusable faces, missing eye tracking, or gaps over 1 second discard challenge progress. A blink prompt expires after 6 seconds and needs new open-eye identity evidence.
- Attempts expire after 20 seconds. A new attempt cancels the old one. Deleting a profile revokes attempts.
- Image tests expose identity scores but always stay locked; setting a permissive threshold does not bypass the blink challenge.

These thresholds are initial test settings, not a validated authentication operating point. Integration-test portraits demonstrate behavior, not a population-wide false-accept/false-reject rate. A blink challenge rejects an unchanged still photo in functional tests, but does not establish video-replay or generated-video resistance. Camera frames arrive through the sandbox HTTP API, which cannot attest a physical camera.

### Eye state and pose

`attention.py` runs the version-1 float16 MediaPipe Face Landmarker in stateless IMAGE mode, with up to two faces to detect ambiguity. Its landmarks must associate with the same YuNet face. There is no cross-person tracking/smoothing state. The two eye-blink coefficients and eye aspect ratios (EAR) must agree:

- Open: both blink coefficients ≤0.30 and both EAR ≥0.18.
- Closed: both blink coefficients ≥0.60 and both EAR ≤0.21.
- Intermediate/disagreeing measurements, including a wink, are uncertain and cannot count as both open or both closed. Missing/invalid landmarks and excessive pose are unknown.

Model predictions can be wrong; glasses, occlusion, lighting, and different eyelid geometry require real-camera evaluation. The final open-eye check is mandatory and never inferred from identity similarity.

### Guided enrollment

The backend chooses the sequence: center → subject's left → subject's right → up → down. Positive yaw is the subject's left, positive pitch is chin down; the browser mirrors only the preview. The first neutral sample establishes a pitch/yaw baseline. Turns target 12–28° yaw; up/down target 10–23° pitch relative to neutral, with limits on other axes. Three observations spanning at least 450 ms, with pose drift ≤4°, are required for a capture. Every sample must match every earlier sample at ≥0.50 cosine similarity. Wrong poses/faces or closed eyes reset the current hold. A 90-second timeout or cancellation discards unfinished samples. Only the explicit finish endpoint writes the profile once all five poses are complete.

The SFace model ID and embedding format are unchanged, so old persistent profiles can still be matched. New guided profiles record pose labels/angles in encrypted metadata.

## Local data and transport

The service binds only to loopback. Host/origin validation, no cross-origin response headers, a per-process mutation token, bounded requests, and a content security policy keep the development API scoped to the local UI. It is not a privileged authentication API or a hostile-local-process boundary.

Frames and embeddings are not included in API logs. Loaded browser images remain in page memory until cleared or the page closes. The service stores only profile metadata and the centroid. Session-event export includes timestamps and decision messages, never face vectors or images.

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
| DELETE | `/api/attempts/{id}` | Cancel an attempt |

Mutating requests require the `X-Viso-Token` from `/api/status`. Image values are JPEG/PNG data URLs. Eye states, pose values, and blink claims supplied by a client are ignored: the backend measures them. Responses expose measurements and simulated state, not an operating-system authentication capability. The UI requires the `blink-and-open-eyes` capability before enabling tests.

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
