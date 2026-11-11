# Script index

[← Development](../docs/development.md) · [Testing](../docs/testing.md) · [Windows sign-in](../docs/windows-signin.md)

Run commands from the repository root in PowerShell. Python scripts use `.venv\Scripts\python.exe` after setup. **Build/test commands do not install Windows sign-in.** Production entry points are shared; validation-only scripts in the next section and `build-signin.ps1 -Test` require the `test` branch. `main` excludes their sources and the historical browser bench.

## Desktop and recognition

| Entry point | Purpose | Important details |
| :--- | :--- | :--- |
| `setup.ps1 [-SkipBuild]` | Create environment, install pinned packages, verify/download models, build desktop. | Needs Python and internet; no administrator installation. |
| `start.ps1 [-Ephemeral]` | Rebuild stale/missing native executable and launch. | Memory-only enrollment with `-Ephemeral`; normal launch uses current-user DPAPI. |
| `build-native.ps1 [-SmokeTest] [-OutputDirectory PATH]` | Build x64 C#/WPF executable. | .NET Framework 4.8; close running app first. Smoke uses synthetic/temp state, not a physical camera. |
| `build-release.ps1 [-OutputDirectory PATH] [-AllowDirty]` | Build runnable Windows ZIP and SHA-256 file. | Private Python/dependencies/models; no sign-in installer. Clean sources required unless explicitly building a local draft. [Release guide](../docs/releases.md). |
| `package-runtime.py ROOT DESTINATION` | Copy the installed dependency closure into a private runtime. | Called by packaging helpers with the project's `.venv` Python; keeps notices, excludes caches/test folders/pip/unrelated packages. |
| `download_models.py` | Download pinned models and upstream notices; verify SHA-256. | Writes ignored weights/licenses under `models/`. |

## Validation and evidence

| Entry point | Purpose | Important details |
| :--- | :--- | :--- |
| `test.ps1` | Download public portraits, run Python suite, build/smoke native app. | Writes `tests/.fixtures/` and `test-results/native/`; no physical camera. |
| `download_test_fixtures.py` | Fetch three pinned public example portraits. | Test inputs only, never user enrollment or app distribution. |
| `benchmark_matcher.py` | Deterministic matcher component comparison. | Writes `test-results/matcher.json`; not biometric accuracy or end-to-end latency. |
| `check-docs.py` | Validate local Markdown links, anchors, and image paths. | Standard-library only; excludes ignored/generated trees; does not fetch external links. |
| `test-signin-deployment.ps1` | Check ownership/ACL/reparse-point deployment rules. | Temporary synthetic paths; does not install/register components. |
| `test-signin-runtime.ps1` | Package private runtime and exercise service/worker checks. | Run `build-signin.ps1 -Test` first; temporary payload, no passwords/camera/registration. |
| `test-release.ps1 -Archive PATH [-AllowDirty]` | Validate a ZIP after extraction outside the repository. | Runtime isolation, hashes/exclusions, inference, production client, WPF startup and cleanup; spaces/Unicode paths. Test-only desktop helper stays outside the ZIP. |

## Optional privileged deployment

| Entry point | Purpose | Important details |
| :--- | :--- | :--- |
| `build-signin.ps1 [-Test]` | Build C++ provider and C# service; optionally run regressions. | Requires x64 C++ Build Tools + Windows SDK; build/tests do not install. |
| `install-signin.ps1` | Install protected payload, start LocalSystem service, register provider. | **64-bit administrator PowerShell. Changes Windows sign-in.** Read the full guide first. |
| `uninstall-signin.ps1 [-KeepAccountLinks]` | Remove Viso registration/service/payload. | **Administrator. Deletes account records by default.** Keep links only for an intended upgrade. |
| `signin-common.ps1` | Shared deployment/runtime helpers. | Sourced by entry points; not a standalone installer. |

Do not run installation/removal as part of routine tests or repository cleanup. [Retained-link upgrade and recovery instructions](../docs/windows-signin.md#update-disable-remove).
