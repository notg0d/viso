# Troubleshooting

[← Documentation](README.md) · [Getting started](getting-started.md) · [Windows sign-in](windows-signin.md)

## Desktop and camera

| Problem | What to try |
| :--- | :--- |
| **Camera unavailable or busy** | Allow Windows desktop-app camera access, close other camera apps, then choose/refresh the device in Settings. Use Image lab to test the engine without a webcam. |
| **Models or engine unavailable** | ZIP: close Viso, verify the download, and extract the entire archive again without mixing runtime/model versions. Source: run `.\scripts\setup.ps1` from the root, then reopen. Model checksums are checked before use. Errors appear in the native window. |
| **ZIP executable won't start / runtime missing** | Extract all files; do not run inside the ZIP or copy only `Viso.exe`. Check Windows x64 and .NET Framework 4.8. The unsigned executable may trigger SmartScreen; [verify the download](releases.md#verify-the-download). |
| **Python package install fails** | Check that the selected Python is 64-bit and has wheels for the pinned packages. Python 3.14 is the verified development version; see [requirements](getting-started.md#requirements). Do not install multiple OpenCV wheels into the same environment. |
| **Cannot replace `Viso.exe` during build** | Close the running app before `.\scripts\build-native.ps1`. Do not delete your enrollment to fix an executable lock. |
| **Camera stops after changing pages, minimizing, locking, or sleep** | This is deliberate cancellation. Restart the camera/test; old frames and challenge evidence must not resume. |
| **Camera driver did not stop/release** | Close Viso before retrying. Startup fallback never opens a second handle while a blocked driver owns the first. Reconnect the camera or restart Windows if other apps cannot use it. |
| **Source build uses a different camera after fallback** | DirectShow and Media Foundation may order devices differently. Check the preview/backend/index; disconnect unneeded cameras while diagnosing. Physical multi-camera mapping is not verified. |
| **Enrollment does not capture a direction** | Follow the actual indicated direction with both eyes open, pause briefly, and keep movement small. A cardinal turn cannot fill a diagonal view. Recenter between circles only. |
| **Eyes not confirmed open / blink missed** | Improve lighting, reduce glasses glare, move closer, and face the camera more directly. Blink both eyes normally after the prompt, then reopen; do not substitute a head turn or wink. Physical-camera behavior remains experimental. |
| **Recognition fails in a dim room** | Use soft front-facing light, raise screen brightness if it illuminates your face, and avoid a bright window behind you. Do not lower identity/blink thresholds to compensate. Software brightening cannot recover missing eye detail; use password/PIN when lighting is insufficient. |
| **Profile cannot be opened** | Current-user DPAPI belongs to the Windows user/machine that created it. The unreadable profile is preserved until explicit reset. Resetting removes it; if sign-in is linked, read the [unlink/delete rules](windows-signin.md#update-disable-remove) first. |
| **Enrollment missing after closing** | `-Ephemeral` is memory-only. Launch without it and enroll again; closing does not save or convert the prior session. |

### Unlock-test crash in desktop 0.8.0

Desktop **0.8.1** fixes an `IndexOutOfRangeException` in `EnrollmentRing.OnRender` when valid identity frames exceed the minimum before the time gate completes. Close the app and rebuild:

```powershell
.\scripts\build-native.ps1
.\scripts\start.ps1
```

The fix bounds visual progress, not authentication evidence. It needs no re-enrollment, account-link change, or sign-in reinstall.

## Windows sign-in

> [!WARNING]
> If Viso fails at the Windows sign-in screen, choose your ordinary password/PIN option. Keep that fallback available; do not make Viso the only route into a test machine.

| Problem | What to check |
| :--- | :--- |
| **No Viso Face option** | The desktop build does not install the provider. Follow the separate [build/install guide](windows-signin.md#build-and-install) from 64-bit administrator PowerShell and confirm the account is linked. |
| **Link rejected** | Use a persistent, completed camera profile and link from the Windows account being unlocked. Enter the account password, not a Hello PIN. Photo, ephemeral, blank-password, and passwordless-only linking are unsupported. |
| **Microsoft-account password rejected** | Sign into Windows once with the current account password to refresh its cached credentials. Password sign-in must be available; work/school and domain accounts are outside this prototype. |
| **Enrollment, password, or camera changes not reflected** | The installed service retains a snapshot. Choose **Link / update account** again; desktop changes do not silently replace it. |
| **Updated desktop but old sign-in behavior** | `%ProgramFiles%\Viso` contains a separate provider/service/private runtime. Follow the [retained-link upgrade procedure](windows-signin.md#update-disable-remove). The desktop 0.8.1 rendering fix alone does not require it. |
| **“Starting Viso” pauses before the camera starts** | This covers pipe connection and Python/model initialization, not just Windows service startup. The unreleased [model-readiness update](windows-signin.md#model-readiness-unreleased) retains preloaded models while Windows needs sign-in, without a timed expiry. It also initializes native inference in advance and reports cold loading immediately. Deploy the separate sign-in service to use it. Cold initialization, camera drivers and optional exposure calibration still take time; zero delay is not guaranteed. |
| **Scan does not start behind lock-screen wallpaper** | Scanning begins when Windows selects the credential tile on the sign-in screen. Windows chooses providers according to its remembered preference and policy. |
| **A failed scan does not retry** | By design: use the arrow or reselect the tile. Viso avoids an automatic camera/retry loop. |
| **Wake behavior inconsistent** | The selected-tile wake path has synthetic regression coverage; long sleep, hibernate, and Modern Standby need physical validation. Sign in normally and record the scenario. |
| **Uninstaller cannot remove an open DLL** | Restart Windows, then rerun the uninstaller. Use `-KeepAccountLinks` only for an intended retained-link upgrade; ordinary removal deletes service account records. |

For provider lifecycle tracing, use the opt-in [diagnostics setting](windows-signin.md#provider-diagnostics), then disable it after diagnosis. Do not include passwords, encrypted account records, images, or face embeddings in a bug report.

## Report a useful reproduction

In the unreleased source build, **Activity → Export JSON** includes allowlisted runtime/camera diagnostics: versions, model readiness, storage mode, backend/index, startup outcomes/time, source dimensions and sampled cadence. No camera is opened and nothing is uploaded. The published v0.8.1 ZIP does not yet include this diagnostic update. Metadata excludes credentials, identifiers, images/vectors and raw driver exceptions, but existing event messages can contain a chosen profile name or an error path; review/redact before sharing. The snapshot describes the desktop worker, not the separately installed sign-in runtime.

Include Windows/Python versions, desktop and installed sign-in versions separately, camera model, action sequence, storage mode, and the visible error. For crashes, the Windows Application log may contain `.NET Runtime` / `Application Error` entries for `Viso.exe`. Redact personal/account information before sharing. See [Contributing](../CONTRIBUTING.md#reporting-a-problem).
