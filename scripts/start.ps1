param([switch]$Ephemeral)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        throw 'Run .\scripts\setup.ps1 first.'
    }
    $executable = Join-Path $root 'desktop\bin\Viso.exe'
    $sources = @(Get-ChildItem (Join-Path $root 'desktop\Viso'), (Join-Path $root 'signin\Shared') -File -Recurse)
    $sources += Get-Item (Join-Path $PSScriptRoot 'build-native.ps1'), (Join-Path $PSScriptRoot 'build-icon.ps1')
    $newestSource = $sources | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if (-not (Test-Path $executable) -or $newestSource.LastWriteTimeUtc -gt (Get-Item $executable).LastWriteTimeUtc) {
        & (Join-Path $PSScriptRoot 'build-native.ps1')
    }
    $launch = @{ FilePath = (Join-Path $root 'desktop\bin\Viso.exe'); WorkingDirectory = $root }
    if ($Ephemeral) { $launch.ArgumentList = '--ephemeral' }
    Start-Process @launch
} finally {
    Pop-Location
}
