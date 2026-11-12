# Historical browser bench

[← Viso](../../README.md) · [Development](../../docs/development.md)

This is the earlier React/TypeScript/Vite recognition sandbox. **It is not the current Windows desktop UI and is not required to build or run Viso.** Its source, package/lockfile, configs, and camera-sampler tests are kept together here.

> [!WARNING]
> The archived guidance assumes five poses/four directional sectors. The current backend uses two eight-direction circuits; this browser UI has **not** been ported or end-to-end validated for circular enrollment. Use the native app for enrollment and current product testing. The photo/API bench and sampler tests remain development references.

## Build and test

Use a Node.js version supported by the locked Vite package (**20.x ≥20.19 or ≥22.12**, per its engine range) and npm. From the repository root:

```powershell
npm --prefix experiments/browser ci
npm --prefix experiments/browser test
npm --prefix experiments/browser run build
```

No new runtime dependencies were added during the move; the dependency lock and versions are retained. Outputs are `experiments/browser/dist/` and local TypeScript build info, both ignored.

## Optional local host

After [Python/model setup](../../docs/getting-started.md), run from the root in one terminal:

```powershell
# Always use memory-only storage when exploring this historical bench
.\.venv\Scripts\python.exe -m backend.viso.server --ephemeral
```

The host binds to `127.0.0.1:8765` and serves **this package's** `dist/`, not an old root build. It also exposes the current sandbox API. `--ephemeral` avoids replacing the desktop's persistent profile. Do not use this bench to manage a linked sign-in profile.

For Vite development, use another terminal:

```powershell
npm --prefix experiments/browser run dev
```

Vite listens on `127.0.0.1:5173` and proxies `/api` to port `8765`. Open the printed local URL; stop both processes when finished. The native app starts neither server.

The four sampler tests transpile the actual `src/media.ts` with the locked TypeScript compiler and exercise deterministic video/clock behavior. A passing build/sampler test does not validate the archived enrollment screen against today's backend.

## Attribution

The Glance-derived ring/light adaptations remain subject to [the full third-party notices](../../THIRD_PARTY_NOTICES.md). The root `.gitignore` covers nested dependencies/builds. Existing generated root browser folders were not removed by the reorganization.
