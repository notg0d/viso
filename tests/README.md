# Shared test fixtures

[← Development](../docs/development.md) · [Validation](../docs/testing.md)

`tests/.fixtures/` is the stable, git-ignored location for downloaded public example portraits used by Python and native smoke checks. It remains at the root even though the browser package moved.

```powershell
.\.venv\Scripts\python.exe scripts\download_test_fixtures.py
```

The downloader fetches `obama.jpg`, `obama2.jpg`, and `biden.jpg` from `ageitgey/face_recognition` examples pinned to commit `9f3061aaeed9a8756d2c970f5dfe066617a8281d`. These are functional integration-test inputs, not user enrollment or proof of biometric accuracy.

- Python tests: [`backend/tests/`](../backend/tests/).
- Native raster checks: [`desktop/Viso/RenderingChecks.cs`](../desktop/Viso/RenderingChecks.cs).
- Provider/service tests: [`signin/Tests/`](../signin/Tests/).
- Browser sampler tests: [`experiments/browser/tests/`](../experiments/browser/tests/).

Do not add personal faces or account data to this directory or commit the downloaded fixtures.
