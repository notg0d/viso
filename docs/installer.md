# Complete Windows installer

[← Documentation](README.md) · [Release ZIP](releases.md) · [Windows sign-in](windows-signin.md) · [Security](security.md)

The **0.8.2 source build** adds `Viso-0.8.2-Setup-x64.exe`, an all-in-one, administrator installer. It is separate from the already published **v0.8.1 desktop-only ZIP**, which remains unchanged. Building the installer does not publish it or update an installed machine.

## What is included

- Native desktop app, Start-menu shortcut, optional desktop shortcut, and Windows Installed apps uninstall entry. Viso's face-scan logo is embedded in the desktop and Setup executable, with 16-256px Windows icon sizes and a matching high-DPI window/header icon.
- Private x64 Python interpreter, pinned dependency closure, recognition models, and upstream notices/licenses. Users need no Python, Visual Studio, Inno Setup, .NET SDK, or first-run model download.
- x64 Credential Provider and automatic LocalSystem `VisoSignIn` service, using the same protected runtime.
- Documentation, build provenance and a pinned SHA-256 payload manifest; a separate checksum accompanies the Setup executable. Included guide links work locally; references to unshipped development sources point to the build's pinned GitHub commit (publish that source commit before distributing those references).

Requires **Windows 10/11 x64 and .NET Framework 4.8**. Windows on ARM is unsupported. These experimental builds are unsigned and may trigger SmartScreen. Verify the download before running. The repository does not currently declare a project-wide Viso license; retain all upstream notices when distributing. Inno Setup is a build-only tool; its own license/commercial-use terms apply to the builder.

## Install and use

