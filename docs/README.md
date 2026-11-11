# Viso documentation

[← Project overview](../README.md)

Start with the desktop. The all-in-one installer includes Windows sign-in; read its requirements and recovery guidance before approving installation.

## Use Viso

| Guide | You'll find |
| :--- | :--- |
| [Getting started](getting-started.md) | Requirements, setup, two-circle enrollment, unlock simulator, photo lab, and controls. |
| [Windows releases](releases.md) | Runnable ZIP, checksum verification, requirements, local-state updates, and artifact builds. |
| [Complete Windows installer](installer.md) | All-in-one desktop/runtime/models/sign-in Setup.exe, storage, upgrades, removal and recovery. |
| [Windows sign-in](windows-signin.md) | Account support, administrator installation, explicit linking, upgrades, disable/removal, and diagnostics. |
| [Troubleshooting](troubleshooting.md) | Camera, models, builds, profiles, blink confirmation, and sign-in failures. |

## Understand and develop

| Reference | You'll find |
| :--- | :--- |
| [Architecture](architecture.md) | Desktop/worker and provider/service flows, recognition rules, capture timing, and the legacy API. |
| [Security & privacy](security.md) | Simulator vs authentication, RGB limitations, stored data, passwords, and trust boundaries. |
| [Development](development.md) | Repository map, native builds, test commands, generated files, and browser isolation. |
| [Script index](../scripts/README.md) | What each entry point does, prerequisites, and whether it changes Windows. |
| [Contributing](../CONTRIBUTING.md) | Change scope, safety expectations, validation, and useful issue reports. |
| [Third-party notices](../THIRD_PARTY_NOTICES.md) | Model sources, library licenses, and Glance attribution. |

## Evidence and history

| Record | You'll find |
| :--- | :--- |
| [Testing & validation](testing.md) | Current automated coverage, reproduction commands, manual scenarios, and open release gates. |
| [Measured performance](performance.md) | Component benchmarks, camera-start measurements, memory residency, and measurement limits. |
| [Enrollment, resources & wake research](enrollment-resume-research.md) | Primary sources, pre-implementation decisions, deployment checks, and the desktop hotfix. |
| [Windows Face Unlock review](windows-face-unlock-review.md) | Pinned source comparison, security/lifecycle findings, and unreleased camera/diagnostic improvements. |
| [Changelog](../CHANGELOG.md) | Concise version history; desktop and sign-in versions kept separate. |
| [Earlier native validation](history/native-validation.md) | The 0.7.1 physical-camera and automatic-submit results. |
| [Earlier browser validation](history/browser-validation.md) | Historical 0.3–0.5 browser experiments and their limitations. |
| [Browser experiment on `test`](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md) | Running the archived React/Vite bench without making it a desktop dependency. |

## Read the status correctly

The latest recorded snapshot is **2026-11-11**: desktop/complete-installer source **0.8.2**, with the separately authorized **`ac7ce8b` source sign-in update** installed on the development machine. The public [v0.8.1 desktop-only ZIP](releases.md) remains unchanged; the [all-in-one Setup.exe](installer.md) has not been published or deployed. None of these is general authentication certification. Changes are developed/validated on `test`; only production source/documentation is promoted to `main`. Regression sources, runners/fixtures, benchmarks, and the historical browser bench remain **test-only**.

Automated checks use synthetic state, temporary storage, and public portrait fixtures; they do not prove physical-camera accuracy or replay resistance. Earlier successful local-account unlocks do not validate the current sign-in build. See the [current evidence and remaining gates](testing.md).
