$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    & '.\.venv\Scripts\python.exe' scripts/download_test_fixtures.py
    if ($LASTEXITCODE -ne 0) { throw 'Test fixture download failed.' }
    & '.\.venv\Scripts\python.exe' -m unittest discover -s backend/tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    & (Join-Path $PSScriptRoot 'build-native.ps1') -SmokeTest
} finally {
    Pop-Location
}
