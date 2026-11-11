# Contributing to Viso

Start with the [development guide](docs/development.md), [architecture](docs/architecture.md), and [security limitations](docs/security.md).

## Keep changes focused

- The C#/WPF desktop is the primary app. Keep the historical browser package isolated; do not introduce it as a desktop dependency.
- Keep production commits separate from test-only changes. Validate on `test` and promote selected production/documentation commits to `main`; never merge test suites, runners/fixtures or the browser bench into `main`. See the [branch and release workflow](docs/development.md#branch-and-release-workflow).
- Preserve server-owned identity/pose/eye evidence, fresh blink acknowledgment, one-use credentials, cancellation, account binding, and power-generation checks. UI progress is not authentication evidence.
- Preserve reduced-motion behavior, responsive/minimum layouts, camera/worker cleanup, and current-user data. Do not silently relink accounts or reset profiles.
- Avoid dependency/model changes without a reason, provenance/license review, and corresponding validation.
- Build and test before proposing installation. Never include real credentials, personal profiles, or generated private data in a change.

## Before submitting

1. Describe the problem, scope, and observable behavior change.
2. Run the relevant [validation commands](docs/development.md#validate-changes). Add a deterministic regression for a bug where practical.
3. Update the applicable guide/reference and [changelog](CHANGELOG.md). Keep historical evidence separate from current results.
4. Run `scripts/check-docs.py` from `test` and `git diff --check`. Validation tools/sources stay off production-only `main`.
5. State what was not tested, especially physical-camera, sleep/reboot, Microsoft-account, and multi-user scenarios. Automated success is not biometric certification.

For security-sensitive changes, explain how failure, cancellation, stale evidence, and concurrency remain fail-closed. Use synthetic credentials and temporary storage in tests. Integrated sign-in tests belong on a recoverable Windows machine/VM with normal sign-in available.

## Reporting a problem

Include:

- Windows version and architecture; Python and package versions if relevant.
- Desktop version and **separate installed sign-in version**, plus branch/commit when known.
- Camera model/index, lighting/glasses context, and whether the issue is in the simulator or Windows sign-in.
- Exact actions, expected/actual behavior, and reproducibility.
- A redacted error/log excerpt; see [Troubleshooting](docs/troubleshooting.md).

Do not attach account passwords, `.viso/profile.dpapi`, ProgramData account records, private face images, or memory dumps with secrets. Avoid publishing a usable credential-release exploit before a safe reporting channel is agreed.

## Licensing and attribution

Preserve [third-party notices](THIRD_PARTY_NOTICES.md) and model provenance. This repository currently declares no project-wide license; the included upstream MIT/Apache/etc. notices apply to those components, not automatically to all Viso code. Licensing decisions need the owner's explicit approval.
