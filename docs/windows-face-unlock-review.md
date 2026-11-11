# Windows Face Unlock: source review and Viso improvements

[← Documentation](README.md) · [Architecture](architecture.md) · [Validation](testing.md#unreleased-camera-compatibility-and-diagnostics)

Reviewed **2026-11-11**: [caochitam/windows-face-unlock](https://github.com/caochitam/windows-face-unlock), `master` at **`beddcc96b112b393a93062e7d159b2f924008b95`**. All upstream references below are pinned to that revision. This is read-only source inspection, not an installed-system audit, exploit demonstration, biometric benchmark, or validation of its installer. No upstream code/scripts were run or copied into Viso. Its [MIT license](https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/LICENSE) does not license Viso's own code or replace model/dependency notices.

## How it works

```text
User logon → scheduled face_service + presence_monitor tray
                 │                         │
                 │ webcam / DeepFace       └─ periodic presence probe → LockWorkStation
                 │
Enrollment GUI ──┤ pause camera → capture JPGs → build reference embeddings
                 │
LogonUI C++ tile ─┴─ named pipe “unlock” → face verification → saved password
                                              → Windows credential serialization
```

1. **Enrollment:** the tray wizard pauses the service camera, captures JPEGs, and asks the service to build embeddings. `DeepFace.represent` uses ArcFace by default and selects the first returned face per image. Reference vectors are saved to unencrypted `embeddings.npz`; photos remain on disk. This is sample-count enrollment, not measured pose/eye-gated circular coverage. [Wizard][wizard] · [Recognizer, lines 26–62][enrollment]
2. **Verification:** optional `DeepFace.extract_faces(anti_spoofing=True)` evaluates MiniFASNet liveness; a separate representation call supplies the embedding. The best cosine **distance** across references must pass the configured threshold, default 0.45. The service drains two frames and accepts once three of five frames match. There is no prompted blink/open-eye sequence. [Recognizer, lines 64–115][recognition] · [Voting, lines 99–135][voting]
3. **Windows sign-in:** a C++ Credential Provider requests `unlock` from the user's Python service. Successful recognition returns username, domain and decrypted password to the client, which packs them for Windows authentication. Storage uses **user-scope DPAPI**, not passwordless authentication. [Tile][tile] · [Credential return][credential-return] · [Storage][credentials]
4. **Walk-away lock:** the tray checks presence every 60 seconds; two absent strikes trigger `LockWorkStation()` by default. Recognition mode requires the enrolled face; detection mode accepts any face without anti-spoofing. Recent input, pauses and remote-context checks can suppress locking. This is independent of sign-in. [Monitor][monitor] · [Presence modes][presence]
5. **Camera and delivery:** startup tries DirectShow, Media Foundation and an unspecified OpenCV backend across three rounds, validating actual frames and releasing failed handles. The service normally keeps a camera open; enrollment leases it temporarily. PyInstaller/Inno Setup bundle dependencies; the tray offers status, settings and update prompts. [Camera][camera] · [Configuration][config] · [Installer][installer]

## Useful ideas and risks

| Observation | Viso decision |
| :--- | :--- |
| Actual-frame validation and alternate capture backends | Adopt bounded, serial startup fallback; `isOpened()` alone is insufficient. |
| Camera handoff | Keep existing stop/cancel-before-handoff and the service semaphore; no persistent camera or timed lease is needed. |
| Dashboard and bundled delivery | Add explicit runtime/camera diagnostic export. Viso already has a validated extract-and-run ZIP; privileged installation stays separate. |
| ArcFace/MiniFASNet and voting | Consider a separate accuracy/presentation-attack study, not a blind model/dependency replacement. Preserve fresh-blink verification. |
| Presence auto-lock, remote exclusions and multilingual UI | Possible future features. Automatic locking changes behavior and camera residency, so is not added here. |

### Security and lifecycle findings

- **No trusted-peer boundary for credential return.** The server uses a NULL pipe DACL, accepts commands without impersonating/authenticating callers, and returns plaintext credentials after recognition. The C++ client does not authenticate the server process either. Recognition is not permission to receive a password. The README discloses the NULL DACL but calls it acceptable for personal machines. Viso retains SCM server-PID authentication, caller-SID checks, SYSTEM LogonUI-only credential release, vault revision checks and one-use serialization. [Server ACL][acl] · [Commands/pipe handling][pipe-server] · [Client][pipe-client]
- **The “service” starts only at user logon.** Installed tasks use `AtLogOn`, an interactive limited-user principal and `$env:USERNAME`. This does not establish availability before the first login after reboot, correct target identity under alternate-admin elevation, or multi-user isolation with one shared pipe name. Viso uses a LocalSystem SCM service and per-SID vault. Neither project should claim cold-boot/multi-user validation from source alone. [Task registration][tasks]
- **First-face liveness with missing metadata defaulting to true.** Liveness takes `faces[0].get("is_real", True)`; a separate representation call also takes its first face. Source does not explicitly bind the two measurements to one uniquely detected person. Exceptions fail closed, but missing liveness metadata does not. Viso keeps exactly-one-face rejection, associated eye/identity measurements and final fresh open-eye confirmation. [Recognizer][recognition]
- **Fragile credential parsing.** The C++ JSON parser assumes no embedded quotes and uses ad-hoc unescaping. Escaping, Unicode and malformed responses need robust parsing and validation. Viso keeps bounded framing and explicit protocol validation. [Client parser][pipe-client]
- **Checksum failures can fail open.** The updater accepts a missing checksum asset; retrieval/format failures return `None` and still permit installer launch. HTTPS and a hash hosted alongside a binary are not publisher-signature verification. Viso keeps explicit manual release verification, without a self-updater. [Updater, lines 143–193][updater]
- **README claims exceed supplied evidence.** The feature list says photos and videos are blocked; security notes separately exclude deepfake screens. No supplied attack-dataset/error-rate result establishes general replay resistance or “any webcam” compatibility. Viso's blink check is also not proven replay protection or Windows Hello certification. [Claims and security notes][readme]

ArcFace distance 0.45 and SFace similarity 0.55 are **not interchangeable calibrated thresholds**. Model choice, architecture and voting do not establish comparative false-accept/false-reject rates. That requires the same labeled live/attack inputs, cameras, conditions and measured operating points.

## Implemented in Viso source

### Bounded startup fallback

`backend/viso/native.py` now tries, serially:

1. DirectShow with the existing 960×720 open-time negotiation.
2. DirectShow with driver defaults if negotiation/open/initial reads fail.
3. Media Foundation with driver defaults.

Each candidate gets at most three initial reads to supply a nonempty, three-channel uint8 frame. Failed handles are released before another constructor. All share the existing **12-second startup budget**: no repeated rounds, unspecified `CAP_ANY`, post-open size/FPS changes or parallel capture owners. Python cannot forcibly interrupt a blocked native driver call; after timeout, the existing **3-second stop join** applies, and Viso refuses another open while that thread lives. A throwing release retires the Camera until process restart.

Fallback is **startup-only**. Streaming interruption clears retained evidence and stops verification; it never silently reopens or continues an old blink. Six immutable buffered frames, timestamps/freshness, prompt acknowledgment and sign-in's disabled preview encoding remain intact. Old-generation camera-error events cannot cancel a newer desktop session.

OpenCV indices are backend-local, not stable device identities. Media Foundation can order multiple cameras differently from the DirectShow Settings list. Verify preview and exported backend/index after fallback; physical/multi-camera mapping remains a manual gate. No hardware-identity attestation is claimed.

### Privacy-conscious diagnostics

Activity records the selected backend and milliseconds to first frame. **Activity → Export JSON** requests a read-only snapshot containing Python/dependency versions, bitness/isolation, model ID/readiness, storage mode/error flag, camera startup outcomes, dimensions, sampled cadence and frame age. Desktop and Windows version fields accompany it. Export does not start a camera, reload models, call the installed sign-in service or upload anything, and remains available if the worker disconnects.

Diagnostic metadata excludes device names/paths, raw driver/model exceptions, user/machine/account identifiers, profile metadata, images, vectors, tokens, passwords and biometric scores. Existing **session event text can still contain your chosen profile name or an error path**; review/redact it before sharing. Clearing Activity removes events, not the last camera snapshot, which is process-local and replaced on a new camera start. Export camera dimensions are source-frame dimensions; recognition still downsizes to a 960-pixel long edge.

## Validation and delivery boundary

See [current automated checks and limitations](testing.md#unreleased-camera-compatibility-and-diagnostics). Synthetic drivers test actual `Camera` code without physical hardware. Inference, prompt/eye/security, native rendering and packaged shared-runtime gates remain required. Physical fallback, sleep, reboot, multi-camera mapping and current-build Windows authentication are not established by these tests.

These are **unreleased distribution improvements**, developed on `test` before production promotion. The published [v0.8.1 ZIP](releases.md) remains immutable and **does not contain this update**. The user subsequently authorized the `ac7ce8b` source sign-in upgrade: all 3,219 payload hashes, retained enrollment/encrypted links, unchanged non-Viso registrations/filters and 25 installed-runtime checks passed. This source deployment is separate from the new [0.8.2 complete installer](installer.md), which has not been installed or published. Current-build physical camera/unlock and installer lifecycle gates remain open.

[wizard]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/presence_monitor/enroll_gui.py
[enrollment]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/recognizer.py#L26-L62
[recognition]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/recognizer.py#L64-L115
[voting]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/service.py#L99-L135
[tile]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/credential_provider/FaceCredential.cpp
[credential-return]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/service.py#L279-L291
[credentials]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/credentials.py
[monitor]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/presence_monitor/monitor.py
[presence]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/service.py#L137-L201
[camera]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/camera.py
[config]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/config.py
[installer]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/installer/installer.iss
[acl]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/service.py#L57-L64
[pipe-server]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/face_service/service.py#L230-L325
[pipe-client]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/credential_provider/PipeClient.cpp
[tasks]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/installer/postinstall/register_tasks.ps1#L12-L31
[updater]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/presence_monitor/updater.py#L143-L193
[readme]: https://github.com/caochitam/windows-face-unlock/blob/beddcc96b112b393a93062e7d159b2f924008b95/README.md
