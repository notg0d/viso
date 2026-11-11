param([Parameter(Mandatory=$true)][string]$Archive, [switch]$AllowDirty)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$archive = [IO.Path]::GetFullPath($Archive)
$temporary = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp\opencode') ('Viso portable ' + [char]0x674e + ' ' + [Guid]::NewGuid().ToString('N'))
New-Item $temporary -ItemType Directory | Out-Null
try {
    $expected = (Get-Content -LiteralPath ($archive + '.sha256') -Raw).Split(' ')[0]
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Archive SHA-256 does not match.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $temporary
    $bundle = (Get-ChildItem -LiteralPath $temporary -Directory | Select-Object -First 1).FullName
    $arguments = @('-I', '-B', "$root\backend\tests\validate_release.py", $bundle, "$root\tests\.fixtures\obama.jpg")
    if ($AllowDirty) { $arguments += '--allow-dirty' }
    & "$root\.venv\Scripts\python.exe" @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Extracted release runtime validation failed.' }

    # Run x64 Framework reflection/UI Automation in a matching host. Tests stay outside the ZIP.
    $nativeHost = if ([Environment]::Is64BitProcess) { "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" } else { "$env:WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" }
    & $nativeHost -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\test-release-desktop.ps1" -Bundle $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Extracted production desktop validation failed.' }
    Write-Host 'Extracted release passed runtime, production client, WPF startup and child cleanup checks.' -ForegroundColor Green
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
