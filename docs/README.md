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

The [v0.8.5 complete installer](https://github.com/notg0d/viso/releases/tag/v0.8.5) is an **experimental pre-release**. The [v0.8.1 portable ZIP](releases.md) remains desktop-only. Each installer includes exact source provenance and a validation record. Production code and shared docs are on `main`; regression suites, benchmarks and the browser experiment are on `test`.

Automated checks use synthetic state, temporary storage and public portrait fixtures. They do not establish biometric accuracy or replay resistance. Clean-machine installation, varied cameras, reboot, long sleep, Microsoft-account and multi-user scenarios require separate physical validation.
