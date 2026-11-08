#Requires -RunAsAdministrator
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'signin-common.ps1')
$destination = Join-Path $env:ProgramFiles 'Viso'
$data = Join-Path $env:ProgramData 'Viso\Accounts'
$clsid = '{4965C343-8550-499A-A734-512863668D12}'
$providerKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$clsid"
$classKey = "HKLM:\SOFTWARE\Classes\CLSID\$clsid"
if (-not [Environment]::Is64BitProcess) { throw 'Run this installer in 64-bit PowerShell.' }
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { throw 'This Credential Provider build requires x64 Windows, rather than Windows on ARM.' }
if (Get-Service VisoSignIn -ErrorAction SilentlyContinue) { throw 'Uninstall the existing sign-in components and restart Windows before installing this build.' }
if ((Test-Path $providerKey) -or (Test-Path $classKey)) { throw 'Remove the existing Viso registration using uninstall-signin.ps1 first.' }
foreach ($file in 'signin\bin\VisoCredentialProvider.dll','signin\bin\VisoSignInService.exe','.venv\Scripts\python.exe','models\manifest.json') {
    if (-not (Test-Path (Join-Path $root $file))) { throw "Missing $file. Run setup.ps1 and build-signin.ps1 first." }
}
Assert-VisoNoReparse $destination
Assert-VisoNoReparse $data
if (Test-Path $destination) { throw "Remove the previous installation using uninstall-signin.ps1 before reusing $destination." }
$dataRoot = Split-Path $data
if (Test-Path $dataRoot) { Assert-VisoTree $dataRoot $false }
$serviceCreated = $destinationCreated = $false
try {
    New-VisoProtectedDirectory $destination $true
    $destinationCreated = $true
    if (-not (Test-Path $dataRoot)) { New-VisoProtectedDirectory $dataRoot $false }
    if (-not (Test-Path $data)) { New-VisoProtectedDirectory $data $false }
    Assert-VisoTree $dataRoot $false
    Copy-Item "$root\signin\bin\VisoCredentialProvider.dll", "$root\signin\bin\VisoSignInService.exe" $destination
    # A private runtime avoids executing a per-user Python installation as SYSTEM.
    Copy-VisoRuntime $root $destination -ProtectedPayload
    Assert-VisoTree $destination $true
    # Service first; publish the tile only after it is running.
    New-Service -Name VisoSignIn -BinaryPathName "`"$destination\VisoSignInService.exe`"" -DisplayName 'Viso Windows face sign-in' -StartupType Automatic -Description 'Service-owned camera verification for the Viso Credential Provider.' | Out-Null
    $serviceCreated = $true
    Start-Service VisoSignIn
    (Get-Service VisoSignIn).WaitForStatus('Running', [TimeSpan]::FromSeconds(15))
    New-Item "$classKey\InprocServer32" -Force | Out-Null
    Set-Item "$classKey\InprocServer32" "$destination\VisoCredentialProvider.dll"
    New-ItemProperty "$classKey\InprocServer32" -Name ThreadingModel -Value Apartment -PropertyType String -Force | Out-Null
    New-Item $providerKey -Force | Out-Null
    Set-Item $providerKey 'Viso Face'
    Write-Host 'Installed. Open Viso > Settings > Windows face sign-in and link your current Windows account.' -ForegroundColor Green
    Write-Host 'Then lock Windows and choose Sign-in options > Viso Face. Other Windows sign-in providers stay available.'
} catch {
    Remove-Item $providerKey, $classKey -Recurse -Force -ErrorAction SilentlyContinue
    if ($serviceCreated) {
        Stop-Service VisoSignIn -Force -ErrorAction SilentlyContinue
        & sc.exe delete VisoSignIn | Out-Null
    }
    if ($destinationCreated -and (Test-Path $destination)) { Remove-Item $destination -Recurse -Force -ErrorAction SilentlyContinue }
    throw
}
