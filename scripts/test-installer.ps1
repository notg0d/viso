param([string]$Payload)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$requestedPayload = if ($Payload) { [IO.Path]::GetFullPath($Payload) } else { $Payload }
. (Join-Path $root 'installer\deploy.ps1')
$Payload = $requestedPayload
$writeJournal = ${function:Save-VisoTransaction}
$checks = 0
function Check([bool]$condition, [string]$message) { if (-not $condition) { throw $message }; $script:checks++ }
function Reject([scriptblock]$action, [string]$message) {
    $rejected = $false
    try { & $action | Out-Null } catch { $rejected = $true }
    Check $rejected $message
}
$temporary = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp\opencode') ('Viso installer ' + [char]0x674e + ' ' + [Guid]::NewGuid().ToString('N'))
$registry = 'HKCU:\Software\VisoInstallerTests-' + [Guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $temporary | Out-Null
function Write-Manifest([string]$folder, [object[]]$entries = @()) {
    if (-not $entries.Count) {
        $entries = @(foreach ($file in Get-ChildItem -LiteralPath $folder -File -Recurse | Where-Object { $_.Name -ne 'payload.json' }) {
            @{ path = $file.FullName.Substring($folder.Length + 1).Replace('\','/'); sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
        })
    }
    @{ format = 1; version = 'test'; files = $entries } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $folder 'installer\payload.json') -Encoding UTF8
    return (Get-FileHash -LiteralPath (Join-Path $folder 'installer\payload.json') -Algorithm SHA256).Hash
}
try {
    $sample = Join-Path $temporary 'sample payload'
    foreach ($relative in 'Viso.exe','Viso.exe.config','VisoSignInService.exe','VisoCredentialProvider.dll','runtime/python.exe','backend/run_native.py','models/manifest.json','installer/deploy.ps1','installer/signin-common.ps1','RELEASE.json') {
        $path = Join-Path $sample $relative
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        [IO.File]::WriteAllText($path, 'synthetic installer fixture')
    }
    $hash = Write-Manifest $sample
    Check ((Get-VisoPayloadManifest $sample $hash).files.Count -eq 10) 'Valid synthetic payload was rejected.'
    Reject { Get-VisoPayloadManifest $sample ('0' * 64) } 'An unpinned manifest was accepted.'
    Reject { Get-VisoPayloadManifest $sample 'invalid' } 'A malformed manifest digest was accepted.'
    $entries = (Get-Content (Join-Path $sample 'installer\payload.json') -Raw | ConvertFrom-Json).files
    $badHash = Write-Manifest $sample @($entries + $entries[0])
    Reject { Get-VisoPayloadManifest $sample $badHash } 'Duplicate manifest paths were accepted.'
    foreach ($unsafe in '../outside.exe', '/absolute.exe', 'C:/outside.exe', 'runtime/python.exe:stream', 'runtime\python.exe', 'runtime//python.exe', './Viso.exe') {
        $badHash = Write-Manifest $sample @(@{ path = $unsafe; sha256 = ('0' * 64) })
        Reject { Get-VisoPayloadManifest $sample $badHash } ('Unsafe manifest path accepted: ' + $unsafe)
    }
    $hash = Write-Manifest $sample
    [IO.File]::WriteAllText((Join-Path $sample 'extra.txt'), 'unrecorded')
    Reject { Get-VisoPayloadManifest $sample $hash } 'Unrecorded payload files were accepted.'
    Remove-Item (Join-Path $sample 'extra.txt')
    foreach ($private in '.viso/profile.dpapi', 'tests/sample.txt', '__pycache__/cached.pyc') {
        $path = Join-Path $sample $private
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        [IO.File]::WriteAllText($path, 'synthetic excluded data')
        Reject { Get-VisoPayloadManifest $sample $hash } 'Private/development data was accepted.'
        Remove-Item -LiteralPath (Split-Path $path -Parent) -Recurse -Force
    }
    # Use the trusted development interpreter to build a synthetic cache. The
    # read-only manifest audit must never try to execute sample runtime/python.exe.
    $python = Join-Path $root '.venv\Scripts\python.exe'
    $fixture = @'
import importlib.util, json, marshal, pathlib, sys
root = pathlib.Path(sys.argv[1])
source = root / 'runtime' / 'Lib' / 'cache_fixture.py'
source.parent.mkdir(parents=True, exist_ok=True)
source.write_text('def fixture():\n    return 42\n', encoding='utf-8')
cache = pathlib.Path(importlib.util.cache_from_source(str(source)))
cache.parent.mkdir()
cache.write_bytes(importlib.util.MAGIC_NUMBER + (3).to_bytes(4, 'little') + importlib.util.source_hash(source.read_bytes()) + marshal.dumps(compile(source.read_bytes(), 'runtime/Lib/cache_fixture.py', 'exec')))
(root / 'runtime' / 'packages.json').write_text(json.dumps({'python': sys.version.split()[0], 'bytecode': {'cache_tag': sys.implementation.cache_tag, 'magic': importlib.util.MAGIC_NUMBER.hex(), 'invalidation': 'checked-hash'}}))
print(cache.name)
'@
    $cacheFile = & $python -I -B -c $fixture $sample
    Check ($LASTEXITCODE -eq 0) 'Could not create synthetic checked-hash bytecode.'
    $cacheFile = Join-Path (Join-Path $sample 'runtime\Lib\__pycache__') ([string]$cacheFile)
    $validCache = [IO.File]::ReadAllBytes($cacheFile)
    $hash = Write-Manifest $sample
    Check ((Get-VisoPayloadManifest $sample $hash).files.Count -eq 13) 'Valid manifest-covered runtime bytecode was rejected.'
    & $python -I -B -c (Get-VisoBytecodeCheck) $sample
    Check ($LASTEXITCODE -eq 0) 'Synthetic bytecode source hashes or relative filenames failed.'
    foreach ($flags in 0, 1, 2, 7) {
        $badCache = [byte[]]$validCache.Clone(); $badCache[4] = $flags
        [IO.File]::WriteAllBytes($cacheFile, $badCache)
        $badHash = Write-Manifest $sample
        Reject { Get-VisoPayloadManifest $sample $badHash } 'Non-checked-hash bytecode was accepted, despite a repinned manifest.'
    }
    $badCache = [byte[]]$validCache.Clone(); $badCache[0] = $badCache[0] -bxor 1
    [IO.File]::WriteAllBytes($cacheFile, $badCache)
    $badHash = Write-Manifest $sample
    Reject { Get-VisoPayloadManifest $sample $badHash } 'Bytecode for a different interpreter was accepted.'
    [IO.File]::WriteAllBytes($cacheFile, [byte[]]$validCache[0..15])
    $badHash = Write-Manifest $sample
    Reject { Get-VisoPayloadManifest $sample $badHash } 'Truncated bytecode was accepted.'
    [IO.File]::WriteAllBytes($cacheFile, $validCache)
    $sourceFile = Join-Path $sample 'runtime\Lib\cache_fixture.py'
    Move-Item $sourceFile ($sourceFile + '.saved')
    $badHash = Write-Manifest $sample
    Reject { Get-VisoPayloadManifest $sample $badHash } 'Sourceless bytecode was accepted.'
    Move-Item ($sourceFile + '.saved') $sourceFile
    foreach ($excluded in 'backend/viso/__pycache__/dev.cpython-314.pyc', 'runtime/Lib/orphan.pyc', 'runtime/Lib/__pycache__/cache_fixture.cpython-000.pyc', 'runtime/Lib/__pycache__/cache_fixture.cpython-314.opt-1.pyc', 'runtime/Lib/__pycache__/orphan.cpython-314.pyc') {
        $path = Join-Path $sample $excluded
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        [IO.File]::WriteAllBytes($path, $validCache)
        $badHash = Write-Manifest $sample
        Reject { Get-VisoPayloadManifest $sample $badHash } ('Unexpected cache was accepted: ' + $excluded)
        Remove-Item -LiteralPath $path
        if ($excluded.StartsWith('backend/')) { Remove-Item -LiteralPath (Split-Path $path -Parent) }
    }
    # The protected-runtime check also verifies source hashes and nested code
    # filenames, which cannot be inferred from a file's SHA-256 alone.
    $rejectCheck = @'
import sys
try:
    exec(sys.argv[2])
except (AssertionError, ValueError, FileNotFoundError):
    sys.exit(1)
'@
    $badCache = [byte[]]$validCache.Clone(); $badCache[8] = $badCache[8] -bxor 1
    [IO.File]::WriteAllBytes($cacheFile, $badCache)
    & $python -I -B -c $rejectCheck $sample (Get-VisoBytecodeCheck)
    Check ($LASTEXITCODE -ne 0) 'A wrong bytecode source hash was accepted.'
    [IO.File]::WriteAllBytes($cacheFile, $validCache)
    $badFilename = @'
import marshal, pathlib, sys
cache = pathlib.Path(sys.argv[1])
data = cache.read_bytes()
code = marshal.loads(data[16:])
nested = next(value for value in code.co_consts if hasattr(value, 'co_filename'))
code = code.replace(co_consts=tuple(nested.replace(co_filename='C:/developer/private/path.py') if value is nested else value for value in code.co_consts))
cache.write_bytes(data[:16] + marshal.dumps(code))
'@
    & $python -I -B -c $badFilename $cacheFile
    Check ($LASTEXITCODE -eq 0) 'Could not create synthetic non-relocatable bytecode.'
    & $python -I -B -c $rejectCheck $sample (Get-VisoBytecodeCheck)
    Check ($LASTEXITCODE -ne 0) 'A private absolute code filename was accepted.'
    [IO.File]::WriteAllBytes($cacheFile, $validCache)
    $hash = Write-Manifest $sample
    [IO.File]::WriteAllBytes($cacheFile, $badCache)
    Reject { Get-VisoPayloadManifest $sample $hash } 'Modified bytecode bypassed manifest checksums.'
    [IO.File]::WriteAllBytes($cacheFile, $validCache)
    $target = New-Item -ItemType Directory -Path (Join-Path $temporary 'junction target')
    $junction = Join-Path $sample 'junction'
    New-Item -ItemType Junction -Path $junction -Target $target.FullName | Out-Null
    Reject { Get-VisoPayloadManifest $sample $hash } 'A payload reparse point was accepted.'
    [IO.Directory]::Delete($junction)
    Reject { Assert-VisoTransaction $temporary $false } 'An arbitrary transaction path was accepted.'
    $handle = [IO.File]::Open((Join-Path $sample 'Viso.exe'), 'Open', 'Read', 'None')
    try { Reject { Assert-VisoFilesUnlocked $sample } 'A locked old payload was accepted.' } finally { $handle.Dispose() }
    Assert-VisoFilesUnlocked $sample
    $checks++
    $journalFolder = New-Item -ItemType Directory -Path (Join-Path $temporary 'journal writer')
    & {
        # Exercise real flush/rename/replace with ACL calls scoped to mocks;
        # no administrator privileges or actual protected data are needed.
        function Get-Acl {
            $acl = New-Object PSObject
            $acl | Add-Member ScriptMethod SetOwner { param($owner) }
            return $acl
        }
        function Set-Acl {}
        & $writeJournal @{ revision = 1 } $journalFolder.FullName
        & $writeJournal @{ revision = 2 } $journalFolder.FullName
        $read = Get-Content (Join-Path $journalFolder.FullName 'transaction.json') -Raw | ConvertFrom-Json
        Check ($read.revision -eq 2 -and -not (Test-Path (Join-Path $journalFolder.FullName 'transaction.json.new'))) 'Atomic recovery-journal replacement failed.'
    }

    # Exercise the real directory-swap/journal/rollback/remove code using only
    # synthetic folders, a private HKCU sandbox and mocked SCM/runtime calls.
    # No real Viso service, Program Files tree, account data or camera is touched.
    $VisoDestination = Join-Path $temporary 'installed'
    $VisoData = Join-Path $temporary 'private data'
    $VisoProviderKey = $registry + '\provider'
    $VisoClassKey = $registry + '\class'
    $script:fakeService = $null
    $script:starts = 0; $script:stops = 0; $script:runtimeCalls = 0; $script:failStarts = 0; $script:failRuntime = $false
    function Assert-VisoTransaction([string]$path, [bool]$existing) {
        if (-not $path.StartsWith($temporary + '\') -or $existing -ne (Test-Path -LiteralPath $path)) { throw 'Unsafe synthetic transaction.' }
    }
    function Assert-NoPendingVisoRemoval {}
    function Assert-VisoTree([string]$path, [bool]$readable) { Assert-VisoNoReparse $path }
    function Set-VisoPayloadOwner([string]$path) {}
    function New-VisoProtectedDirectory([string]$path, [bool]$readable) { New-Item -ItemType Directory -Path $path | Out-Null }
    function Save-VisoTransaction($state, [string]$folder) { $state | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $folder 'transaction.json') -Encoding UTF8 }
    $script:accountHash = 'a' * 64
    $script:relinkDuringRuntime = $false; $script:relinkAfterStart = $false
    function Get-VisoAccountFingerprint { return @{ count = 1; hash = $script:accountHash } }
    function Get-VisoService { return $script:fakeService }
    function Stop-VisoService { $script:stops++; if ($script:fakeService) { $script:fakeService.State = 'Stopped' } }
    function Delete-VisoService { $script:fakeService = $null }
    function New-Service { $script:fakeService = @{ State = 'Stopped'; StartMode = 'Auto' } }
    function Set-Service([string]$Name, [string]$StartupType) { $script:fakeService.StartMode = switch ($StartupType) { 'Automatic' { 'Auto' } 'Disabled' { 'Disabled' } default { 'Manual' } } }
    function Start-Service {
        $script:starts++
        if ($script:failStarts -gt 0) { $script:failStarts--; throw 'Synthetic service start failure.' }
        $script:fakeService.State = 'Running'
        if ($script:relinkAfterStart) { $script:accountHash = 'c' * 64 }
    }
    function Get-Service {
        $service = New-Object PSObject
        $service | Add-Member ScriptMethod WaitForStatus { param($status, $timeout) }
        $service | Add-Member ScriptMethod Dispose {}
        return $service
    }
    function Test-VisoRuntime([string]$folder) {
        $script:runtimeCalls++
        if ($script:relinkDuringRuntime) { $script:accountHash = 'b' * 64 }
        if ($script:failRuntime) { throw 'Synthetic model check failure.' }
    }

    $transaction = Join-Path $temporary 'transaction'
    Install-VisoPayload $sample $hash $transaction
    Check ((Test-Path $VisoDestination) -and $fakeService.State -eq 'Running') 'Fresh simulated installation did not become ready.'
    Check ((Get-Item "$VisoClassKey\InprocServer32").GetValue('') -eq (Join-Path $VisoDestination 'VisoCredentialProvider.dll')) 'Provider path was not fixed to the installation.'
    Check ((Get-Content (Join-Path $transaction 'transaction.json') -Raw | ConvertFrom-Json).verified) 'Verified transaction was not journaled.'
    Complete-VisoInstallation $transaction
    Check (-not (Test-Path $transaction)) 'Committed backup/journal was not removed.'
    $oldHash = (Get-FileHash (Join-Path $VisoDestination 'Viso.exe')).Hash
    [IO.File]::WriteAllText((Join-Path $sample 'Viso.exe'), 'updated synthetic executable')
    $hash = Write-Manifest $sample
    Install-VisoPayload $sample $hash $transaction
    Check ((Get-FileHash (Join-Path $VisoDestination 'Viso.exe')).Hash -ne $oldHash) 'Simulated update did not replace payload.'
    Check ((Get-FileHash (Join-Path $transaction 'previous\Viso.exe')).Hash -eq $oldHash) 'Update did not retain previous payload for recovery.'
    $journal = Get-Content (Join-Path $transaction 'transaction.json') -Raw
    '{}' | Set-Content (Join-Path $transaction 'transaction.json')
    Reject { Restore-VisoInstallation $transaction } 'A damaged recovery journal was accepted.'
    Check ((Test-Path $VisoDestination) -and $fakeService.State -eq 'Running') 'Damaged-journal recovery changed the installation/service.'
    $journal | Set-Content (Join-Path $transaction 'transaction.json') -Encoding UTF8
    $savedBackup = Join-Path $temporary 'saved backup'
    Move-Item (Join-Path $transaction 'previous') $savedBackup
    Reject { Restore-VisoInstallation $transaction } 'Recovery accepted a missing previous-payload backup.'
    Check ((Test-Path $VisoDestination) -and $fakeService.State -eq 'Running') 'Missing-backup recovery discarded the current installation.'
    Move-Item $savedBackup (Join-Path $transaction 'previous')
    Restore-VisoInstallation $transaction
    Check ((Get-FileHash (Join-Path $VisoDestination 'Viso.exe')).Hash -eq $oldHash) 'Canceled update did not restore the old payload.'
    Check ($fakeService.State -eq 'Running') 'Recovery did not restore the old running service.'

    $script:failRuntime = $true
    $stopCount = $stops
    Reject { Install-VisoPayload $sample $hash $transaction } 'Model check failure did not abort update.'
    Check ($stops -eq $stopCount -and $fakeService.State -eq 'Running') 'Model checks stopped the old service before validation.'
    Check ((Get-FileHash (Join-Path $VisoDestination 'Viso.exe')).Hash -eq $oldHash -and -not (Test-Path $transaction)) 'Failed preflight altered the old payload.'
    $script:failRuntime = $false
    $script:failStarts = 1
    Reject { Install-VisoPayload $sample $hash $transaction } 'Service startup failure did not abort update.'
    Check ((Get-FileHash (Join-Path $VisoDestination 'Viso.exe')).Hash -eq $oldHash -and $fakeService.State -eq 'Running') 'Service failure did not restore previous payload/service.'
    $handle = [IO.File]::Open((Join-Path $VisoDestination 'Viso.exe'), 'Open', 'Read', 'None')
    try { Reject { Install-VisoPayload $sample $hash $transaction } 'An in-use installation was replaced.' } finally { $handle.Dispose() }
    Check ($fakeService.State -eq 'Running' -and -not (Test-Path $transaction)) 'Locked-file abort did not restore service and clean its stage.'
    $script:relinkDuringRuntime = $true; $script:relinkAfterStart = $true
    Install-VisoPayload $sample $hash $transaction
    $state = Read-VisoTransaction $transaction
    Check ($state.accounts.hash -eq ('b' * 64) -and $accountHash -eq ('c' * 64)) 'Account snapshot was not frozen after staging/before new service startup.'
    Restore-VisoInstallation $transaction
    Check ($accountHash -eq ('c' * 64) -and $fakeService.State -eq 'Running') 'Cancellation rejected or overwrote an authenticated post-start relink.'
    Install-VisoPayload $sample $hash $transaction
    Complete-VisoInstallation $transaction
    Check (-not (Test-Path $transaction) -and $accountHash -eq ('c' * 64)) 'Backup cleanup rejected or overwrote a legitimate relink.'
    $script:relinkDuringRuntime = $false; $script:relinkAfterStart = $false
    New-Item -ItemType Directory -Path (Join-Path $VisoData 'Accounts') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $VisoData 'Accounts\synthetic.dpapi'), 'not a real credential')
    Check (-not (Remove-VisoInstallation $true)) 'Unlocked uninstall incorrectly required restart.'
    Check ((Test-Path (Join-Path $VisoData 'Accounts\synthetic.dpapi')) -and -not (Test-Path $VisoProviderKey) -and $null -eq $fakeService) 'Keep-link removal lost a record or retained sign-in registration.'
    Remove-Item $VisoDestination
    $script:failStarts = 1
    Reject { Install-VisoPayload $sample $hash $transaction } 'Fresh service startup failure did not abort installation.'
    Check (-not (Test-Path $VisoDestination) -and -not (Test-Path $transaction) -and $null -eq $fakeService -and -not (Test-Path $VisoProviderKey)) 'Failed fresh install left its payload/service/tile behind.'
    Install-VisoPayload $sample $hash $transaction
    Complete-VisoInstallation $transaction
    Remove-VisoInstallation $false | Out-Null
    Check (-not (Test-Path (Join-Path $VisoData 'Accounts'))) 'Default uninstall did not remove synthetic account records.'
    Remove-Item $VisoDestination
    Install-VisoPayload $sample $hash $transaction
    Complete-VisoInstallation $transaction
    $script:scheduled = @()
    function Schedule-VisoRemoval([string]$path) {
        if (-not $path.StartsWith($VisoDestination)) { throw 'A non-Viso synthetic path was scheduled.' }
        $script:scheduled += $path
        return $true
    }
    $lockedFile = Join-Path $VisoDestination 'VisoCredentialProvider.dll'
    $handle = [IO.File]::Open($lockedFile, 'Open', 'Read', 'None')
    try { Check (Remove-VisoInstallation $true) 'Locked-file uninstall did not request a manual restart.' } finally { $handle.Dispose() }
    Check ($scheduled -contains $lockedFile -and $scheduled -contains $VisoDestination -and $null -eq $fakeService -and -not (Test-Path $VisoProviderKey)) 'Locked-file uninstall did not schedule only its remaining payload after disabling Viso.'

    if ($Payload) {
        $manifest = Join-Path ([IO.Path]::GetFullPath($Payload)) 'installer\payload.json'
        $manifestHash = (Get-FileHash $manifest -Algorithm SHA256).Hash
        $verified = Get-VisoPayloadManifest $Payload $manifestHash
        Check ($verified.files.Count -gt 1000) 'Full bundled runtime was not present.'
        & (Join-Path $root '.venv\Scripts\python.exe') -I -B (Join-Path $PSScriptRoot 'check-docs.py') $Payload
        Check ($LASTEXITCODE -eq 0) 'Bundled installer documentation has broken local links/assets.'
        & (Join-Path $root 'signin\bin\ServiceTests.exe') --runtime $Payload
        if ($LASTEXITCODE -ne 0) { throw 'Installer runtime checks failed.' }
    }
    Write-Host "Installer checks passed: $checks payload safety, lock handling, simulated installation/upgrade/recovery/removal checks."
} finally {
    if (Test-Path $registry) { Remove-Item $registry -Recurse -Force }
    if (Test-Path $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
exit 0
