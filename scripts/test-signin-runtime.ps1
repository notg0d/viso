$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'signin-common.ps1')
$tests = Join-Path $root 'signin\bin\ServiceTests.exe'
if (-not (Test-Path $tests)) { throw 'Run build-signin.ps1 -Test first.' }
# Synthetic profiles only. No provider/service registration, camera or account password.
$temporary = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp\opencode') ('Viso-runtime-test-' + [Guid]::NewGuid().ToString('N'))
New-Item $temporary -ItemType Directory -Force | Out-Null
try {
    Copy-VisoRuntime $root $temporary
    & $tests --runtime $temporary
    if ($LASTEXITCODE -ne 0) { throw 'Packaged sign-in worker checks failed.' }
} finally { Remove-Item $temporary -Recurse -Force }
