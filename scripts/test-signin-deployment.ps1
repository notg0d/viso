$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'signin-common.ps1')
$checks = 0
function Check-Acl([string]$sddl, [bool]$readable, [bool]$accepted) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetSecurityDescriptorSddlForm($sddl)
    $passed = $true
    try { Assert-VisoAcl $acl $readable } catch { $passed = $false }
    if ($passed -ne $accepted) { throw "Unexpected trust result for $sddl" }
    $script:checks++
}
Check-Acl 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' $false $true
Check-Acl 'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' $false $true
Check-Acl 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;BU)' $true $true
Check-Acl 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;BU)' $false $false
Check-Acl 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FW;;;BU)' $true $false
Check-Acl 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;WD;;;AU)' $true $false
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
Check-Acl "O:${sid}G:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)" $false $false
$temporary = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp\opencode') ('Viso-deployment-test-' + [Guid]::NewGuid().ToString('N'))
New-Item $temporary -ItemType Directory -Force | Out-Null
try {
    Initialize-VisoDeployment
    $atomic = Join-Path $temporary 'atomic'
    [Viso.Deployment]::Create($atomic, "O:${sid}G:${sid}D:P(A;OICI;FA;;;${sid})")
    if (-not (Get-Acl $atomic).AreAccessRulesProtected) { throw 'New directory DACL was not protected.' }
    $rejected = $false
    try { [Viso.Deployment]::Create($atomic, "O:${sid}G:${sid}D:P(A;OICI;FA;;;${sid})") } catch { $rejected = $true }
    if (-not $rejected) { throw 'Atomic directory creation accepted an existing directory.' }
    $checks += 2
    $target = New-Item (Join-Path $temporary 'target') -ItemType Directory
    $junction = Join-Path $temporary 'junction'
    New-Item $junction -ItemType Junction -Target $target.FullName | Out-Null
    Assert-VisoNoReparse $target.FullName
    $rejected = $false
    try { Assert-VisoNoReparse (Join-Path $junction 'Accounts') } catch { $rejected = $true }
    if (-not $rejected) { throw 'Reparse-point traversal was not rejected.' }
    $checks += 2
    # Remove the junction itself, without recursively traversing its target.
    [IO.Directory]::Delete($junction)
} finally { Remove-Item $temporary -Recurse -Force }
Write-Host "Deployment checks passed: $checks ownership, ACL and reparse-point checks."
