param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    # MediaPipe depends on the contrib wheel; only one distribution may own cv2.
    & '.\.venv\Scripts\python.exe' -m pip uninstall -y opencv-python-headless
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & '.\.venv\Scripts\python.exe' scripts/download_models.py
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Re-run setup to retry.' }
    if (Test-Path 'package-lock.json') { npm ci } else { npm install }
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    if (-not $SkipBuild) {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    }
    Write-Host 'Viso is ready. Run: .\scripts\start.ps1' -ForegroundColor Green
} finally {
    Pop-Location
}
