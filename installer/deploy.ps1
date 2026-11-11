[CmdletBinding()]
param(
    [ValidateSet('Install','Commit','Rollback','CheckUninstall','Uninstall','ValidatePayload')][string]$Action,
    [string]$Payload,
    [string]$ExpectedManifestHash,
    [string]$Transaction,
    [string]$ResultFile,
    [switch]$KeepAccountLinks
)
$ErrorActionPreference = 'Stop'
if ($MyInvocation.InvocationName -ne '.') {
    # Setup may inherit incompatible PowerShell 7 or user-writable module paths.
    # Load only this Windows PowerShell's built-in modules in the helper process;
    # never change the caller's environment when dot-sourced for validation.
    $env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
}
$common = Join-Path $PSScriptRoot 'signin-common.ps1'
if (-not (Test-Path -LiteralPath $common)) { $common = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts\signin-common.ps1' }
. $common
$VisoDestination = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Viso'
$VisoData = Join-Path $env:ProgramData 'Viso'
$VisoClsid = '{4965C343-8550-499A-A734-512863668D12}'
$VisoProviderKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$VisoClsid"
$VisoClassKey = "HKLM:\SOFTWARE\Classes\CLSID\$VisoClsid"

function Get-VisoPayloadManifest([string]$folder, [string]$expectedHash) {
    if ($expectedHash -notmatch '^[0-9a-fA-F]{64}$') { throw 'A pinned payload manifest hash is required.' }
    $folder = [IO.Path]::GetFullPath($folder).TrimEnd('\')
    Assert-VisoNoReparse $folder
    $items = @(Get-ChildItem -LiteralPath $folder -Recurse -Force)
    foreach ($item in $items) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are not allowed in the installer payload.' }
        $relative = $item.FullName.Substring($folder.Length + 1).Replace('\','/')
        if ($relative -match '(^|/)(\.viso|\.venv|\.git|__pycache__|tests?|test-results|node_modules|experiments)(/|$)' -or $relative -match '\.(dpapi|pyc|pyo|partial|log)$') { throw 'Private or development data was found in the installer payload.' }
    }
    $manifestFile = Join-Path $folder 'installer\payload.json'
    if ((Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Installer payload manifest does not match the compiled installer.' }
    $manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
    if ($manifest.format -ne 1 -or -not $manifest.files.Count) { throw 'Unsupported or empty installer payload manifest.' }
    $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $manifest.files) {
        $relative = [string]$entry.path
        if (-not $relative -or $relative -match '[:\\]' -or [IO.Path]::IsPathRooted($relative) -or @($relative.Split('/') | Where-Object { $_ -in @('','.', '..') }).Count -or -not $seen.Add($relative)) { throw 'Unsafe or duplicate path in the installer payload manifest.' }
        $file = [IO.Path]::GetFullPath((Join-Path $folder $relative))
        if (-not $file.StartsWith($folder + '\', [StringComparison]::OrdinalIgnoreCase) -or $relative -eq 'installer/payload.json' -or $entry.sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid payload manifest entry.' }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.sha256) { throw 'Installer payload checksum mismatch.' }
    }
    if (@($items | Where-Object { -not $_.PSIsContainer }).Count -ne $seen.Count + 1) { throw 'Unexpected or missing files in the installer payload.' }
    foreach ($required in 'Viso.exe','Viso.exe.config','VisoSignInService.exe','VisoCredentialProvider.dll','runtime/python.exe','backend/run_native.py','models/manifest.json','installer/deploy.ps1','installer/signin-common.ps1','RELEASE.json') {
        if (-not $seen.Contains($required)) { throw 'A required desktop, runtime, model or sign-in component is missing.' }
    }
    return $manifest
}

function Assert-VisoTransaction([string]$path, [bool]$existing) {
    $path = [IO.Path]::GetFullPath($path).TrimEnd('\')
    $parent = [Environment]::GetFolderPath('ProgramFiles')
    if ((Split-Path $path -Parent) -ne $parent -or (Split-Path $path -Leaf) -notmatch '^Viso\.setup-[A-Za-z0-9._-]+$') { throw 'Unsafe installer transaction location.' }
    Assert-VisoNoReparse $path
    if ($existing) {
        Assert-VisoAcl (Get-Acl -LiteralPath $path) $false
        Assert-VisoTree $path $true
        Assert-VisoAcl (Get-Acl -LiteralPath (Join-Path $path 'transaction.json')) $false
    }
    elseif (Test-Path -LiteralPath $path) { throw 'An installer transaction already exists. Finish or recover it before retrying.' }
}

function Get-VisoAccountFingerprint {
    $accounts = Join-Path $VisoData 'Accounts'
    $lines = @()
    if (Test-Path -LiteralPath $VisoData) { Assert-VisoTree $VisoData $false }
    if (Test-Path -LiteralPath $accounts) {
        foreach ($file in Get-ChildItem -LiteralPath $accounts -File -Filter '*.dpapi' | Sort-Object Name) {
            $lines += $file.Name + ':' + (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        }
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($lines -join "`n")))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
    # Persist only an aggregate digest/count, never account names, SIDs or records.
    return @{ count = $lines.Count; hash = $digest }
}

function Assert-VisoRetainedAccounts($before) {
    $after = Get-VisoAccountFingerprint
    if ($after.count -ne $before.count -or $after.hash -ne $before.hash) { throw 'Retained encrypted account links changed unexpectedly.' }
}

function Get-VisoService {
    $service = Get-CimInstance Win32_Service -Filter "Name='VisoSignIn'"
    if ($service -and ($service.StartName -ne 'LocalSystem' -or $service.PathName.Trim('"') -ne (Join-Path $VisoDestination 'VisoSignInService.exe'))) { throw 'An unexpected VisoSignIn service cannot be adopted by this installer.' }
    return $service
}

function Stop-VisoService {
    $service = Get-Service VisoSignIn -ErrorAction SilentlyContinue
    if ($service) {
        try {
            if ($service.Status -ne 'Stopped') { Stop-Service -InputObject $service -ErrorAction Stop }
            $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
        } finally { $service.Dispose() }
    }
}

function Delete-VisoService {
    & "$env:WINDIR\System32\sc.exe" delete VisoSignIn | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Windows could not remove the VisoSignIn service.' }
}

function Assert-NoPendingVisoRemoval {
    $session = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
    foreach ($entry in @($session.PendingFileRenameOperations) + @($session.PendingFileRenameOperations2)) {
        if ($entry -and $entry -match ([Regex]::Escape($VisoDestination) + '(\\|$)')) { throw 'Viso file removal/replacement is pending. Restart Windows before running Setup again.' }
    }
}

function Assert-VisoDesktopClosed {
    foreach ($process in Get-CimInstance Win32_Process -Filter "Name='Viso.exe'") {
        if ($process.ExecutablePath -eq (Join-Path $VisoDestination 'Viso.exe')) { throw 'Close the installed Viso desktop in every Windows session, then retry Setup.' }
    }
}

function Assert-VisoFilesUnlocked([string]$folder) {
    foreach ($file in Get-ChildItem -LiteralPath $folder -File -Recurse -Force) {
        try { $handle = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None); $handle.Dispose() }
        catch { throw 'Windows still has a Viso file open. Restart Windows, then run Setup again. No files have been replaced.' }
    }
}

function Save-VisoTransaction($state, [string]$folder) {
    $file = Join-Path $folder 'transaction.json'
    $pending = $file + '.new'
    Assert-VisoNoReparse $pending
    $bytes = [Text.Encoding]::UTF8.GetBytes(($state | ConvertTo-Json -Depth 5))
    $stream = [IO.File]::Open($pending, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    $acl = Get-Acl -LiteralPath $pending
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier 'S-1-5-32-544'))
    Set-Acl -LiteralPath $pending -AclObject $acl
    # A crash must not truncate the last usable recovery journal.
    if (Test-Path -LiteralPath $file) { [IO.File]::Replace($pending, $file, [NullString]::Value) }
    else { [IO.File]::Move($pending, $file) }
}

function Read-VisoTransaction([string]$folder) {
    $state = Get-Content -LiteralPath (Join-Path $folder 'transaction.json') -Raw | ConvertFrom-Json
    if ($state.format -ne 1) { throw 'Unsupported or damaged installer recovery journal. No installation files were changed.' }
    foreach ($name in 'hadOld','hadService','wasRunning','hadProvider','hadClass','accountsFrozen','serviceActivated','swapped','verified') {
        if ($state.$name -isnot [bool]) { throw 'Incomplete installer recovery journal. No installation files were changed.' }
    }
    if ($state.oldStartMode -notin @('', 'Auto', 'Manual', 'Disabled') -or
        ($state.hadService -and $state.oldStartMode -eq '') -or
        [string]$state.accounts.count -notmatch '^\d+$' -or $state.accounts.hash -notmatch '^[0-9a-f]{64}$') {
        throw 'Invalid installer recovery journal. No installation files were changed.'
    }
    return $state
}

function Restore-VisoInstallation([string]$folder) {
    Assert-VisoTransaction $folder $true
    $state = Read-VisoTransaction $folder
    $previous = Join-Path $folder 'previous'
    if ($state.hadOld -and $state.swapped -and -not (Test-Path -LiteralPath $previous)) {
        throw 'The previous payload backup is missing. Recovery cannot discard the current installation.'
    }
    if ($state.swapped -or (Test-Path -LiteralPath $previous) -or (-not $state.hadOld -and (Test-Path -LiteralPath $VisoDestination) -and -not (Test-Path -LiteralPath (Join-Path $folder 'payload')))) {
        Get-VisoService | Out-Null
        Stop-VisoService
        if (-not $state.hadProvider) { Remove-Item -LiteralPath $VisoProviderKey -Recurse -Force -ErrorAction SilentlyContinue }
        if (-not $state.hadClass) { Remove-Item -LiteralPath $VisoClassKey -Recurse -Force -ErrorAction SilentlyContinue }
        if (-not $state.hadService -and (Get-VisoService)) {
            Delete-VisoService
        }
        if (Test-Path -LiteralPath $VisoDestination) {
            Assert-VisoTree $VisoDestination $true
            Remove-Item -LiteralPath $VisoDestination -Recurse -Force
        }
        if (Test-Path -LiteralPath $previous) { Move-Item -LiteralPath $previous -Destination $VisoDestination }
    }
    if ($state.accountsFrozen -and -not $state.serviceActivated) { Assert-VisoRetainedAccounts $state.accounts }
    else { Get-VisoAccountFingerprint | Out-Null }
    if ($state.hadService) {
        $startup = switch ($state.oldStartMode) { 'Auto' { 'Automatic' } 'Disabled' { 'Disabled' } default { 'Manual' } }
        Set-Service VisoSignIn -StartupType $startup
        if ($state.wasRunning) { Start-Service VisoSignIn }
    }
    Remove-Item -LiteralPath $folder -Recurse -Force
}

function Install-VisoPayload([string]$source, [string]$manifestHash, [string]$folder) {
    Assert-VisoTransaction $folder $false
    Assert-NoPendingVisoRemoval
    if (@(Get-ChildItem -LiteralPath ([Environment]::GetFolderPath('ProgramFiles')) -Directory -Filter 'Viso.setup-*').Count) { throw 'An unfinished Viso Setup transaction exists. Follow the recovery guide before retrying.' }
    Assert-VisoNoReparse $VisoDestination
    if (Test-Path -LiteralPath $VisoDestination) { Assert-VisoTree $VisoDestination $true }
    Assert-VisoDesktopClosed
    $oldService = Get-VisoService
    $hadOld = Test-Path -LiteralPath $VisoDestination
    if (-not $hadOld -and ($oldService -or (Test-Path $VisoProviderKey) -or (Test-Path $VisoClassKey))) { throw 'A partial old installation exists. Recover or remove it before retrying Setup.' }
    if ((Test-Path $VisoProviderKey) -ne (Test-Path $VisoClassKey) -or ((Test-Path $VisoClassKey) -and -not (Test-Path "$VisoClassKey\InprocServer32"))) { throw 'A partial Viso registration exists. Recover it before retrying Setup.' }
    if ((Test-Path $VisoProviderKey) -and (Get-Item $VisoProviderKey).GetValue('') -ne 'Viso Face') { throw 'An unexpected Viso provider registration cannot be adopted.' }
    if (Test-Path "$VisoClassKey\InprocServer32") {
        $key = Get-Item "$VisoClassKey\InprocServer32"
        if ($key.GetValue('') -ne (Join-Path $VisoDestination 'VisoCredentialProvider.dll') -or $key.GetValue('ThreadingModel') -ne 'Apartment') { throw 'An unexpected Viso COM registration cannot be adopted.' }
    }
    $state = [ordered]@{
        format = 1; hadOld = $hadOld; hadService = [bool]$oldService; wasRunning = ($oldService -and $oldService.State -eq 'Running')
        oldStartMode = $(if ($oldService) { $oldService.StartMode } else { '' })
        hadProvider = (Test-Path $VisoProviderKey); hadClass = (Test-Path $VisoClassKey)
        accounts = (Get-VisoAccountFingerprint); accountsFrozen = $false; serviceActivated = $false; swapped = $false; verified = $false
    }
    New-VisoProtectedDirectory $folder $false
    Save-VisoTransaction $state $folder
    try {
        $stage = Join-Path $folder 'payload'
        New-VisoProtectedDirectory $stage $true
        Copy-VisoTree $source $stage
        Set-VisoPayloadOwner $stage
        Assert-VisoTree $stage $true
        Get-VisoPayloadManifest $stage $manifestHash | Out-Null
        # Never execute Python from the user-writable download/extraction folder.
        Test-VisoRuntime $stage
        Assert-VisoDesktopClosed
        Stop-VisoService
        # Account linking can legitimately finish while the new payload is
        # staging. Freeze the retained snapshot only after SCM stop completes.
        $state.accounts = Get-VisoAccountFingerprint
        $state.accountsFrozen = $true
        Save-VisoTransaction $state $folder
        if ($hadOld) {
            Assert-VisoFilesUnlocked $VisoDestination
            Move-Item -LiteralPath $VisoDestination -Destination (Join-Path $folder 'previous')
        }
        Move-Item -LiteralPath $stage -Destination $VisoDestination
        $state.swapped = $true
        Save-VisoTransaction $state $folder
        if (-not (Test-Path -LiteralPath $VisoData)) { New-VisoProtectedDirectory $VisoData $false }
        $accounts = Join-Path $VisoData 'Accounts'
        if (-not (Test-Path -LiteralPath $accounts)) { New-VisoProtectedDirectory $accounts $false }
        Assert-VisoTree $VisoData $false
        Assert-VisoTree $VisoDestination $true
        if ($oldService) { Set-Service VisoSignIn -StartupType Automatic }
        else { New-Service -Name VisoSignIn -BinaryPathName ('"' + (Join-Path $VisoDestination 'VisoSignInService.exe') + '"') -DisplayName 'Viso Windows face sign-in' -StartupType Automatic -Description 'Service-owned camera verification for the Viso Credential Provider.' | Out-Null }
        Assert-VisoRetainedAccounts $state.accounts
        # From this point authenticated relinks may occur. Neither cancellation
        # nor backup cleanup may reject or overwrite those intentional changes.
        $state.serviceActivated = $true
        Save-VisoTransaction $state $folder
        Start-Service VisoSignIn
        $running = Get-Service VisoSignIn
        try { $running.WaitForStatus('Running', [TimeSpan]::FromSeconds(20)) } finally { $running.Dispose() }
        # Publish only Viso's tile after the protected runtime and service are ready.
        New-Item "$VisoClassKey\InprocServer32" -Force | Out-Null
        Set-Item "$VisoClassKey\InprocServer32" (Join-Path $VisoDestination 'VisoCredentialProvider.dll')
        New-ItemProperty "$VisoClassKey\InprocServer32" -Name ThreadingModel -Value Apartment -PropertyType String -Force | Out-Null
        New-Item $VisoProviderKey -Force | Out-Null
        Set-Item $VisoProviderKey 'Viso Face'
        $service = Get-VisoService
        if ($service.State -ne 'Running' -or $service.StartMode -ne 'Auto') { throw 'Windows sign-in service did not become ready.' }
        $state.verified = $true
        Save-VisoTransaction $state $folder
    } catch {
        $failure = $_.Exception.Message
        try { Restore-VisoInstallation $folder }
        catch { throw 'Installation failed and automatic recovery did not complete. Use ordinary Windows password/PIN sign-in; restart and rerun Setup or consult the recovery guide.' }
        throw $failure
    }
}

function Complete-VisoInstallation([string]$folder) {
    Assert-VisoTransaction $folder $true
    $state = Read-VisoTransaction $folder
    if (-not $state.verified -or -not $state.swapped) { throw 'An unverified installer transaction cannot be committed.' }
    # Once the service is running, authenticated users may intentionally relink.
    # Backup cleanup must not reject or undo those legitimate account changes.
    Get-VisoAccountFingerprint | Out-Null
    Remove-Item -LiteralPath $folder -Recurse -Force
}

function Assert-VisoRemovalReady {
    Assert-VisoTree $VisoDestination $true
    if (Test-Path -LiteralPath $VisoData) { Assert-VisoTree $VisoData $false }
    Assert-VisoDesktopClosed
    Get-VisoService | Out-Null
}

function Schedule-VisoRemoval([string]$path) {
    # Windows PowerShell converts ordinary $null string arguments to "".
    # MoveFileEx requires an actual null destination to schedule deletion.
    return [Viso.InstallerRemoval]::MoveFileEx($path, [NullString]::Value, 4)
}

function Remove-VisoInstallation([bool]$keepLinks) {
    Assert-VisoRemovalReady
    Stop-VisoService
    Remove-Item -LiteralPath $VisoProviderKey, $VisoClassKey -Recurse -Force -ErrorAction SilentlyContinue
    if (Get-VisoService) {
        Delete-VisoService
    }
    if (-not $keepLinks -and (Test-Path -LiteralPath (Join-Path $VisoData 'Accounts'))) { Remove-Item -LiteralPath (Join-Path $VisoData 'Accounts') -Recurse -Force }
    if (-not ('Viso.InstallerRemoval' -as [type])) {
        Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
namespace Viso { public static class InstallerRemoval {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool MoveFileEx(string source, string destination, uint flags);
} }
'@
    }
    $restart = $false
    # Remove only payload-owned files; Inno removes its own uninstaller separately.
    $files = @(Get-ChildItem -LiteralPath $VisoDestination -File -Recurse -Force | Where-Object { $_.DirectoryName -ne $VisoDestination -or $_.Name -notmatch '^unins\d+\.(exe|dat|msg)$' })
    foreach ($file in $files) {
        try { Remove-Item -LiteralPath $file.FullName -Force }
        catch {
            if (-not (Schedule-VisoRemoval $file.FullName)) { throw 'A locked Viso file could not be scheduled for removal. Restart and retry uninstall.' }
            $restart = $true
        }
    }
    foreach ($directory in Get-ChildItem -LiteralPath $VisoDestination -Directory -Recurse -Force | Sort-Object { $_.FullName.Length } -Descending) {
        try { [IO.Directory]::Delete($directory.FullName) }
        catch {
            if (-not (Schedule-VisoRemoval $directory.FullName)) { throw 'A Viso directory could not be scheduled for removal.' }
            $restart = $true
        }
    }
    if ($restart -and -not (Schedule-VisoRemoval $VisoDestination)) { throw 'The remaining Viso directory could not be scheduled for removal.' }
    return $restart
}

# Dot-sourcing exposes pure validation helpers, never an installation action.
if ($MyInvocation.InvocationName -ne '.') {
    $success = $false; $restart = $false; $message = ''; $exitCode = 1
    try {
        # Integrity-only verification must exercise the launcher's bitness too,
        # but remains non-mutating and does not require elevation.
        if (-not [Environment]::Is64BitProcess) { throw 'Use 64-bit PowerShell. If running Viso Setup, use the corrected x64 installer.' }
        if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { throw 'Viso sign-in requires x64 Windows, not Windows on ARM.' }
        if ($Action -ne 'ValidatePayload') {
            $principal = New-Object Security.Principal.WindowsPrincipal ([Security.Principal.WindowsIdentity]::GetCurrent())
            if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Viso Setup requires Windows administrator approval.' }
            if ($Action -eq 'Install') {
                $framework = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release
                if ($framework.Release -lt 528040) { throw 'Install .NET Framework 4.8 before running Viso Setup.' }
            }
        }
        switch ($Action) {
            'ValidatePayload' { Get-VisoPayloadManifest $Payload $ExpectedManifestHash | Out-Null }
            'Install' { Install-VisoPayload $Payload $ExpectedManifestHash $Transaction }
            'Commit' { Complete-VisoInstallation $Transaction }
            'Rollback' { Restore-VisoInstallation $Transaction }
            'CheckUninstall' { Assert-VisoRemovalReady }
            'Uninstall' { $restart = Remove-VisoInstallation $KeepAccountLinks.IsPresent }
            default { throw 'An explicit installer action is required.' }
        }
        $success = $true; $exitCode = 0; $message = 'Viso operation verified.'
    } catch {
        $message = $_.Exception.Message
        $restart = $message -like '*Restart Windows*'
        Write-Error $message -ErrorAction Continue
    } finally {
        if ($ResultFile) {
            Assert-VisoNoReparse $ResultFile
            $message = $message.Replace("`r",' ').Replace("`n",' ')
            "[Result]`r`nSuccess=$([int]$success)`r`nNative64=$([int][Environment]::Is64BitProcess)`r`nRestartRequired=$([int]$restart)`r`nMessage=$message`r`n" | Set-Content -LiteralPath $ResultFile -Encoding Unicode
        }
    }
    exit $exitCode
}
