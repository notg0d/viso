#Requires -RunAsAdministrator
param([switch]$KeepAccountLinks)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'signin-common.ps1')
$clsid = '{4965C343-8550-499A-A734-512863668D12}'
$destination = Join-Path $env:ProgramFiles 'Viso'
if (-not [Environment]::Is64BitProcess) { throw 'Run this uninstaller in 64-bit PowerShell.' }
# Remove only Viso's registration; built-in providers are never filtered or edited.
Remove-Item "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$clsid" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "HKLM:\SOFTWARE\Classes\CLSID\$clsid" -Recurse -Force -ErrorAction SilentlyContinue
if (Get-Service VisoSignIn -ErrorAction SilentlyContinue) {
    Stop-Service VisoSignIn -Force
    & sc.exe delete VisoSignIn
    if ($LASTEXITCODE -ne 0) { throw 'Windows could not remove the VisoSignIn service.' }
}
$data = Join-Path $env:ProgramData 'Viso'
if (-not $KeepAccountLinks -and (Test-Path $data)) {
    Assert-VisoTree $data $false
    $accounts = Join-Path $data 'Accounts'
    if (Test-Path $accounts) { Remove-Item $accounts -Recurse -Force }
}
if (Test-Path $destination) { Assert-VisoTree $destination $true }
try { if (Test-Path $destination) { Remove-Item $destination -Recurse -Force } }
catch { Write-Host "Windows still has a Viso file open. Restart Windows, then run this uninstaller again to remove $destination." }
Write-Host 'Viso face sign-in removed. The desktop app and its enrollment are retained.' -ForegroundColor Green
