param([Parameter(Mandatory=$true)][string]$Bundle)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitProcess) { throw 'Use 64-bit PowerShell.' }
$assembly = [Reflection.Assembly]::LoadFrom((Join-Path $Bundle 'Viso.exe'))
if ($assembly.GetType('Viso.RenderingChecks', $false)) { throw 'Installer executable contains rendering-test helpers.' }
$paths = $assembly.GetType('Viso.AppPaths', $true)
$method = $paths.GetMethod('DataDirectory')
$installed = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Viso'
$expected = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Viso'
foreach ($root in $installed, ($installed.ToUpperInvariant() + '\')) {
    if ($method.Invoke($null, [object[]]@([string]$root)) -ne $expected) { throw 'Installed desktop does not use current-user LocalAppData storage.' }
}
if ($method.Invoke($null, [object[]]@($Bundle)) -ne (Join-Path $Bundle '.viso')) { throw 'Portable/source storage changed unexpectedly.' }
$temporary = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp\opencode') ('Viso state ' + [char]0x674e + ' ' + [Guid]::NewGuid().ToString('N'))
$client = $null
try {
    $clientType = $assembly.GetType('Viso.EngineClient', $true)
    $client = $clientType.GetConstructor([type[]]@([string], [bool], [string])).Invoke([object[]]@([string]$Bundle, $true, [string]$temporary))
    $ready = $clientType.GetMethod('WaitForModels').Invoke($client, $null)
    if (-not $ready.Wait(45000)) { throw 'Installer client model readiness timed out.' }
    $status = $clientType.GetMethod('Send').Invoke($client, [object[]]@('status', $null))
    if (-not $status.Wait(15000) -or -not $status.Result['engine']['ready'] -or $null -ne $status.Result['profile']) { throw 'Installer client status is incorrect.' }
    if (Test-Path $temporary) { throw 'Memory-only initialization created persistent storage.' }
    $process = $clientType.GetField('process', [Reflection.BindingFlags]'Instance,NonPublic').GetValue($client)
    if (-not $process.StartInfo.Arguments.Contains('--data-dir "' + $temporary + '"')) { throw 'Desktop worker did not receive the intended storage directory.' }
    $client.Dispose(); $client = $null
    $client = $clientType.GetConstructor([type[]]@([string], [bool], [string])).Invoke([object[]]@([string]$Bundle, $false, [string]$temporary))
    $ready = $clientType.GetMethod('WaitForModels').Invoke($client, $null)
    if (-not $ready.Wait(45000)) { throw 'Persistent installer client model readiness timed out.' }
    $fixture = Join-Path (Split-Path $PSScriptRoot -Parent) 'tests\.fixtures\obama.jpg'
    $image = 'data:image/jpeg;base64,' + [Convert]::ToBase64String([IO.File]::ReadAllBytes($fixture))
    $data = @{ name = 'Installer synthetic profile'; images = [string[]]@($image) }
    $json = $assembly.GetType('Viso.Json', $true)
    $encoded = $data | ConvertTo-Json -Compress
    $request = $json.GetMethod('Decode').Invoke($null, [object[]]@([string]$encoded))
    $saved = $clientType.GetMethod('Send').Invoke($client, [object[]]@('image.enroll', $request))
    if (-not $saved.Wait(30000) -or -not (Test-Path (Join-Path $temporary 'profile.dpapi'))) { throw 'Synthetic enrollment did not persist in the explicit user-state folder.' }
    if (Test-Path (Join-Path $Bundle '.viso\profile.dpapi')) { throw 'Installer storage validation wrote enrollment into the program payload.' }
    $deleted = $clientType.GetMethod('Send').Invoke($client, [object[]]@('profile.delete', $null))
    if (-not $deleted.Wait(15000) -or (Test-Path (Join-Path $temporary 'profile.dpapi'))) { throw 'Synthetic state-folder enrollment deletion failed.' }
    Write-Host 'Installed/portable path selection, explicit spaces/Unicode state-directory IPC and model-ready camera-off startup passed.'
    Write-Host 'Synthetic current-user DPAPI enrollment/save/delete used the explicit state directory without writing to the program payload.'
} finally {
    if ($client) { $client.Dispose() }
    if (Test-Path $temporary) { Remove-Item $temporary -Recurse -Force }
}
