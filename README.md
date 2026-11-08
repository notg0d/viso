# Viso

**Look. You're in.** A Windows-first face-unlock project.

## Native Windows app

Viso is a **native C#/WPF desktop application** for face enrollment, unlock testing, image inspection, profile management, and settings. Its Glance-inspired dark interface uses a segmented enrollment ring, directional light, and eased native animations. The Python/OpenCV recognition worker starts with the app and communicates over private process pipes. No browser, web server, Electron, or WebView is needed.

**Unlock test** is a simulator. An optional native **Windows sign-in prototype** now supports local accounts and personal Microsoft accounts through a Credential Provider and LocalSystem service. See [Windows sign-in setup](docs/windows-signin.md). Actual lock-screen/reboot authentication and service camera access still need VM validation.

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
- Glance-style segmented enrollment ring, live head-turn feedback, and soft directional light cues.
- Native window controls, camera selection, file dialogs, and keyboard navigation.
- 90–320 ms eased UI transitions, measured-pose tracking, and a 420 ms completion ring.
- Windows animation preferences and an in-app reduced-motion setting.
- Adjustable cosine-similarity threshold and measured inference latency.
- One enrolled identity, encrypted with current-user Windows DPAPI by default.
- Ephemeral mode for a completely memory-only enrollment session.
- Identity management and exportable session events.
- Account linking, password updates, and disable controls for local/Microsoft-account Windows sign-in.
- x64 Credential Provider, protected per-account service storage, and a privately packaged recognition runtime.

**Blink verification is enabled.** Closed, uncertain, or untrackable eyes cannot authorize an unlock. Still images can be compared for identity but cannot unlock. This is an experimental RGB-camera challenge, not validated protection against replayed/generated video or an injected camera feed.

## Run on Windows

Requirements: **64-bit Windows 10/11**, **.NET Framework 4.8**, and **Python 3.11+**. Development has been verified with Python 3.14. The build uses Windows' installed C# compiler; Node.js and a .NET SDK are not required.

From PowerShell in this folder:

```powershell
# First-time setup: isolated Python environment, recognition models, native build
.\scripts\setup.ps1

# Recommended for initial testing: enrollment lasts only for this process
.\scripts\start.ps1 -Ephemeral
```

This opens **`desktop\bin\Viso.exe`**. After the first build, you can launch that executable directly. Keep it inside the project folder so it can locate the Python environment and models. Closing the window releases the camera and shuts down its recognition worker.

To keep your enrollment encrypted between runs:

```powershell
.\scripts\start.ps1
```

The model download is about 43 MB. Dependencies/models need the internet during setup; recognition and the UI run locally afterward. No administrator privileges are needed. Persistent profiles use the existing `.viso/profile.dpapi` file; desktop preferences are stored in `.viso/desktop.json`.

### Optional Windows sign-in

The sign-in components additionally require **x64 Windows**, **Visual Studio C++ Build Tools**, and the **Windows 10/11 SDK** to build. Installation requires administrator privileges. Build and validate first:

```powershell
.\scripts\build-signin.ps1 -Test
.\scripts\test-signin-runtime.ps1
```

In an administrator PowerShell on the test Windows machine:

```powershell
.\scripts\install-signin.ps1
```

Run Viso normally, save a five-angle camera enrollment, then use **Settings → Windows face sign-in → Link / update account**. Select **Local account** and your Windows username, or **Microsoft account** and your account email. Enter the **account password**, not a Windows Hello PIN. Passwordless-only accounts need a usable password for this implementation. Lock Windows and choose **Sign-in options → Viso Face**, then scan and blink when prompted.

[Full setup, password updates, removal, and validation status](docs/windows-signin.md).

### Try it with a webcam

1. In **Your face**, enter a profile name. **Start camera** previews your camera; **Begin enrollment** also starts it automatically.
2. Follow the five prompts: center, your left, your right, chin up, chin down. The preview is mirrored, and the ring tracks your measured head direction.
3. Hold each requested angle briefly with both eyes open. Viso averages the stable frames and captures automatically. Return to center when prompted. **Cancel** or **Escape** discards the unfinished sequence.
4. Open **Unlock test**, then **Test face unlock**. Look at the camera, **blink both eyes when prompted**, then reopen them. The simulator unlocks only after it confirms your eyes are open again.
5. Start another test to repeat. Every attempt needs a new blink. The camera stops after completion, when changing pages, when minimizing, on Windows session lock, and when closing Viso.

