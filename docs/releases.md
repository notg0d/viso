# Windows releases

[← Documentation](README.md) · [Getting started](getting-started.md) · [Security](security.md)

## Download and run

**0.8.3 release candidate:** the updated source adds lighting feedback, opt-in exposure assistance and startup reliability fixes. A locally built `Viso-0.8.3-Setup-x64.exe` is not automatically published or installed. Its adjacent `.sha256`, `.exe.json` and `.exe.validation.json` identify that exact build and its unverified gates. The public downloads below remain unchanged until an explicit release is published.

Choose the distribution deliberately. Both are unsigned **experimental pre-releases**, require **Windows 10/11 x64 and .NET Framework 4.8**, and include the private Python runtime, dependencies, recognition models and upstream notices. Windows on ARM is unsupported.

| Download | Installation and scope |
| :--- | :--- |
| [**v0.8.2 complete installer**](https://github.com/notg0d/viso/releases/tag/v0.8.2) | Desktop plus experimental Windows sign-in provider/service. Administrator approval and explicit risk consent required. Per-user desktop state in `%LOCALAPPDATA%\Viso`. |
| [**v0.8.1 portable desktop ZIP**](https://github.com/notg0d/viso/releases/tag/v0.8.1) | Unchanged desktop-only bundle, no sign-in installation or administrator approval. State in `.viso/` beside the extracted app. |

### Complete installer (0.8.2)

Download these four release assets as needed; only the executable is needed to install, but verify it against the checksum first:

- **`Viso-0.8.2-Setup-x64.exe`** — all-in-one installer (**130,520,374 bytes**).
- **`Viso-0.8.2-Setup-x64.exe.sha256`** — executable checksum.
- **`Viso-0.8.2-Setup-x64.exe.json`** — clean-source provenance, versions and checksums.
- **`Viso-0.8.2-Setup-x64.exe.validation.json`** — exact-build pre-publication evidence and unverified gates; historical flags reflect validation time.

After verification, close Viso in every Windows session, run Setup and accept its administrator/sign-in-risk prompts. Open Viso from the Start menu as your ordinary Windows user. First-time users enroll a face and explicitly link their account in Settings using the account password, not a Hello PIN. Setup never enrolls, collects credentials, links accounts or opens the camera.

The tag is pinned to production build commit `3f35b09`; only the latest logo-equipped, native-PowerShell-corrected build is published. Do not use superseded local installers. Final elevated embedded-payload verification, clean-machine installation/lifecycle/reboot and current-build physical authentication remain open validation gates. Read the [installer storage, upgrades/removal and recovery guide](installer.md), and keep normal Windows password/PIN access available.

### Portable desktop only (0.8.1)

Get the **ZIP**, not GitHub's automatically generated source-code archives, from the [0.8.1 experimental release](https://github.com/notg0d/viso/releases/tag/v0.8.1):

- **`Viso-0.8.1-windows-x64.zip`** — native desktop plus private Python runtime, pinned dependencies, verified models, and notices.
- **`Viso-0.8.1-windows-x64.zip.sha256`** — archive checksum.

Extract the **entire ZIP** to a folder owned by your Windows user, then open **`Viso.exe`**. Keep the companion folders and `Viso.exe.config` beside it. Do not run it inside the ZIP or copy only the executable. No administrator installation, Python setup, or first-run model download is required.

Both distributions need a webcam for live enrollment; Image lab works without opening a camera. Windows SmartScreen may warn about the unsigned executables. This is experimental software, not a certified security product.

The ZIP is a directly runnable folder bundle, **not a single-file executable or installer**. Recognition runs locally over private process pipes; it opens no HTTP server. The worker uses Python isolated mode (`-I`) and disables bytecode caches (`-B`), selecting the bundled runtime before a source checkout's `.venv`.

## Verify the download

In PowerShell, in the folder containing the download and its `.sha256`:

```powershell
$file = 'Viso-0.8.2-Setup-x64.exe'
# For the portable desktop instead: $file = 'Viso-0.8.1-windows-x64.zip'
$expected = (Get-Content ($file + '.sha256') -Raw).Split(' ')[0]
$actual = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Checksum mismatch. Do not run this download.' }
```

The **v0.8.2 installer SHA-256** is `d18c27c57ae32775a9bfc2d03ea77270fb28eb2501b6effef0f07f1652b4e68f`. Its adjacent `.exe.json` records clean production source/build metadata and payload checksums. The unchanged **v0.8.1 ZIP SHA-256** is `8108b88d1d2b2c213827609f6ef6c7a8bdae63f9b91742d0a60df30d3cc0352e`.

For the portable ZIP, `SHA256SUMS.txt` inside the extracted folder records all payload files except itself. `RELEASE.json` records the production source commit, build date, desktop/Python versions, and exact dependency inventory. Checksums detect corruption; they are not a digital signature or independent proof of publisher identity.

## Enrollment and Windows sign-in

Normal **installed** desktop launch stores `profile.dpapi` and `desktop.json` in `%LOCALAPPDATA%\Viso`, separately for each Windows user. Normal **portable ZIP** launch stores `.viso/profile.dpapi` and `.viso/desktop.json` beside the app. Enrollment is encrypted for the current Windows user/machine. Neither distribution ships user enrollment, credentials, account links, fixtures, tests, browser assets or development caches. Source/portable profiles are not migrated automatically by Setup.

For memory-only enrollment, open PowerShell in the extracted folder:

```powershell
.\Viso.exe --ephemeral
```

Launching the desktop app does **not** install Windows sign-in; the **Unlock test** is a simulator. The **complete installer does install** Viso's provider/service after administrator approval and risk consent, while the **ZIP contains no provider, service binary or privileged installer**. The [source-based administrator workflow](windows-signin.md#build-and-install) also remains supported. Settings can explicitly link to an installed Viso service; use **Link / update account** only if you intend to change its saved snapshot.

RGB face/blink checks are not Windows Hello certified and have no measured replay-resistance guarantee. Keep your Windows password/PIN available. [Privacy and limitations](security.md).

## Update or remove

For the **complete installer**, close Viso and use the verified replacement Setup. Installed per-user desktop state is retained; encrypted service links have protected upgrade safeguards. Uninstall through Windows Installed apps with an explicit account-link retention choice; desktop state is retained. Follow the [installer recovery/removal guidance](installer.md#storage-upgrades-and-removal), including restart-before-reinstall when files are locked. Publication does not apply an update to your machine.

For the **portable desktop ZIP**:

1. Close Viso before updating; its Python child should exit with it.
2. Extract the new ZIP to a **new** folder. Do not mix versions of runtime files or models.
3. To retain desktop enrollment/preferences on this PC, copy only your own `.viso/` folder into the new extracted application folder. Keep it private. A different Windows user/machine cannot decrypt the profile.
4. Removing the application folder removes its local desktop enrollment/preferences. It does **not** uninstall a separately installed sign-in service or remove its account link; use the [separate removal workflow](windows-signin.md#update-disable-remove) if that is your intention.

## Build an artifact

From a prepared, clean Windows source checkout:

```powershell
.\scripts\setup.ps1
# Commit validated source changes before building a publishable artifact.
.\scripts\build-release.ps1
```

Output is ignored under `desktop/releases/`, or use `-OutputDirectory PATH`. Existing artifacts are never overwritten. `-AllowDirty` builds a clearly marked **local draft only**; do not publish it. The dependency packager copies the installed dependency closure specified by `requirements.txt`, retaining runtime metadata/licenses, rather than copying unrelated packages, pip, or environment leftovers. Models are copied only from the pinned manifest and verified by loading/inference.

On the [`test` branch](https://github.com/notg0d/viso/tree/test), validate the ZIP outside the repository:

```powershell
.\scripts\test-release.ps1 -Archive .\desktop\releases\Viso-0.8.1-windows-x64.zip
```

The test-only runner verifies extracted hashes/exclusions, import isolation under poisoned Python environment variables, real-model blank/portrait inference, private IPC, the actual production `EngineClient`, WPF model-ready startup from a spaces/Unicode path and unrelated working directory, and graceful worker cleanup. Physical current-build enrollment/authentication and a separate clean Windows machine remain outside this automated scope.

Preserve `THIRD_PARTY_NOTICES.md`, `models/licenses/`, the CPython license, and dependency license files when redistributing. The repository does not declare a project-wide license for Viso.
