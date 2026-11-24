# Windows sign-in: local and Microsoft accounts

[← Documentation](README.md) · [Security & privacy](security.md) · [Troubleshooting](troubleshooting.md#windows-sign-in)

> [!WARNING]
> This prototype changes Windows sign-in and stores a protected account-password snapshot. Use a recoverable test environment, keep ordinary password/PIN access available, and read the update/removal instructions before installation. Automated checks are not authentication certification.

Viso includes an x64 V2 Credential Provider and a `VisoSignIn` Windows service. The provider submits a Windows credential after the service matches a face, prompts for a fresh blink, and confirms both eyes reopened. Windows performs the account authentication.

The [0.8.5 complete installer](installer.md) includes the separate service, provider and private runtime. Updating the desktop alone does not update Windows sign-in. Physical sleep, hibernate, reboot, varied cameras, Microsoft-account and multi-user scenarios require separate validation.

## Account support

| Windows account | Link using | Credential path |
|---|---|---|
| Local account | Username, `.\username`, or `PCNAME\username`, plus its password | Protected `KERB_INTERACTIVE_UNLOCK_LOGON` |
| Personal Microsoft account | Email or `MicrosoftAccount\email`, plus its password | Protected identity-provider buffer via `CredPackAuthenticationBufferW` |

Link from the Windows account you intend to unlock. The service validates the password with `LogonUser` and requires the returned SID to match the named-pipe caller. Another account's correct password cannot link that account from your session. Each Windows user has a separate service record.

Windows Hello PINs are device-specific credentials and cannot replace the account password here. Blank-password and passwordless-only accounts are unsupported. If Microsoft-account validation fails, first sign into Windows once with the current account password so its cached Windows credentials are current. If Windows is configured to allow only Hello sign-in for Microsoft accounts, password sign-in must be available for this prototype. Work/school, Entra ID, domain, RDP/CredUI, and password-change scenarios are outside this implementation.

## Build and install

The [**v0.8.5 experimental release**](https://github.com/notg0d/viso/releases/tag/v0.8.5) provides a [complete Windows Setup.exe](installer.md) containing the desktop, private Python/models and these sign-in components. End users need no source checkout, Python or C++ build tools. First-time users must still explicitly enroll/link their own account after installation. The **source-based workflow below** remains supported and has additional build prerequisites.

Requirements: x64 Windows 10/11, .NET Framework 4.8, the Python dependencies/models installed by `setup.ps1`, Visual Studio x64 C++ Build Tools, and a Windows SDK with Credential Provider headers. Windows on ARM is not supported by this DLL build.

```powershell
.\scripts\setup.ps1
.\scripts\build-signin.ps1
```

Automated build/runtime checks and fixtures are maintained on `test`; see [validation commands](development.md#validate-changes).

Then, from **64-bit administrator PowerShell** in this project:

```powershell
.\scripts\install-signin.ps1
```

The installer copies the provider, service, backend, models, Python interpreter/standard library and installed dependencies into `%ProgramFiles%\Viso`. It checks the packaged recognition runtime before starting the service and registering the tile. The service starts automatically as LocalSystem. The desktop app continues to launch from the project folder via `start.ps1`.

The installer creates protected directories atomically. Retained `%ProgramData%\Viso` data must already be owned by Administrators/SYSTEM, have no other access grants, and contain no reparse points. Untrusted existing files are rejected rather than adopted. Installation errors roll back Viso's registration/service/payload; existing account links are retained.

## Link and use

1. Open installed Viso from the Start menu, or launch `scripts/start.ps1` without `-Ephemeral` for a source build, and save a two-circle **camera** enrollment. Photo-lab and memory-only enrollment cannot enable Windows sign-in. Existing complete five-view profiles still work; re-enroll/relink only when intentionally changing the saved snapshot for new direction coverage.
2. In **Settings**, select the desired camera. Under **Windows face sign-in**, choose the account type, enter its username/email and password, and click **Link / update account**.
3. Use **Refresh status** to confirm the account is linked. Password fields clear after a link attempt, when leaving Settings, on minimize/session lock, and on close.
4. Lock Windows. Choose **Sign-in options → Viso Face**. Selection starts the scan automatically. Look ahead with eyes open, blink after the displayed prompt, and reopen both eyes. After a failure, select the arrow to retry or switch sign-in options.

Only one scan can hold the camera at a time. The desktop stops its camera on session lock and power changes. The sign-in match threshold is fixed at **0.55**; the desktop threshold slider affects simulator tests only. Recognition attempts expire after 20 seconds. An outer 45-second worker deadline covers initialization and IPC. The provider accepts a released credential once, for at most 10 seconds.

### Model readiness (0.8.4)

The service keeps one unused model-only worker between sign-ins, including while Windows is unlocked. Lock notifications alone arrive too late to hide cold imports. Model retention never permits authentication. One measured standby used approximately 508 MiB of private memory; memory use varies by system.

The standby worker receives no profile and opens no camera. It reads each model once, verifies those bytes, and initializes native inference with blank inputs before reporting readiness. Initialization has a 30-second deadline. No background model load starts while another worker is active.

A selected scan consumes the worker once and destroys it after success, error, cancellation or timeout. Profiles, eye calibration and camera frames never carry into a replacement worker. The service prepares a replacement when no worker is active, even after sign-in with Viso, PIN or password. Unlock, logon, logoff and disconnect revoke that session's active verification and result pipe.

Suspend preserves only an unused standby that has successfully initialized. It destroys active or loading workers and closes existing pipes. Automatic maintenance wake does not start a replacement. Interactive resume can prepare a replacement; service shutdown destroys every worker. Physical sleep and hibernate behavior still need validation.

New source builds precompile `runtime/Lib` with the packaged interpreter. These caches use checked source hashes and relative filenames. Workers retain `-I -B`: isolated imports can read packaged caches, but do not write new caches. Payload manifests cover the caches. Validation rejects caches outside the runtime, wrong interpreter tags, unchecked hashes and caches without source.

If models are not ready, a selected scan prepares its camera while model preparation continues. The tile reports both stages immediately. Idle standby still opens no camera. Recognition starts only after both stages finish; it discards startup frames before the fresh identity and blink challenge.

Cold initialization, camera-driver startup and optional exposure calibration still take time. These stages can overlap, but zero-delay startup is not guaranteed. Physical reboot, sleep, hibernate and current-build sign-in latency still need validation. Building the desktop alone does not deploy this separate sign-in update.

For model-only startup measurements, run this command from a prepared `test`-branch checkout:

```powershell
.\.venv\Scripts\python.exe -I -B .\scripts\benchmark_startup.py --root 'C:\Program Files\Viso' --runs 5
```

The benchmark never opens a camera or reads account records. It measures a fresh worker and a synthetic validation request. It does not measure physical sign-in, cold boot or LocalSystem performance.

### Lighting feedback and optional exposure assistance (0.8.3)

The selected sign-in tile includes measured lighting guidance alongside the real face/blink instruction. A scene estimate is used before a usable face is detected; an aligned-face measurement is preferred afterward. “Usable” lighting is not proof of identity or adequate eye detail.

In desktop **Settings**, refresh sign-in status, choose the camera, set **Exposure assistance for Windows sign-in**, then click **Save sign-in camera settings**. This explicitly updates only the current linked account’s camera options, without requesting a password or replacing its face profile. It also invalidates verification using the previous settings. Desktop capture has a separate checkbox. Old records/preferences keep assistance off by default.

Assistance reads supported DirectShow controls and calibrates before capture is made available (normally about 0.8–1.5 additional seconds). It raises exposure by at most two log2 steps and never above **15.6 ms**; measured capture must remain at least **24 Hz**. Controls are read back. Slow or overly bright capture rolls back; an active blink challenge is revoked and requires a fresh scan. Unsupported/limited drivers keep ordinary capture usable. Media Foundation fallback does not receive speculative control writes. No exposure increases occur during the blink challenge.

Original exposure/auto settings are restored on normal camera shutdown, including before a successful worker result is released. Restoration is best effort when a driver hangs or a process is forcibly killed; restart the camera or use its own settings if needed. No screen fill light or software brightening is used. Identity thresholds, fresh-frame checks and blink/open-eye requirements are unchanged. Real low-light hardware testing is still required; add a light in front of you if the image remains inadequate.

### Default selection and automatic scanning

Viso supplies a default tile for a linked account. Windows gives preference to the last successfully used provider, subject to device policy and its own selection rules. Choose Viso and complete one sign-in; subsequent locks can select that tile automatically. Viso does not force a machine-wide provider policy. Automatic scanning begins when the credential tile is selected on the sign-in screen, not behind the wallpaper-only lock screen.

Selection launches background verification; a message-only window delivers status/prompt callbacks on LogonUI's UI thread. Only a fresh accepted result asks Windows to serialize automatically. Failed scans wait for a manual retry rather than repeatedly reopening the camera. Deselection, unadvising, and disconnect cancel pending work. Windows may still impose its own sign-in confirmation in some scenarios.

The same window registers suspend/resume and session-display notifications. Suspend/display-off clears pending scans and accepted credentials. Interactive resume or display return rearms a still-selected tile **once**, even if Windows never calls `SetSelected` again. Automatic maintenance wake alone does not open the camera; repeated wake/display notifications do not loop retries. The service closes pre-suspend pipes and active workers, retaining only the unused initialized standby. It rejects results from older power generations. This is covered by synthetic notification tests, not yet a physical long-sleep guarantee.

If recognition, the camera, the service, or a saved password fails, select your ordinary Windows password/PIN option. A failed stored password must be updated in Viso after signing in normally.

## Update, disable, remove

- **Password or enrollment changed:** use **Link / update account** again. The service keeps a snapshot; desktop changes do not silently replace it. Relink after renaming the Windows account/computer or changing the Microsoft-account sign-in identity. In 0.8.3, camera/exposure-only changes use **Save sign-in camera settings** instead.
- **Disable one account:** click **Disable face sign-in**. The encrypted service record is deleted; desktop enrollment remains.
- **Delete desktop enrollment:** persistent-mode deletion first unlinks the current service account. If the installed service is stopped, start it before deleting so an enabled service copy is not left behind. Ephemeral sessions do not alter the persistent link.
- **Concurrent changes:** unlink/relink invalidates pending link commits and verification against an older record. A credential already released to LogonUI is one-use and expires after 10 seconds; unlink cannot retract a serialization Windows has already received.

For complete-installer upgrades, close Viso and run the verified replacement Setup. It retains account links and desktop enrollment. Uninstalling first is not required; see [installer upgrade and recovery rules](installer.md#storage-upgrades-and-removal).

To remove the Windows components in administrator PowerShell:

```powershell
.\scripts\uninstall-signin.ps1
```

This removes Viso's registrations, stops/deletes its service, and deletes its account records and installed payload. Desktop files/enrollment stay in the project. If LogonUI still holds the DLL open, restart Windows and run the uninstaller again to finish file removal.

For an upgrade that retains account links:

```powershell
# Close the desktop app, then build the updated components.
.\scripts\build-native.ps1
.\scripts\build-signin.ps1
# Administrator PowerShell:
.\scripts\uninstall-signin.ps1 -KeepAccountLinks
# If files or the deleted service remain open, restart Windows and rerun
# uninstall with -KeepAccountLinks. Otherwise continue in this session.
.\scripts\install-signin.ps1
```

Retained records work only on the same Windows installation. A changed profile format/model may require relinking.

Launching or rebuilding the desktop app alone does not update `%ProgramFiles%\Viso`. The lock screen runs the separately installed service, provider DLL, and private backend. Apply the sign-in update as well to receive the 0.8 wake and resource fixes. After circular re-enrollment, **Link / update account** again: retained links keep their old profile snapshot until explicitly replaced. Building/tests do not install anything.

### Provider diagnostics

For callback/automatic-submit troubleshooting, administrator PowerShell can set DWORD `HKLM:\SOFTWARE\Viso\SignInDiagnostics` to `1`. The next LogonUI instance records provider lifecycle stages, result codes, and state flags in the Application event log under source `VisoSignIn`, event ID `100`. It records no account names, passwords, face images, or embeddings. Set the value back to `0` after diagnosing the issue. The setting is read once per provider process.

## Stored data and trust boundary

- `%ProgramData%\Viso\Accounts\<SID>.dpapi` contains the account kind/name, password, imported face profile, camera index, optional exposure-assistance flag, and a revision ID, encrypted with machine-scope DPAPI. The directory's administrator/SYSTEM-only ACL is essential: machine-scope DPAPI alone is not per-user isolation.
- Clients verify that `Viso.SignIn.v1` belongs to the running SCM service PID. The service identifies clients by pipe impersonation and restricts credential requests to LocalSystem `System32\LogonUI.exe` in an interactive session. The pipe denies network callers.
- The bounded UTF-8 pipe protocol accepts no client image frames or claimed biometric success. The private worker receives profile/camera data, never the account password. Python runs with `-I -B` and a restricted executable search path; a kill-on-close Job Object contains it.
- Passwords are not logged or exported. Byte buffers and native password strings are cleared after use; .NET's immutable strings mean guaranteed immediate erasure of every managed-memory copy is not claimed.

This remains an experimental RGB-camera implementation. Blink checks have functional coverage but do not establish replay/generated-video resistance or Windows Hello certification. Physical authentication, reboot, long sleep and multi-user validation are still required.
