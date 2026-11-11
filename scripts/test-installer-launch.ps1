param([Parameter(Mandatory=$true)][string]$Compiler)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not [Environment]::Is64BitOperatingSystem) { throw 'The launch regression requires x64 Windows.' }
if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) { throw 'Supply the existing Inno Setup compiler; no tools are downloaded.' }
$setup = Get-Content -LiteralPath (Join-Path $root 'installer\Viso.iss') -Raw
if ($setup -notmatch '#include "native-powershell\.iss"' -or $setup -notmatch 'Result := ExecNativePowerShell\(Parameters, ExitCode\)' -or $setup -match 'Result := Exec\(') { throw 'Setup/uninstall actions do not use the shared production launcher.' }
$temporary = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp\opencode') ('Viso launch ' + [char]0x674e + ' ' + [Guid]::NewGuid().ToString('N'))
$checks = 1
$passed = $false
function Check([bool]$condition, [string]$message) { if (-not $condition) { throw $message }; $script:checks++ }
function Read-Receipt([string]$path) {
    $receipt = @{}
    foreach ($line in Get-Content -LiteralPath $path) {
        if ($line -match '^([^=]+)=(.*)$') { $receipt[$Matches[1]] = $Matches[2] }
    }
    return $receipt
}
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    # Files are deliberately non-executable placeholders. Only the real helper's
    # non-mutating ValidatePayload action is called; no runtime is started.
    $payload = Join-Path $temporary 'synthetic payload'
    $entries = @(foreach ($relative in 'Viso.exe','Viso.exe.config','VisoSignInService.exe','VisoCredentialProvider.dll','runtime/python.exe','backend/run_native.py','models/manifest.json','installer/deploy.ps1','installer/signin-common.ps1','RELEASE.json') {
        $file = Join-Path $payload $relative
        New-Item -ItemType Directory -Path (Split-Path $file -Parent) -Force | Out-Null
        [IO.File]::WriteAllText($file, 'non-executable launch regression fixture')
        @{ path = $relative; sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
    $manifest = Join-Path $payload 'installer\payload.json'
    @{ format = 1; files = $entries } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifest -Encoding UTF8
    $manifestHash = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash
    $poison = Join-Path $temporary 'untrusted modules'
    $poisonModule = Join-Path $poison 'Microsoft.PowerShell.Utility'
    New-Item -ItemType Directory -Path $poisonModule -Force | Out-Null
    $sentinel = Join-Path $temporary 'untrusted-module-loaded.txt'
    $escapedSentinel = $sentinel.Replace("'", "''")
    @"
[IO.File]::WriteAllText('$escapedSentinel', 'An untrusted inherited module was executed.')
function Get-FileHash { throw 'Untrusted Get-FileHash was loaded.' }
Export-ModuleMember -Function Get-FileHash
"@ | Set-Content -LiteralPath (Join-Path $poisonModule 'Microsoft.PowerShell.Utility.psm1') -Encoding UTF8
    $probeSource = Join-Path $temporary 'probe.iss'
    @'
#define SourcePascal StringChange(SourceRoot, "'", "''")
#define ProbePascal StringChange(ProbeRoot, "'", "''")
#define PayloadPascal StringChange(PayloadRoot, "'", "''")
[Setup]
AppName=Viso native PowerShell launch probe
AppVersion=0.0.0
DefaultDirName={tmp}\not-installed
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
#if Ver >= 0x07000000
SetupArchitecture={#ProbeArchitecture}
#endif
CreateAppDir=no
Uninstallable=no
OutputDir={#ProbeRoot}
OutputBaseFilename=launch-probe-{#ProbeArchitecture}
SetupLogging=yes
RedirectionGuard=yes
[Code]
#include SourceRoot + "\installer\native-powershell.iss"
function Quoted(const Value: String): String;
begin
  Result := '"' + Value + '"';
end;
function InitializeSetup: Boolean;
var
  Parameters, ProbeReceipt, NativeReceipt, LegacyReceipt, ProtectedReceipt: String;
  Launched: Boolean;
  ExitCode: Integer;
begin
  ProbeReceipt := '{#ProbePascal}\probe-{#ProbeArchitecture}.ini';
  NativeReceipt := '{#ProbePascal}\native-{#ProbeArchitecture}.ini';
  LegacyReceipt := '{#ProbePascal}\legacy-{#ProbeArchitecture}.ini';
  ProtectedReceipt := '{#ProbePascal}\protected-{#ProbeArchitecture}.ini';
  SetIniString('Probe', 'CompilerMajor', '{#Ver >> 24}', ProbeReceipt);
  Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' +
    Quoted('{#SourcePascal}\installer\deploy.ps1') + ' -Action ValidatePayload' +
    ' -Payload ' + Quoted('{#PayloadPascal}') + ' -ExpectedManifestHash {#ManifestHash}';
  ExitCode := -1;
  Launched := ExecNativePowerShell(Parameters + ' -ResultFile ' + Quoted(NativeReceipt), ExitCode);
  if Launched then SetIniString('Probe', 'NativeLaunched', '1', ProbeReceipt);
  SetIniString('Probe', 'NativeExit', IntToStr(ExitCode), ProbeReceipt);
#if Ver >= 0x07000000 && ProbeArchitecture == "x86"
  // Negative control: the exact superseded launcher must fail the bitness gate.
  ExitCode := -1;
  Launched := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parameters + ' -ResultFile ' + Quoted(LegacyReceipt), '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Launched then SetIniString('Probe', 'LegacyLaunched', '1', ProbeReceipt);
  SetIniString('Probe', 'LegacyExit', IntToStr(ExitCode), ProbeReceipt);
#endif
  if not IsAdmin then begin
    // Invalid temporary transaction is defense in depth if elevation detection
    // disagrees: Commit rejects it before accessing any protected installation.
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' +
      Quoted('{#SourcePascal}\installer\deploy.ps1') + ' -Action Commit -Transaction ' +
      Quoted('{#ProbePascal}\not-a-protected-transaction') + ' -ResultFile ' + Quoted(ProtectedReceipt);
    ExitCode := -1;
    Launched := ExecNativePowerShell(Parameters, ExitCode);
    if Launched then SetIniString('Probe', 'ProtectedLaunched', '1', ProbeReceipt);
    SetIniString('Probe', 'ProtectedExit', IntToStr(ExitCode), ProbeReceipt);
  end;
  Result := False; // Always exit before installation or wizard creation.
end;
'@ | Set-Content -LiteralPath $probeSource -Encoding UTF8
    $architectures = @('x86')
    for ($index = 0; $index -lt $architectures.Count; $index++) {
        $architecture = $architectures[$index]
        & $Compiler /Q ("/DSourceRoot=$root") ("/DProbeRoot=$temporary") ("/DPayloadRoot=$payload") ("/DManifestHash=$manifestHash") ("/DProbeArchitecture=$architecture") $probeSource
        Check ($LASTEXITCODE -eq 0) 'Inno launch-probe compilation failed.'
        $log = Join-Path $temporary "setup-$architecture.log"
        $previousModulePath = $env:PSModulePath
        try {
            $env:PSModulePath = $poison + ';' + $previousModulePath
            $process = Start-Process -FilePath (Join-Path $temporary "launch-probe-$architecture.exe") -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + $log + '"') -PassThru
        } finally { $env:PSModulePath = $previousModulePath }
        try {
            if (-not $process.WaitForExit(60000)) { throw "Non-installing Inno probe timed out; inspect $temporary before retrying." }
            Check ($process.ExitCode -eq 1) 'Launch probe did not intentionally cancel before installation.'
        } finally { $process.Dispose() }
        $probe = Read-Receipt (Join-Path $temporary "probe-$architecture.ini")
        $native = Read-Receipt (Join-Path $temporary "native-$architecture.ini")
        Check ($probe.NativeLaunched -eq '1' -and $probe.NativeExit -eq '0') ("The production launcher failed: exit=$($probe.NativeExit), native64=$($native.Native64), message=$($native.Message)")
        Check ($native.Success -eq '1' -and $native.Native64 -eq '1') 'Actual Inno-to-helper verification was not native x64.'
        Check (-not (Test-Path -LiteralPath $sentinel)) 'The helper executed a user-writable inherited module.'
        if (Test-Path -LiteralPath (Join-Path $temporary "protected-$architecture.ini")) {
            $protected = Read-Receipt (Join-Path $temporary "protected-$architecture.ini")
            Check ($probe.ProtectedLaunched -eq '1' -and $probe.ProtectedExit -eq '1' -and $protected.Native64 -eq '1' -and $protected.Success -eq '0' -and $protected.Message -eq 'Viso Setup requires Windows administrator approval.') 'The native launcher bypassed administrator requirements.'
        } else { Write-Warning 'The probe is running elevated; the non-admin rejection case was skipped.' }
        $logText = Get-Content -LiteralPath $log -Raw
        Check ($logText -match '64-bit install mode: Yes') 'Probe did not use the production 64-bit install mode.'
        Check ($logText -notmatch 'Installation process starting') 'Probe entered the installation lifecycle.'
        if ([int]$probe.CompilerMajor -ge 7) {
            Check ($logText.Contains("($($architecture.Replace('x86','32').Replace('x64','64'))-bit)")) 'Probe did not exercise the requested Inno engine bitness.'
            if ($architecture -eq 'x86') {
                $legacy = Read-Receipt (Join-Path $temporary 'legacy-x86.ini')
                Check ($probe.LegacyLaunched -eq '1' -and $probe.LegacyExit -eq '1' -and $legacy.Success -eq '0' -and $legacy.Native64 -eq '0' -and $legacy.Message -like 'Use 64-bit PowerShell.*') 'The original redirected Inno 7 Exec defect was not reproduced.'
                $architectures += 'x64'
            }
        }
        Write-Host "Actual Inno $($probe.CompilerMajor) $architecture launch probe passed; native helper bitness verified without installation."
    }
    Write-Host "Installer launch checks passed: $checks. No service/provider, account, runtime or camera operations were performed."
    $passed = $true
} finally {
    # The fresh probe directory is the only cleanup target, never Program Files.
    if ($passed) { Remove-Item -LiteralPath $temporary -Recurse -Force }
    else { Write-Warning "Failed probe artifacts retained for diagnosis: $temporary" }
}
