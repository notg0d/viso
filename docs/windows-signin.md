# Windows sign-in: local and Microsoft accounts

Viso includes an x64 V2 Credential Provider and a `VisoSignIn` Windows service. The provider submits a Windows credential after the service matches a face, prompts for a fresh blink, and confirms both eyes reopened. Windows performs the account authentication.

**Status:** the existing installed account-linking/sign-in flow has been reported working on a local Windows installation. The 0.7 automatic-selection and prewarming changes pass component checks; the new build still needs interactive LogonUI, reboot, and multi-user validation on the target machine.

## Account support

| Windows account | Link using | Credential path |
|---|---|---|
| Local account | Username, `.\username`, or `PCNAME\username`, plus its password | Protected `KERB_INTERACTIVE_UNLOCK_LOGON` |
| Personal Microsoft account | Email or `MicrosoftAccount\email`, plus its password | Protected identity-provider buffer via `CredPackAuthenticationBufferW` |

Link from the Windows account you intend to unlock. The service validates the password with `LogonUser` and requires the returned SID to match the named-pipe caller. Another account's correct password cannot link that account from your session. Each Windows user has a separate service record.

Windows Hello PINs are device-specific credentials and cannot replace the account password here. Blank-password and passwordless-only accounts are unsupported. If Microsoft-account validation fails, first sign into Windows once with the current account password so its cached Windows credentials are current. If Windows is configured to allow only Hello sign-in for Microsoft accounts, password sign-in must be available for this prototype. Work/school, Entra ID, domain, RDP/CredUI, and password-change scenarios are outside this implementation.

## Build and install

Requirements: x64 Windows 10/11, .NET Framework 4.8, the Python dependencies/models installed by `setup.ps1`, Visual Studio x64 C++ Build Tools, and a Windows SDK with Credential Provider headers. Windows on ARM is not supported by this DLL build.

```powershell
.\scripts\setup.ps1
.\scripts\build-signin.ps1
```

Automated build/runtime checks and fixtures are maintained on the [test branch](https://github.com/notg0d/viso/tree/test).

Then, from **64-bit administrator PowerShell** in this project:

```powershell
.\scripts\install-signin.ps1
```

The installer copies the provider, service, backend, models, Python interpreter/standard library and installed dependencies into `%ProgramFiles%\Viso`. It checks the packaged recognition runtime before starting the service and registering the tile. The service starts automatically as LocalSystem. The desktop app continues to launch from the project folder via `start.ps1`.

The installer creates protected directories atomically. Retained `%ProgramData%\Viso` data must already be owned by Administrators/SYSTEM, have no other access grants, and contain no reparse points. Untrusted existing files are rejected rather than adopted. Installation errors roll back Viso's registration/service/payload; existing account links are retained.

## Link and use

1. Launch `scripts/start.ps1` without `-Ephemeral` and save a five-angle **camera** enrollment. Photo-lab and memory-only enrollment cannot enable Windows sign-in.
2. In **Settings**, select the desired camera. Under **Windows face sign-in**, choose the account type, enter its username/email and password, and click **Link / update account**.
3. Use **Refresh status** to confirm the account is linked. Password fields clear after a link attempt, when leaving Settings, on minimize/session lock, and on close.
4. Lock Windows. Choose **Sign-in options → Viso Face**. Selection starts the scan automatically. Look ahead with eyes open, blink after the displayed prompt, and reopen both eyes. After a failure, select the arrow to retry or switch sign-in options.

The service preloads models in one unused, Job-contained Python worker at startup and after each scan. This standby worker receives no profile and opens no camera. A scan consumes it once and destroys it on success, error, cancellation, or timeout; no profile, eye calibration, or camera frame carries into the next worker. Only one scan can hold the camera at a time. The desktop stops its camera on session lock. The sign-in match threshold is fixed at **0.55**; the desktop threshold slider affects simulator tests only. Recognition attempts expire after 20 seconds, with an outer 45-second worker deadline covering initialization and IPC. The provider accepts a released credential once, for at most 10 seconds.

### Default selection and automatic scanning

Viso supplies a default tile for a linked account. Windows gives preference to the last successfully used provider, subject to device policy and its own selection rules. Choose Viso and complete one sign-in; subsequent locks can select that tile automatically. Viso does not force a machine-wide provider policy. Automatic scanning begins when the credential tile is selected on the sign-in screen, not behind the wallpaper-only lock screen.

Selection launches background verification; a message-only window delivers status/prompt callbacks on LogonUI's UI thread. Only a fresh accepted result asks Windows to serialize automatically. Failed scans wait for a manual retry rather than repeatedly reopening the camera. Deselection, unadvising, and disconnect cancel pending work. Windows may still impose its own sign-in confirmation in some scenarios.

If recognition, the camera, the service, or a saved password fails, select your ordinary Windows password/PIN option. A failed stored password must be updated in Viso after signing in normally.

## Update, disable, remove

- **Password, enrollment, or camera changed:** use **Link / update account** again. The service keeps a snapshot; desktop changes do not silently replace it. Relink after renaming the Windows account/computer or changing the Microsoft-account sign-in identity.
- **Disable one account:** click **Disable face sign-in**. The encrypted service record is deleted; desktop enrollment remains.
- **Delete desktop enrollment:** persistent-mode deletion first unlinks the current service account. If the installed service is stopped, start it before deleting so an enabled service copy is not left behind. Ephemeral sessions do not alter the persistent link.
- **Concurrent changes:** unlink/relink invalidates pending link commits and verification against an older record. A credential already released to LogonUI is one-use and expires after 10 seconds; unlink cannot retract a serialization Windows has already received.

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

Launching or rebuilding the desktop app alone does not update `%ProgramFiles%\Viso`. The lock screen runs the separately installed service, provider DLL, and private backend. Apply the sign-in update as well to receive automatic scanning, model prewarming, and the 0.7.1 camera-start fix.

### Provider diagnostics

For callback/automatic-submit troubleshooting, administrator PowerShell can set DWORD `HKLM:\SOFTWARE\Viso\SignInDiagnostics` to `1`. The next LogonUI instance records provider lifecycle stages, result codes, and state flags in the Application event log under source `VisoSignIn`, event ID `100`. It records no account names, passwords, face images, or embeddings. Set the value back to `0` after diagnosing the issue. The setting is read once per provider process.

## Stored data and trust boundary

- `%ProgramData%\Viso\Accounts\<SID>.dpapi` contains the account kind/name, password, imported face profile, camera index, and a revision ID, encrypted with machine-scope DPAPI. The directory's administrator/SYSTEM-only ACL is essential: machine-scope DPAPI alone is not per-user isolation.
- Clients verify that `Viso.SignIn.v1` belongs to the running SCM service PID. The service identifies clients by pipe impersonation and restricts credential requests to LocalSystem `System32\LogonUI.exe` in an interactive session. The pipe denies network callers.
- The bounded UTF-8 pipe protocol accepts no client image frames or claimed biometric success. The private worker receives profile/camera data, never the account password. Python runs with `-I -B` and a restricted executable search path; a kill-on-close Job Object contains it.
- Passwords are not logged or exported. Byte buffers and native password strings are cleared after use; .NET's immutable strings mean guaranteed immediate erasure of every managed-memory copy is not claimed.

This remains an experimental RGB-camera implementation. Blink checks have functional coverage but do not establish replay/generated-video resistance or Windows Hello certification. See [the remaining integrated tests](https://github.com/notg0d/viso/blob/test/docs/testing.md#windows-sign-in-validation).
