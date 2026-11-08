# Responsiveness: 0.7.1

## Camera startup fix (0.7.1)

The shared desktop/sign-in camera path previously opened the default stream, restarted it to change resolution, and restarted it again to request 30 fps. The pinned OpenCV 4.13 DirectShow backend accepts width/height in its constructor, so 0.7.1 negotiates the stream before its first start and uses the camera's default cadence. Frames retain their capture timestamps and the existing freshness and blink checks.

Measured on camera index 0 on 2026-11-08; frames were not saved:

| Measurement | Time to first raw frame |
|---|---:|
| Previous setup, one instrumented run | 4.489 s |
| Updated desktop camera path, three runs | 1.388 / 1.031 / 1.043 s |
| Updated sign-in camera path, three runs | 1.059 / 1.048 / 1.014 s |

The previous run spent 1.391 s reconfiguring resolution and 1.624 s setting nominal FPS. Both paths delivered 960×540 frames from the same 960×720 size request. Separate 60-frame probes measured about 17.3–17.4 fps with and without the nominal FPS setting in the available light; requesting 30 fps did not make this camera deliver 30 fps. These are local camera-start timings, not full authentication timings or guarantees for other hardware. The updated capture checks also verified immutable raw frames and release/queue cleanup across all six opens.

After this change, all 99 Python checks and the native WPF smoke checks passed. The desktop assembly, manifest, and visible Settings version now identify 0.7.1.

## Automatic-submit handoff fix (0.7.1)

Interactive testing confirmed automatic scanning and faster camera startup, but exposed a callback lifecycle error after successful blink verification. The Windows trace showed `verification accepted → CredentialsChanged → credential UnAdvise → SetSelected`. Clearing all state in `UnAdvise` discarded the verified result before Windows could serialize it; manually retrying subsequently signed in successfully.

`UnAdvise` now cancels pending work/callbacks while retaining only an already verified result inside its original 10-second deadline. Actual deselection, disconnect, provider teardown, expiry, and serialization still clear it. Provider regression checks cover the observed refresh sequence, one-use serialization, expiry, and cancellation. Provider, 47 service, 3 sign-in worker, and 11 deployment checks passed after this fix.

The installed fix was confirmed interactively on 2026-11-08: the user unlocked Windows automatically after blinking, without pressing the arrow. The trace at 23:05:22 showed `UnAdvise → GetCredentialCount automatic → Connect (verified result present) → GetSerialization → credential packed → ReportResult 0x00000000`.

## Earlier 0.7 improvements

Measured on the development Windows machine on 2026-11-08, using the existing Python environment, CPU models, and an ephemeral profile. These are local component timings, not a lock-to-desktop benchmark.

| Measurement | Earlier implementation | 0.7 |
|---|---:|---:|
| Native worker command/profile status, repeat launch | 1.79 s | 0.41 s median of 3 launches |
| Models fully ready, repeat launch | 1.79 s | 1.41 s median of 3 launches |
| Portrait identity frame, including camera conversion | 49.03 ms JPEG roundtrip | 39.35 ms raw frame |
| Minimum enrollment hold | 350 ms / 3 observations | 240 ms / 3 observations |
| Minimum return-to-center hold | 200 ms / 3 observations | 120 ms / 2 observations |

The first pre-change worker launch took 4.65 s; the repeated measurement above is the closer comparison to cached post-change launches. The new desktop can show stored profile/settings information before model initialization completes. Camera actions remain unavailable until successful model initialization.

The frame comparison used the same 720×900 portrait, warmed models, and 24 observations per path. Both paths detected one face and open eyes. It includes encoding, base64 conversion, and decoding for the former native camera path. Model accuracy thresholds and blink confirmation timing were not changed.

The sign-in standby worker loaded its models in 1.46 s before receiving any profile. A subsequent synthetic profile validation dispatched in 0.63 ms. That measures ready-worker dispatch only, not face verification. Real scan latency also includes the camera driver opening, exposure settling, finding a usable face, the user's blink, and Windows authentication. Those end-to-end timings require testing the installed update.

## Verification

- 99 Python checks: identity/eye behavior, raw frame validation, no sign-in JPEG encoding, no duplicate enrollment sampling, wider pose regions, prompt acknowledgment, stale frames, cancellation, and profile storage.
- Native provider checks: actual DLL activation, local/MSA protected credential packing, automatic selection, UI-thread status callbacks, no automatic retry loop, canceled queued callbacks, unload, and no serialization before verification.
- 47 C# service checks, including cancellation/deadlines during a blocked startup write; 11 deployment ownership/ACL/reparse checks.
- Packaged isolated-runtime imports, model checksums, real blank-frame inference, plus 6 service-to-worker checks including model-only prewarm, one-shot completion, profile rejection, and Job cleanup.
- Native WPF smoke/render checks, including camera preview, profile-name input, reduced motion, five pages, minimum layout, and real model IPC.

The previously installed service/provider/worker were found to predate 0.7 even though the desktop executable was updated. The automatic-scan components and single-open camera fix have now been installed on the development machine: binary/source hashes, 64-bit registration, automatic service startup, one standby worker, unchanged account link, and six installed-runtime checks were verified. Automatic selection, faster camera startup, and successful automatic unlock were confirmed interactively. Building the desktop does not replace an already installed service/provider/runtime.
