param([switch]$NoBrowser, [switch]$Ephemeral, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if (-not (Test-Path '.venv\Scripts\python.exe') -or -not (Test-Path 'dist\index.html')) {
        throw 'Run .\scripts\setup.ps1 first.'
    }
    $arguments = @('-m', 'backend.viso.server', '--port', "$Port")
    if (-not $NoBrowser) { $arguments += '--open' }
    if ($Ephemeral) { $arguments += '--ephemeral' }
    & '.\.venv\Scripts\python.exe' @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Viso stopped with an error.' }
} finally {
    Pop-Location
}