Use **Settings** to choose a camera, adjust the similarity threshold, reduce motion, or delete/reset an enrollment. **Ctrl+Tab** moves between pages. **Activity** contains the last 100 events and a native **Export JSON** dialog.

Use small head movements, even lighting, and a camera near eye level. Enrollment expires after 90 seconds; unlock attempts expire after 20 seconds. Blink normally after the prompt, then reopen both eyes. A sampled brief closure is sufficient; holding the eyes closed for over 0.8 seconds resets the challenge. Camera frames are sampled independently of network replies to reduce missed blinks.

Small movements can briefly show **Following your movement…** while Viso refreshes a borderline match. That frame cannot unlock; a fresh passing match and open eyes are required. New enrollments retain each angle for multi-view matching. Re-enroll profiles created before v0.4 to enable this; existing profiles still support the improved tracking and recovery.

For the upward angle, lift your chin slightly while keeping your eyes on the camera. Version 0.5 compensates bounded eye foreshortening and learns temporary references from strictly measured open eyes. The readout shows **Tilt adjusted** when those references resolve a chin-up measurement. Begin facing the camera with both eyes open; references are rebuilt for each enrollment or unlock attempt. A large tilt by itself does not count as the prompted blink.

Camera access uses Windows desktop-app permissions: **Settings → Privacy & security → Camera → Let desktop apps access your camera**.

### Try it without a webcam

1. Open **Image lab → Choose photos** and select up to five clear JPEG/PNG reference photos of one person with both eyes open.
2. Enter a name and click **Enroll photos**.
3. Choose a different photo of the same person. The dropdown selects a photo from the loaded set.
4. Click **Inspect** to compare similarity. **Test photo rejection** keeps the simulator locked even for a matching photo. Then try a photo of another person.

Choosing photos replaces the in-memory input set. Delete enrollment in **Settings** to start over. **Inspect** measures the selected input without changing the simulated lock state.

## Development

```powershell
# Compile the native executable
.\scripts\build-native.ps1

# Run native visual/IPC smoke checks with temporary, memory-only enrollment
.\scripts\build-native.ps1 -SmokeTest
```

Native UI source lives in `desktop/Viso/`. XAML is embedded into the executable. The smoke check loads the real models, renders native screenshots into `test-results/native/`, verifies control gating and reduced motion, and checks inference, Unicode IPC, photo rejection, and deletion when test portraits are available.

```powershell
# Real-model integration tests + backend tests + native build and smoke check
.\scripts\test.ps1
```

See [test scenarios](docs/testing.md), [architecture](docs/architecture.md), and [third-party notices](THIRD_PARTY_NOTICES.md).

## Project layout

```text
desktop/Viso/              Native C#/WPF UI, motion, camera catalog, process client
desktop/bin/               Built Viso.exe (git-ignored)
backend/viso/native.py     Private desktop worker and DirectShow camera capture
backend/viso/signin.py     Service-owned one-shot profile/camera worker
backend/viso/              Recognition, profile storage, simulation, legacy API
backend/tests/             Validation, storage, HTTP, and real-model tests
models/manifest.json       Pinned model revisions and SHA-256 hashes
scripts/                   Setup, launch, model download, and test commands
signin/Provider/           x64 C++ V2 Credential Provider
signin/Service/            C# LocalSystem sign-in service and account vault
signin/Shared/             Named-pipe protocol and Windows account validation
signin/Tests/              Credential formats, service, and IPC checks
docs/                      Architecture and test-environment notes
.viso/profile.dpapi        Local encrypted enrollment (git-ignored)
.viso/desktop.json         Desktop preferences (git-ignored)
src/                       Earlier browser test bench (not used by native app)
```

## Troubleshooting

- **Camera unavailable:** check Windows desktop-camera permissions, close other camera apps, and choose/refresh the device under Settings. Image lab works without a camera.
- **Engine unavailable:** close Viso, run `setup.ps1` if dependencies are missing, then reopen the app. Engine errors appear inside the native window.
- **Build cannot replace Viso.exe:** close the running app before rebuilding.
- **Models unavailable/corrupt:** rerun `setup.ps1`; model checksums are verified before loading.
- **Upgrading:** close Viso and run `start.ps1` to rebuild. Existing DPAPI face profiles remain compatible. Ephemeral profiles last only for their original process.
- **Eyes not confirmed open:** improve lighting, reduce glare on glasses, move closer, and face the camera more directly. The eye thresholds are experimental and may need tuning after real-camera testing.
- **Profile cannot be opened:** DPAPI storage belongs to the Windows user/machine that created it. Use **Reset profile** to remove an unreadable sandbox profile, then enroll again.
