# Responsiveness: 0.7

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

The earlier installed flow was reported working by its user. The new automatic-selection behavior still needs interactive LogonUI/reboot validation after installing 0.7. The build does not replace an already installed service/provider.
