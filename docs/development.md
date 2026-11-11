# Development

[← Documentation](README.md) · [Architecture](architecture.md) · [Testing](testing.md) · [Script index](../scripts/README.md)

## Repository map

| Path | Responsibility |
| :--- | :--- |
| [`desktop/Viso/`](../desktop/Viso/) | Primary C#/WPF app, embedded XAML, camera catalog, native motion, Settings, and process client. |
| [`backend/viso/`](../backend/viso/) | Recognition, attention, circular enrollment, attempts, storage, and native/sign-in/HTTP transports. |
| [`backend/tests/` on `test`](https://github.com/notg0d/viso/tree/test/backend/tests) | Python unit, protocol, resource, and real-model integration checks; not on `main`. |
| [`signin/Provider/`](../signin/Provider/) | x64 C++ V2 Credential Provider and protected Windows credential packing. |
| [`signin/Service/`](../signin/Service/) | LocalSystem service, account vault, worker ownership, and power/deadline handling. |
| [`signin/Shared/`](../signin/Shared/) | C# Windows interop and bounded named-pipe protocol; also compiled into the desktop. |
| [`signin/Tests/` on `test`](https://github.com/notg0d/viso/tree/test/signin/Tests) | Actual DLL and service/protocol regressions; synthetic credentials only, not on `main`. |
| [`scripts/`](../scripts/) | Stable root-relative setup/build/test/deployment commands. |
| [`installer/`](../installer/) | All-in-one Inno wizard and protected payload deployment/recovery helper. |
| [`models/manifest.json`](../models/manifest.json) | Version-pinned model sizes, sources, and SHA-256 values. |
| [`tests/` on `test`](https://github.com/notg0d/viso/blob/test/tests/README.md) | Shared downloaded portrait-fixture location. Browser tests live with the browser package. |
| [`experiments/browser/` on `test`](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md) | Historical React/TypeScript/Vite bench with its own package and lockfile; not on `main`. |
| [`docs/`](README.md) | Guides, reference, validation records, research, and historical notes. |

The native startup code discovers the root by finding `backend/run_native.py`. In source checkouts, keep `desktop/`, `backend/`, `signin/Shared/`, `.venv/`, and `models/` in their documented locations. Release ZIPs keep `Viso.exe` at the root and substitute a private `runtime/` for `.venv/`. Do not relocate local data as part of routine cleanup.

## Build the native desktop

From PowerShell in the repository root:

```powershell
.\scripts\setup.ps1
.\scripts\build-native.ps1
.\scripts\start.ps1 -Ephemeral
```

No Node.js or .NET SDK is needed. The x64 build uses the installed .NET Framework compiler and embeds `MainWindow.xaml`. Normal builds exclude rendering-test helpers. Close the app before replacing `desktop\bin\Viso.exe`.

Python dependency versions are in `requirements.txt`; model versions/hashes are in `models/manifest.json`. Setup deliberately removes the competing `opencv-python-headless` distribution before installing the single contrib wheel required by MediaPipe.

For a directly runnable Windows bundle, use `scripts/build-release.ps1` from committed sources. [Packaging, provenance, and extracted-artifact validation](releases.md#build-an-artifact).

For a complete desktop/runtime/models/sign-in Setup.exe, use `scripts/build-installer.ps1 -Compiler PATH` from clean committed production sources. Inno Setup is build-only; building does not deploy anything. [Installer build, storage and lifecycle validation](installer.md).

## Validate changes

**Use a `test` checkout for this section.** `main` contains production source and documentation, not regression suites, test runners, fixture downloaders, rendering helpers, benchmarks, or the Markdown checker. With a clean working tree, switch to `test`, or use a separate checkout; do not run missing test commands on `main`.

```powershell
# Full Python suite plus native smoke/raster checks; downloads public test fixtures
.\scripts\test.ps1

# Python only
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v

# Native only, without opening a physical camera
.\scripts\build-native.ps1 -SmokeTest

# Local Markdown links, anchors, and documentation assets
.\.venv\Scripts\python.exe scripts\check-docs.py

git diff --check
```

Real-model integration tests can skip when fixtures are absent; `test.ps1` downloads them. Test profiles are temporary or memory-only. Native artifacts go to `test-results/native/`. Do not run native smoke concurrently with another smoke run: they share the output directory.

For provider/service changes, with the C++ tools and Windows SDK installed:

```powershell
.\scripts\build-signin.ps1 -Test
.\scripts\test-signin-runtime.ps1
```

These component/runtime checks do not register a provider, open the camera, or use real account passwords. They do not replace [integrated manual validation](testing.md#windows-sign-in-validation). **Building is not installing.** Deployment requires a separate, intentional administrator operation; see [Windows sign-in](windows-signin.md).

To reproduce the matcher component benchmark:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_matcher.py
```

## Browser experiment

On `test`, the browser package is isolated in `experiments/browser/`, not a root workspace or desktop dependency. It is excluded from `main`. Its `package-lock.json` moves with it and dependency versions remain unchanged. [Bench instructions and compatibility limits](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md).

The optional Python HTTP host serves `experiments/browser/dist/`. The old root `dist/` is not served. Vite remains on `127.0.0.1:5173` and proxies `/api` to `127.0.0.1:8765`. The archived browser's five-pose guidance is **not** the current circular-enrollment UI.

## Branch and release workflow

| Branch | Keep here |
| :--- | :--- |
| `main` | Production app/backend/sign-in/installer code, build/deployment entry points and shared docs. |
| `test` | Production implementation plus regression sources, test/fixture runners, benchmarks and `experiments/browser/`. |

Develop and validate on `test`, committing production changes separately from test-only work. Promote only the production/documentation commits to `main` with selective cherry-picks; never merge all of `test` into `main`. Preserve deliberate smoke-only assertions and branch-specific ignore rules. Check `git diff main test` before pushing: production differences require explanation; added test/bench files must remain test-only.

Build publishable artifacts from a **clean production commit**, run the applicable artifact checks using `test` tools without embedding those tools, and publish the source commit before distributing bundled commit-pinned links. Tag the exact build commit. A later documentation cleanup does not move a release tag or change provenance; the v0.8.2 tag remains on `3f35b09` and the original v0.8.1 release stays unchanged.

Release assets belong on GitHub Releases, not in source commits. For the complete installer, upload only Setup.exe, `.sha256`, provenance `.json` and the exact-build validation `.json`; exclude payload staging, superseded installers, profiles, credentials, models downloaded outside a release and development environments. Keep experimental status and unverified manual gates explicit. Branch/release publication never authorizes installation.

## Generated files and local state

Ignored paths include `.venv/`, `.viso/`, `node_modules/`, `dist/`, model weights/licenses, Python/TypeScript caches, `desktop/bin/`, `desktop/releases/`, `signin/bin/`, `tests/.fixtures/`, and `test-results/`. The dependency/build ignore patterns also cover the nested browser package.

Existing ignored root `src/`, `node_modules/`, `dist/`, and `tsconfig.tsbuildinfo` can remain from the former browser layout; they are not published as production source. Fresh browser installs/builds belong under `experiments/browser/`. Repository cleanup must not delete `.viso/`, `%LOCALAPPDATA%\Viso`, protected account records, a working environment, release artifacts or unfamiliar user work. Native paths and local enrollment/account links are unchanged.

## Documentation conventions

- Keep first-run instructions in [Getting started](getting-started.md), privileged deployment in [Windows sign-in](windows-signin.md), and the README short and product-focused.
- Use relative links for shared documentation. Use explicit `test`-branch links for sources/tools intentionally absent from `main`.
- Record version/date/environment and measured scope with benchmark or validation claims. Keep earlier evidence in `docs/history/`; never imply it proves the current build.
- Keep desktop and installed sign-in versions separate. Branch publication is not a tagged product release.
- Check local links with `scripts/check-docs.py`; external URLs still need human review.
- Keep attribution and full upstream notices. No project-wide license is declared in this repository; upstream licenses do not assign one to Viso as a whole.
