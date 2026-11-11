# Windows desktop releases

[← Documentation](README.md) · [Getting started](getting-started.md) · [Security](security.md)

## Download and run

Get the **ZIP**, not GitHub's automatically generated source-code archives, from the [0.8.1 experimental release](https://github.com/notg0d/viso/releases/tag/v0.8.1):

- **`Viso-0.8.1-windows-x64.zip`** — native desktop plus private Python runtime, pinned dependencies, verified models, and notices.
- **`Viso-0.8.1-windows-x64.zip.sha256`** — archive checksum.

Extract the **entire ZIP** to a folder owned by your Windows user, then open **`Viso.exe`**. Keep the companion folders and `Viso.exe.config` beside it. Do not run it inside the ZIP or copy only the executable. No administrator installation, Python setup, or first-run model download is required.

Requirements: **64-bit Windows 10/11**, **.NET Framework 4.8**, and a webcam for live enrollment. The Image lab works without opening a camera. The executable is **unsigned**; Windows SmartScreen may warn. This is experimental software, not a certified security product.

The ZIP is a directly runnable folder bundle, **not a single-file executable or installer**. Recognition runs locally over private process pipes; it opens no HTTP server. The worker uses Python isolated mode (`-I`) and disables bytecode caches (`-B`), selecting the bundled runtime before a source checkout's `.venv`.

## Verify the download

In PowerShell, in the folder containing both downloaded files:

```powershell
$zip = 'Viso-0.8.1-windows-x64.zip'
$expected = (Get-Content ($zip + '.sha256') -Raw).Split(' ')[0]
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Checksum mismatch. Do not run this download.' }
```

`SHA256SUMS.txt` inside the extracted folder records all payload files except itself. `RELEASE.json` records the production source commit, build date, desktop/Python versions, and the exact installed dependency inventory. Checksums detect corruption; they are not a digital signature or independent proof of publisher identity.

## Enrollment and Windows sign-in

Normal launch stores `.viso/profile.dpapi` and `.viso/desktop.json` beside the app. Enrollment is encrypted for the current Windows user/machine. The ZIP ships without enrollment, credentials, account links, fixtures, tests, browser assets, or development caches.

For memory-only enrollment, open PowerShell in the extracted folder:

```powershell
.\Viso.exe --ephemeral
```

Launching the app does **not** install or change Windows sign-in. The **Unlock test** is a simulator. The ZIP contains no Credential Provider, service binary, or privileged installer. [Windows sign-in installation](windows-signin.md) remains a separate source-based, administrator operation. Settings can explicitly link to an already installed Viso service; use **Link / update account** only if you intend to change its saved snapshot.

RGB face/blink checks are not Windows Hello certified and have no measured replay-resistance guarantee. Keep your Windows password/PIN available. [Privacy and limitations](security.md).

## Update or remove

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