1. Close an existing installed Viso in every Windows session.
2. Run Setup normally and approve the administrator prompt. Read and explicitly accept the experimental sign-in warning; keep working ordinary Windows password/PIN access.
3. Setup verifies a fresh protected staging tree and actual model initialization before stopping an old service, replacing files, starting the new service and registering **only Viso's** tile. If old files are open, it restores the previous service state and asks you to restart manually and retry; it does not kill LogonUI or queue an upgrade over a loaded DLL.
4. Open **Viso** from the Start menu as the ordinary Windows user who will sign in. Enroll a face, then use **Settings → Windows face sign-in → Link / update account** with that account's password, not its Hello PIN. Setup never asks for credentials, imports an enrollment, links another account or opens the camera.
5. Use the [Windows sign-in guide](windows-signin.md#link-and-use). Recognition/blink checks are experimental, not Windows Hello certified or proven resistant to replay/generated video.

If Setup was launched from an already elevated shell or with **Run as administrator**, open Viso separately from the ordinary Start menu rather than relying on the optional finish-page launch. Standard double-click/UAC installation can launch as the original user.

**Superseded 0.8.2 installers:** an earlier Inno Setup 7 build incorrectly launched 32-bit PowerShell, even after administrator approval, and displayed “Use 64-bit administrator PowerShell.” Cancel that failed Setup and use the rebuilt installer/checksum; additional elevation does not fix that executable. The corrected shared launcher explicitly starts native x64 PowerShell for installation and removal, without relaxing the architecture or administrator checks. The helper uses only Windows PowerShell's built-in modules, avoiding incompatible PowerShell 7 or user-writable module paths inherited from a launching shell.

## Storage, upgrades and removal

- Program files are fixed at `%ProgramFiles%\Viso`, protected against ordinary-user writes. Destination overrides, untrusted existing ACLs/owners, reparse points and conflicting service/COM registrations are rejected.
- Installed desktop enrollment and preferences live at **`%LOCALAPPDATA%\Viso`**, independently for each Windows user. The Python worker and account-link import use that same directory. Portable/source copies keep their existing `.viso/` folder.
- Service account records remain at `%ProgramData%\Viso\Accounts`, administrator/SYSTEM-only. Upgrades freeze and verify their aggregate hashes/count between old service stop and new service startup; later authenticated relinks remain valid. No credentials or identifiers are written into the transaction journal.
- Source/portable enrollment is not moved automatically. To migrate on the same Windows installation, close both copies and, as the enrolled Windows user, copy only your own `profile.dpapi` and `desktop.json` from `.viso/` into `%LOCALAPPDATA%\Viso`. Do not overwrite an existing enrollment. Retained service links already have their own snapshot; do not relink unless intentionally changing it.
- Updates stage and validate all bundled files before changing the old installation. The old payload stays in a protected transaction backup until Setup finishes; ordinary failures/cancellation restore the previous payload/service state. A crash or power loss can require the recovery procedure below.
- Uninstall through **Windows Settings → Installed apps → Viso**. It unregisters only Viso, stops/deletes its service, and asks whether to retain encrypted account links for reinstall. The default removes the stored account-password snapshots. Desktop enrollment/preferences are always retained; deleting `%LOCALAPPDATA%\Viso` is a separate user action.
- Locked files during uninstall are scheduled individually for removal at restart. Setup refuses reinstall while Viso-specific file deletion/replacement is pending, preventing a subsequent reboot from deleting new binaries. Restart manually before reinstalling. Uninstall cancellation before confirmation does not stop the service or alter registration.

## Recovery

Use ordinary password/PIN access first. Do not delete protected account records or broad Program Files paths as troubleshooting.

An interrupted installer can leave an administrator/SYSTEM-only `%ProgramFiles%\Viso.setup-*` directory containing `transaction.json`, a staged payload and/or `previous` backup. In **64-bit administrator PowerShell**, use a verified copy of the deployment helper and common helper from the matching installer payload:

```powershell
# Substitute the exact protected transaction directory; never use a wildcard.
& .\installer\deploy.ps1 -Action Rollback -Transaction 'C:\Program Files\Viso.setup-EXACT-NAME'
```

Rollback restores the old payload and prior service startup/running state without overwriting retained account links. Hashes are checked while linking remains quiesced; after new service startup, authenticated relinks are preserved. Damaged journals or a missing required old-payload backup are rejected before touching the current installation. If the new installation has successfully completed and only backup cleanup failed, `-Action Commit` removes a **verified** transaction backup instead. Read the Setup log and journal before choosing; never discard an unverified backup. After a power loss, verify x64 provider registration and the service before treating recovery as complete.

## Build and validate

From a prepared Windows checkout with dependencies/models, x64 C++ Build Tools/SDK and **Inno Setup 6.7+ or 7**:

```powershell
.\scripts\build-installer.ps1 -Compiler 'C:\path\to\ISCC.exe'
```

Alternatively set `INNOSETUP_COMPILER` or put `ISCC.exe` on PATH. The script does not install/download tools. Publishable builds require committed clean sources; `-AllowDirty` is for local drafts only. Existing artifacts are never overwritten; use a fresh `-OutputDirectory` when needed.

Output under `desktop/releases/`:

- `Viso-0.8.2-Setup-x64.exe` — everything in one download.
- `Viso-0.8.2-Setup-x64.exe.sha256` — installer checksum.
- `Viso-0.8.2-Setup-x64.exe.json` — provenance/checksums, no private user data.
- `Viso-0.8.2-installer-payload/` — build/validation staging, not an additional user dependency.

On `test`, run `scripts/test-installer.ps1 -Payload PATH` and the x64 `scripts/test-installer-desktop.ps1 -Bundle PATH`, plus existing Python, native, provider/service and deployment suites. The installer regression runner uses synthetic folders, a private temporary HKCU sandbox and mocked service/runtime operations for lifecycle tests; it **does not install or modify the real Windows sign-in provider/service**. Full bundled service-to-Python checks and desktop model readiness use the actual payload without the camera. The desktop check also saves/deletes a synthetic public-portrait DPAPI enrollment in an explicit temporary user-state directory, never in Program Files or a real user's enrollment folder.

`scripts/test-installer-launch.ps1 -Compiler PATH` compiles and runs a non-elevating, non-installing Inno probe with the **production shared launcher** and real integrity-only helper. It checks native x64 execution from the actual Setup process, spaces/Unicode paths, ignored untrusted inherited modules, wrong-bitness rejection and preserved administrator requirements. With Inno 7 it exercises both 32-bit and 64-bit Setup engines and reproduces the original redirected `Exec` failure. No service/provider, account or camera operation is performed.

Automated staging/compilation checks are not a clean-machine installation, reboot, real uninstall or authentication guarantee. Run fresh-install, retained-link upgrade, rollback, locked-DLL, reboot/removal, non-admin desktop and physical enrollment/unlock tests in a recoverable Windows VM/machine before broad distribution.

Setup also supports `/VERIFYONLY=1 /VERIFYRESULTFILE="C:\path\receipt.ini"`: it extracts and checks the **embedded** payload against the compiled manifest/helper hashes **and requires native x64 helper execution**, writes an optional receipt, then intentionally cancels (exit code 1). This may still request administrator approval because it is the same administrator Setup executable, but performs no installation, service/registration changes, account access or camera capture. A receipt with `Success=1` and `Native64=1` distinguishes successful integrity-only verification from an error; it is not installation certification.

For intentional silent deployment, use `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ACCEPTSIGNINRISK=1`; risk consent cannot be omitted. Silent uninstall removes account records by default; `/KEEPACCOUNTLINKS=1` explicitly retains them. Do not put account passwords in installer parameters.
