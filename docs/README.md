# Viso documentation

[← Project overview](../README.md)

Start with the desktop. The all-in-one installer includes Windows sign-in; read its requirements and recovery guidance before approving installation.

## Use Viso

| Guide | You'll find |
| :--- | :--- |
| [Getting started](getting-started.md) | Requirements, setup, two-circle enrollment, unlock simulator, photo lab, and controls. |
| [Windows releases](releases.md) | Complete installer versus desktop-only ZIP, checksums, requirements, local-state updates, and artifact builds. |
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

## Releases and test tools

| Record | You'll find |
| :--- | :--- |
| [Validation commands](development.md#validate-changes) | Reproduce automated checks from the `test` branch. |
| [Changelog](../CHANGELOG.md) | Concise version history; desktop and sign-in versions kept separate. |
| [Browser experiment on `test`](https://github.com/notg0d/viso/blob/test/experiments/browser/README.md) | Running the archived React/Vite bench without making it a desktop dependency. |

## Read the status correctly

The latest recorded snapshot is **2026-11-11**: the [v0.8.2 all-in-one Setup.exe](https://github.com/notg0d/viso/releases/tag/v0.8.2) is published as an **experimental pre-release**, built from clean production commit `3f35b09`. The public [v0.8.1 desktop-only ZIP](releases.md) remains unchanged. The separately authorized **`ac7ce8b` source sign-in update** is the last agent-verified development-machine installation; GitHub publication did not install or verify the new Setup on that machine. None of these is general authentication certification. Changes are developed/validated on `test`; only production source/documentation is promoted to `main`. Regression sources, runners/fixtures, benchmarks, and the historical browser bench remain **test-only**.

Automated checks use synthetic state, temporary storage, and public portrait fixtures; they do not prove physical-camera accuracy or replay resistance. Earlier successful local-account unlocks do not validate the current sign-in build. Clean-machine installer lifecycle, current-build authentication, reboot, long sleep, Microsoft-account and multi-user tests remain necessary. Personal research and validation reports are kept locally, not in this repository.
