# Viso

**Look. You're in.** A Windows-first face-unlock project.

## Milestone 1: local test bench

This build runs real face detection and recognition against a **simulated lock screen**. The interface runs in your browser, backed by a local Python/OpenCV process. Windows sign-in integration is a later milestone.

### Included

- Live webcam preview, camera selection, and guided five-angle enrollment (center, left, right, up, down).
- Image lab for repeatable enrollment and matching without a webcam.
- YuNet detection and SFace embeddings using pinned, checksum-verified ONNX models.
- Single-face, minimum-size, brightness, and blur checks.
- MediaPipe eye-state and head-pose measurements, using a pinned Face Landmarker model.
- A simulated unlock after identity matching → prompted blink → both eyes reopened.
- Automatic capture only when the requested enrollment pose is held steady with both eyes open.
- Buffered camera sampling for short blinks, lightweight face detection, and a fast eye-tracking path while waiting for a blink.
- Neutral-calibrated enrollment targets, smaller turns, and averaged samples from each stable hold.
- Multi-angle identity matching and bounded motion recovery to reduce restarts during small head movements.
- Pose-corrected eye geometry and identity-local open-eye references for upward head tilt.
- Glance-style segmented enrollment ring, live head-turn feedback, and soft directional light sweeps.
- Adjustable cosine-similarity threshold and measured inference latency.
- One enrolled identity, encrypted with current-user Windows DPAPI by default.
- Ephemeral mode for a completely memory-only enrollment session.
- Identity management and exportable session events.

**Blink verification is enabled.** Closed, uncertain, or untrackable eyes cannot authorize an unlock. Still images can be compared for identity but cannot unlock the simulator. This is an experimental RGB-camera challenge, not validated protection against replayed/generated video or an injected camera feed. Windows sign-in integration is a later milestone.

## Run on Windows

Requirements: **Python 3.11+**, **Node.js 22.12+**, and an up-to-date Edge or Chrome browser. Development has been verified with Python 3.14 and Node 22 on Windows.

From PowerShell in this folder:

```powershell
# First-time setup: isolated Python environment, models, frontend dependencies, build
.\scripts\setup.ps1

# Recommended for initial testing: enrollment lasts only for this process
.\scripts\start.ps1 -Ephemeral
```

Open **http://127.0.0.1:8765** if the browser does not open automatically. Stop the service with **Ctrl+C** in its terminal.

To keep your enrollment encrypted between runs:

```powershell
.\scripts\start.ps1
```

The model download is about 43 MB. Dependencies/models need the internet during setup; recognition and the UI run locally afterward. No administrator privileges are needed.

### Try it with a webcam

1. Select **Live camera** and click **Enable camera**. Allow the browser's camera request.
2. Enter a profile name and click **Enroll face**. Follow the light: center, your left, your right, chin up, chin down. The segmented ring follows your head, and each captured direction turns green. The preview is mirrored, so the light travels in your direction of movement.
3. Hold each requested angle briefly with both eyes open. Viso averages the stable frames and captures automatically. Return to center between turns when prompted. **Cancel enrollment** or **Escape** discards the unfinished sequence.
4. Click **Test face unlock**. Look at the camera, **blink both eyes when prompted**, then reopen them. The simulator unlocks only after it confirms your eyes are open again.
5. Click **Lock again** to repeat. Every new attempt needs a new blink. **Stop test** or **Escape** cancels a running scan.

Use small head movements, even lighting, and a camera near eye level. Enrollment expires after 90 seconds; unlock attempts expire after 20 seconds. Blink normally after the prompt, then reopen both eyes. A sampled brief closure is sufficient; holding the eyes closed for over 0.8 seconds resets the challenge. Camera frames are sampled independently of network replies to reduce missed blinks.

Small movements can briefly show **Following your movement…** while Viso refreshes a borderline match. That frame cannot unlock; a fresh passing match and open eyes are required. New enrollments retain each angle for multi-view matching. Re-enroll profiles created before v0.4 to enable this; existing profiles still support the improved tracking and recovery.

For the upward angle, lift your chin slightly while keeping your eyes on the camera. Version 0.5 compensates bounded eye foreshortening and learns temporary references from strictly measured open eyes. The readout shows **Tilt adjusted** when those references resolve a chin-up measurement. Begin facing the camera with both eyes open; references are rebuilt for each enrollment or unlock attempt. A large tilt by itself does not count as the prompted blink.

The camera stops when you leave the test-bench page, switch input modes, or hide the browser tab. Restart it with **Enable camera**.

### Try it without a webcam

1. Select **Image lab** and choose a clear reference photo containing one face with both eyes open.
2. Enter a name and click **Enroll face**.
3. Use the **+** button to choose a different photo of the same person.
4. Click **Inspect frame only** to compare similarity. **Test photo rejection** should keep the simulator locked even for a matching photo. Then try a photo of another person.

Choosing images replaces the in-memory input set; it does not replace the enrolled identity. Delete enrollment in **Identity vault** to start over. **Inspect frame only** measures the current input without changing the simulated lock state.

## Development

```powershell
# Terminal 1: local API, memory-only profile
.\.venv\Scripts\python.exe -m backend.viso.server --ephemeral

# Terminal 2: React hot reload
npm run dev
```

Use **http://127.0.0.1:5173** for hot reload. The dev server proxies `/api` to port 8765. For the built UI, `npm run build` updates `dist/`; refresh port 8765 afterward.

```powershell
# Real-model integration tests + backend tests + TypeScript / production build
.\scripts\test.ps1
```

See [test scenarios](docs/testing.md), [architecture and next milestones](docs/architecture.md), and [third-party notices](THIRD_PARTY_NOTICES.md).

## Project layout

```text
src/                       React + TypeScript test bench
backend/viso/              Loopback API, recognition, profile storage, simulation
backend/tests/             Validation, storage, HTTP, and real-model tests
models/manifest.json       Pinned model revisions and SHA-256 hashes
scripts/                   Setup, launch, model download, and test commands
docs/                      Architecture and test-environment notes
.viso/profile.dpapi        Local encrypted enrollment (git-ignored)
```

## Troubleshooting

- **Camera unavailable:** try Edge/Chrome, check site camera permissions, or close another application using the webcam. Image lab works without camera access.
- **Service unavailable:** start the Python service, then use **Engine connected / Service unavailable** to reconnect. If the process restarted during an operation, refresh the page.
- **Port in use:** stop the previous Viso process or use `start.ps1 -Port 8766`. The Vite dev proxy specifically uses port 8765.
- **Models unavailable/corrupt:** rerun `setup.ps1`; model checksums are verified before loading.
- **Upgrading:** restart the service and refresh the browser to load the matching camera pipeline. Persistent SFace profiles remain compatible; re-enroll to collect the improved guided samples. Ephemeral profiles last only for their original process. The new UI checks backend camera-pipeline compatibility.
- **Eyes not confirmed open:** improve lighting, reduce glare on glasses, move closer, and face the camera more directly. The eye thresholds are experimental and may need tuning after real-camera testing.
- **Profile cannot be opened:** DPAPI storage belongs to the Windows user/machine that created it. Use **Reset profile** to remove an unreadable sandbox profile, then enroll again.
