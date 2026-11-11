# Security & privacy

[← Documentation](README.md) · [Architecture](architecture.md) · [Windows sign-in](windows-signin.md)

## Experimental RGB recognition

Viso is not a replacement for validated biometric authentication. Its functional tests check identity and a prompted bilateral blink followed by reopened eyes. They do **not** establish population-wide accuracy, presentation-attack resistance, or Windows Hello certification.

- Two-circle enrollment borrows a gesture, not Apple's TrueDepth hardware, depth/IR measurements, Secure Enclave architecture, or Face ID error-rate claims.
- Still-photo tests must remain locked. Passing that test does not prove resistance to screen/video replay, generated video, an injected feed, or a virtual camera driver.
- More views provide direction coverage and averaging; they are not a measured biometric accuracy improvement. The compiled matcher is a component optimization, not faster end-to-end authentication evidence.
- Closed, uncertain, or untrackable eyes cannot authorize a successful attempt. Display animation is never identity, pose, eye, or completion evidence.
- Lighting, glasses, camera drivers, eyelid geometry, and real head motion need physical evaluation. Current-build authentication and long-sleep behavior remain [manual validation gates](testing.md#windows-sign-in-validation).

Keep ordinary Windows password/PIN access and use a recoverable test environment for the sign-in prototype.

## Three different boundaries

| Component | Boundary |
| :--- | :--- |
| **Desktop simulator** | Current-user app and Python child process over private redirected pipes. No listening HTTP port; simulated unlock is not an OS credential. |
| **Optional Windows sign-in** | x64 provider → authenticated local named pipe → LocalSystem service → service-owned camera worker. Windows makes the final account-authentication decision. |
| **Historical browser bench** | Loopback HTTP with host/origin checks, bounded requests, a mutation token, and CSP. Client-supplied frames are sandbox input, not trusted physical-camera proof. |

The service accepts no supplied images or biometric success claims. It authenticates the pipe caller and restricts credential release to a SYSTEM `System32\LogonUI.exe` in an interactive session. The worker receives profile/camera data, never the account password. Those controls do not attest camera hardware or exclude every privileged/local attack.

## What is stored

| Location | Contents and protection |
| :--- | :--- |
| `.viso/profile.dpapi` | One desktop profile: metadata, centroid, and camera/image view embeddings, encrypted with **current-user DPAPI**. No enrollment images are stored in the profile. |
| `.viso/desktop.json` | Desktop preferences, separate from face data. This is not an encrypted biometric vault. |
| Memory-only session | Profile lives only in the worker and is not written to disk. Does not create/update a Windows account link. |
| `%ProgramData%\Viso\Accounts\<SID>.dpapi` | Optional sign-in account kind/name, **saved account password**, imported profile snapshot, camera index, and revision, encrypted with **machine-scope DPAPI**. Administrators/SYSTEM-only ACLs are essential. |
| Activity/export | Session timestamps and decision messages; no face vectors or camera frames. |
| `tests/.fixtures/` / `test-results/` | Development-only public portraits and automated artifacts, ignored by Git. Not user enrollment. |

Current-user DPAPI protects data at rest, not against every process running as the same Windows user. Machine-scope DPAPI alone is not per-user isolation; protected ProgramData ownership/ACLs and service caller checks provide that isolation. A profile cannot be ported by simply copying its encrypted file to another user/machine.

Recognition runs locally after package/model setup. The pinned MediaPipe package is recorded in [third-party notices](../THIRD_PARTY_NOTICES.md); reassess upstream behavior before upgrading it. No cloud biometric service is part of this implementation.

## Account changes and revocation

Account linking validates the password and requires the resulting SID to match the caller. Links keep a **snapshot**, so enrollment, password, camera, or account identity changes require explicit **Link / update account**.

Unlink/relink invalidates older revisions and pending work. A credential already released to LogonUI is usable once for at most ten seconds; unlink cannot retract a serialization Windows has already received. Suspend, cancellation, deselection, deadlines, and service shutdown revoke pending work. [Full lifecycle and removal rules](windows-signin.md#update-disable-remove).

Passwords are not logged/exported. Byte buffers and native strings are cleared where possible; guaranteed immediate erasure of all immutable .NET string copies is **not** claimed. Administrator/SYSTEM access is outside a promise of credential secrecy.

## Sharing issues and artifacts

Do not commit `.viso/`, ProgramData account records, personal face samples, passwords, or dumps containing secrets. Review exported logs/screenshots before sharing. Report a suspected credential-release bypass without posting a usable exploit or sensitive account material in a public issue. [Contribution guidance](../CONTRIBUTING.md).
