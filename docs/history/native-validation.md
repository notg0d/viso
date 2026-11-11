# Earlier native validation

[← Documentation](../README.md) · [Current validation](../testing.md) · [Historical measurements](../performance.md)

This record concerns **0.7.1 on 2026-11-08**, not the current 0.8.0 sign-in build or 0.8.1 desktop hotfix. It is retained so physical results are not confused with newer synthetic coverage.

At that release, production source matched `main`; validation files and the earlier browser bench remained on `test`. The local run passed 99 Python checks, provider checks against the actual DLL (including automatic selection and UI-thread callbacks), 47 service checks, 11 deployment checks, 6 installed-runtime checks, and native smoke/render checks.

The 0.7.1 provider regression reproduces Windows' `UnAdvise`/`Advise` refresh between successful verification and automatic submission. It checks that a fresh result survives the refresh, serializes once, expires on its original deadline, and is cleared by deselection, disconnect, or provider teardown. Its injected credential is synthetic and the access helper is compiled only into the tests.

Six physical-camera opens exercised the shared desktop/sign-in capture paths and release/queue cleanup. Camera startup improved from one measured 4.489 s baseline to medians of 1.043 s (desktop) and 1.048 s (sign-in), with the same 960×540 raw frames. After installing the updates while retaining the account link, the user confirmed fast automatic scanning and successful Windows unlock without pressing the arrow. The provider trace recorded successful serialization and `ReportResult 0x00000000`; temporary tracing was then disabled.

New regressions covered raw camera input, no JPEG work for sign-in, distinct enrollment frames, broader pose regions, asynchronous desktop initialization, model-only one-shot prewarm, canceled queued provider callbacks, and disconnect/deadline handling while startup writes were blocked.

See [exact measurements and caveats](../performance.md#camera-startup-fix-071). These local observations do not establish other-camera, Microsoft-account, multi-user, reboot, long-sleep, or presentation-attack behavior.
