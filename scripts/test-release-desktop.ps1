param([Parameter(Mandatory=$true)][string]$Bundle)
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFrom((Join-Path $Bundle 'Viso.exe'))
if ($assembly.GetType('Viso.RenderingChecks', $false)) { throw 'Production executable contains rendering-test helpers.' }
$clientType = $assembly.GetType('Viso.EngineClient', $true)
$client = $clientType.GetConstructor([type[]]@([string], [bool])).Invoke([object[]]@($Bundle, $true))
try {
    $models = $clientType.GetMethod('WaitForModels').Invoke($client, $null)
    if (-not $models.Wait(45000)) { throw 'Production client model initialization timed out.' }
    $status = $clientType.GetMethod('Send').Invoke($client, [object[]]@('status', $null))
    if (-not $status.Wait(45000) -or -not $status.Result['engine']['ready']) { throw 'Production EngineClient did not become ready.' }
    if ($null -ne $status.Result['profile']) { throw 'Release must start without enrollment.' }
} finally { $client.Dispose() }
Write-Output 'Production executable excludes test helpers; actual EngineClient/private runtime initialization passed.'

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
foreach ($mode in @('--ephemeral', 'persistent')) {
$start = @{ FilePath = (Join-Path $Bundle 'Viso.exe'); WorkingDirectory = $env:WINDIR; PassThru = $true }
if ($mode -eq '--ephemeral') { $start.ArgumentList = $mode }
$process = Start-Process @start
try {
    if (-not $process.WaitForInputIdle(30000)) { throw 'WPF desktop did not become idle.' }
    $deadline = [DateTime]::UtcNow.AddSeconds(40)
    $ready = $false
    while (-not $ready -and [DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
        $process.Refresh()
        if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
            $window = [Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
            $readyText = 'On-device ' + [char]0x00B7 + ' ready'
            $condition = New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::NameProperty, $readyText)
            $ready = $null -ne $window.FindFirst([Windows.Automation.TreeScope]::Descendants, $condition)
        }
        if (-not $ready) { Start-Sleep -Milliseconds 100 }
    }
    if (-not $ready) { throw 'Extracted WPF UI never showed its model-ready state.' }
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($process.Id)")
    if ($children.Count -ne 1 -or $children[0].ExecutablePath -ne (Join-Path $Bundle 'runtime\python.exe')) { throw 'Desktop did not launch exactly one private Python worker.' }
    if (-not $process.CloseMainWindow() -or -not $process.WaitForExit(10000) -or $process.ExitCode -ne 0) { throw 'Desktop did not close cleanly.' }
    foreach ($child in $children) {
        if (Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue) { throw 'Desktop left its Python worker running.' }
    }
    if (Test-Path (Join-Path $Bundle '.viso\profile.dpapi')) { throw 'Ephemeral validation persisted an enrollment.' }
    Write-Output "Extracted WPF $mode startup (spaces/Unicode path, unrelated CWD), visible model-ready state and graceful child cleanup passed."
} finally {
    if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
    $process.Dispose()
}
}
