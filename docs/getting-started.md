# Getting started

[← Documentation](README.md) · [Troubleshooting](troubleshooting.md) · [Optional Windows sign-in](windows-signin.md)

## Requirements

| Component | Requirement |
| :--- | :--- |
| Windows | 64-bit Windows 10 or 11. |
| Desktop runtime | .NET Framework 4.8; the build uses Windows' installed C# compiler. |
| Recognition runtime | 64-bit Python 3.11+ with wheels available for [the pinned dependencies](../requirements.txt). Development is verified with Python 3.14. |
| Camera | A Windows-accessible webcam for live enrollment; not required for the photo lab. |
| First setup | Internet access for Python packages and approximately 43 MB of model weights. |

The desktop does not require Node.js, Electron, WebView, a .NET SDK, or administrator privileges. Visual Studio C++ tools and administrator installation are needed only for the [optional sign-in components](windows-signin.md).

## 1. Build and launch

Open PowerShell in the repository root:

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1 -Ephemeral
```

Setup creates `.venv/`, installs the pinned Python packages, downloads and verifies the model checksums, and builds `desktop\bin\Viso.exe`. The app starts its recognition worker over private process pipes; it opens no HTTP server. After setup, UI and recognition run locally.

Keep the executable within the project directory so it can locate `.venv/`, `backend/`, and `models/`. You can launch it directly after the first build, or use `start.ps1` to rebuild when native source changes.

### Choose your storage mode

| Launch | Enrollment |
| :--- | :--- |
| `.\scripts\start.ps1 -Ephemeral` | Memory-only for this worker process; lost when the app closes. Cannot enable Windows sign-in. |
| `.\scripts\start.ps1` | One encrypted profile in `.viso/profile.dpapi`, restored by the same Windows user/machine. |

An ephemeral profile is not converted into a persistent one. Close the app, launch normally, and enroll again if you want to save it. Desktop preferences are separate in `.viso/desktop.json`. Closing Viso releases the camera and shuts down its worker.

## 2. Enroll with a webcam

Allow **Settings → Privacy & security → Camera → Let desktop apps access your camera**. On Windows 10, find the corresponding desktop-app camera toggle under **Privacy → Camera**.

1. In **Your face**, enter a profile name. **Start camera** previews the device; **Begin enrollment** also starts it automatically.
2. Face the camera with both eyes open for neutral calibration.
3. Follow a small circle: **left → up-left → up → up-right → right → down-right → down → down-left**. Pause briefly in each indicated direction.
4. Return briefly to center, then make the same circle again. The first pass fills blue; the second turns sectors green. You do not need to recenter between every direction.
5. Wait for completion. Viso saves **17 averaged views from at least 51 distinct open-eye observations** only after the full sequence finishes.

The preview is mirrored. Keep movements small, use even light, and place the camera near eye level. Wrong directions, a different face, or closed/uncertain eyes reset the current hold. **Cancel** or **Escape** discards unfinished enrollment. Enrollment expires after **90 seconds**.

For chin-up prompts, lift your chin slightly while looking toward the camera. The **Tilt adjusted** readout indicates bounded, session-local eye calibration—not permission to use closed eyes. Head movement alone never counts as a blink.

## 3. Try the unlock simulator

> [!NOTE]
> The **Unlock test** screen changes only simulated state. It does not unlock Windows or install a Credential Provider.

1. Open **Unlock test → Test face unlock**.
2. Look at the camera with both eyes open until identity is confirmed.
3. **Blink both eyes after the prompt**, then reopen them. Viso needs stable open-eye confirmation before the simulator unlocks.
4. Start another test to repeat; every attempt needs a new blink.

Attempts expire after **20 seconds**. Blink naturally: a sampled brief closure is sufficient; holding the eyes closed for more than **0.8 seconds** resets the challenge. Winks, uncertain/untrackable eyes, and unchanged photos cannot authorize an unlock.

**Following your movement…** means a narrowly bounded pause while a fresh match is measured. The paused frame cannot unlock. If tracking is lost or another face appears, challenge evidence is discarded.

The camera stops on completion, page change, minimizing, Windows session lock/power changes, and app close. Restart the camera/test explicitly in the desktop after an interruption.

## Try it without a webcam

1. Open **Image lab → Choose photos**. Select up to five clear JPEG/PNG reference photos of one person with both eyes open.
2. Enter a name and choose **Enroll photos**. This creates the desktop test profile; it is not a sign-in enrollment. If a profile already exists, remove it explicitly in Settings first.
3. Load or select a different photo of that person and choose **Inspect** to compare identity, eye measurements, quality, and inference timing.
4. Choose **Test photo rejection**. Even a matching photo must leave the simulator locked. Compare another person's photo as well.

Choosing photos replaces the in-memory input set. Inspection does not change simulated lock state. Delete/reset the test enrollment in **Settings** to start over; [read the persistent-profile/account-link behavior first](windows-signin.md#update-disable-remove) if Windows sign-in is enabled.

## Controls and preferences

| Control | Behavior |
| :--- | :--- |
| **Ctrl+Tab** | Move between pages. |
| **Escape / Cancel** | Cancel the active enrollment or test. |
| **Settings → Camera** | Choose or refresh a camera. |
| **Settings → Similarity threshold** | Change simulator matching only; sign-in remains fixed at **0.55**. |
| **Settings → Reduced motion** | Keep static ring, progress, and text guidance; Windows animation preferences also apply. |
| **Activity → Export JSON** | Export the last 100 session events, without frames or face vectors. |

## Next steps

- [Troubleshooting](troubleshooting.md) for camera, model, profile, and blink problems.
- [Security & privacy](security.md) to understand experimental RGB recognition and data storage.
- [Windows sign-in](windows-signin.md) for the separate installation and explicit account-link workflow. Existing five-view profiles are compatible; re-enroll and **Link / update account** for circular coverage.
