param([string]$Compiler, [string]$OutputDirectory, [switch]$AllowDirty)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'signin-common.ps1')
$commit = (& git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'A Git checkout is required for installer provenance.' }
$changes = @(& git -C $root status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Could not check source status.' }
if ($changes.Count -and -not $AllowDirty) { throw 'Commit validated sources before building a publishable installer. -AllowDirty is for local drafts only.' }
if (-not $Compiler) { $Compiler = $env:INNOSETUP_COMPILER }
if (-not $Compiler) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $Compiler = $command.Source }
}
if (-not $Compiler) {
    foreach ($candidate in @("$env:ProgramFiles\Inno Setup 7\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe")) {
        if (Test-Path -LiteralPath $candidate) { $Compiler = $candidate; break }
    }
}
if (-not $Compiler -or -not (Test-Path -LiteralPath $Compiler -PathType Leaf)) { throw 'Install Inno Setup 6.7+ or 7, then supply -Compiler PATH or INNOSETUP_COMPILER. This script never downloads build tools.' }
$Compiler = [IO.Path]::GetFullPath($Compiler)
$source = Get-Content -LiteralPath (Join-Path $root 'desktop\Viso\Program.cs') -Raw
if ($source -notmatch 'AssemblyVersion\("(\d+\.\d+\.\d+)\.\d+"\)') { throw 'Cannot read the desktop version.' }
$version = $Matches[1]
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root 'desktop\releases' }
$bundle = Join-Path $output "Viso-$version-installer-payload"
$installer = Join-Path $output "Viso-$version-Setup-x64.exe"
foreach ($path in $bundle, $installer, ($installer + '.sha256'), ($installer + '.json')) {
    if (Test-Path -LiteralPath $path) { throw 'Installer output already exists. Use a fresh -OutputDirectory; prior artifacts are never overwritten.' }
}
New-Item -ItemType Directory -Path $bundle -Force | Out-Null
& (Join-Path $PSScriptRoot 'build-native.ps1') -OutputDirectory $bundle
& (Join-Path $PSScriptRoot 'build-signin.ps1')
Copy-VisoRuntime $root $bundle
Copy-Item "$root\signin\bin\VisoCredentialProvider.dll", "$root\signin\bin\VisoSignInService.exe" $bundle
New-Item -ItemType Directory -Path (Join-Path $bundle 'installer') | Out-Null
Copy-Item (Join-Path $root 'installer\deploy.ps1') (Join-Path $bundle 'installer\deploy.ps1')
Copy-Item (Join-Path $PSScriptRoot 'signin-common.ps1') (Join-Path $bundle 'installer\signin-common.ps1')
# Bundle only versioned public docs; ignored personal reports must stay local.
$documentation = @(& git -C $root ls-files -- docs)
if ($LASTEXITCODE -ne 0) { throw 'Could not list public installer documentation.' }
foreach ($relative in $documentation) {
    Assert-VisoNoReparse (Join-Path $root $relative)
    $destination = Join-Path $bundle $relative
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root $relative) -Destination $destination
}
& "$root\.venv\Scripts\python.exe" -I -B (Join-Path $PSScriptRoot 'package-installer-docs.py') $root $bundle $commit
if ($LASTEXITCODE -ne 0) { throw 'Installer documentation packaging failed.' }
$runtime = Get-Content -LiteralPath (Join-Path $bundle 'runtime\packages.json') -Raw | ConvertFrom-Json
$release = [ordered]@{
    version = $version; source_commit = $commit; source_dirty = [bool]$changes.Count
    built_utc = [DateTime]::UtcNow.ToString('o'); platform = 'windows-x64'; minimum_dotnet_framework = '4.8'
    python = $runtime.python; dependencies = $runtime.dependencies; windows_signin_installer_included = $true
    desktop_state_directory = '%LOCALAPPDATA%\Viso'; credential_provider = '{4965C343-8550-499A-A734-512863668D12}'
    service = 'VisoSignIn'; installer_compiler_sha256 = (Get-FileHash -LiteralPath $Compiler -Algorithm SHA256).Hash.ToLowerInvariant()
}
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $bundle 'RELEASE.json'), ($release | ConvertTo-Json -Depth 5) + "`n", $utf8)
[IO.File]::WriteAllText((Join-Path $bundle 'README.txt'), @"
Viso $version - complete experimental Windows x64 installation

Run Viso-$version-Setup-x64.exe normally and approve the Windows administrator
prompt. Setup includes the native desktop, private Python/dependencies, pinned
models/notices, Windows sign-in service and Credential Provider. End users do not
need Python, Visual Studio, Inno Setup, a .NET SDK or a first-run model download.
Windows 10/11 x64 and .NET Framework 4.8 are required; Windows on ARM is unsupported.

Keep working ordinary Windows password/PIN sign-in available. Face/blink checks
are experimental, not Windows Hello certified or proven replay-resistant.

Open Viso from the Start menu as your ordinary signed-in user. Enroll your face,
then explicitly link your current Windows account in Settings using its password,
not its Windows Hello PIN. Setup never enrolls or links an account for you.

Upgrades retain protected account links and %LOCALAPPDATA%\Viso enrollment/settings.
Source/portable .viso folders are not moved or removed. To migrate one on this PC,
close both apps and copy only your own profile.dpapi and desktop.json into
%LOCALAPPDATA%\Viso as that Windows user. Do not overwrite an existing enrollment.

Uninstall through Windows Installed apps. It disables Viso sign-in and asks whether
to keep encrypted account links for a reinstall. Desktop enrollment stays private
in %LOCALAPPDATA%\Viso; deleting that folder is a separate user decision.
If Windows holds old files open, restart manually and retry. Setup never kills
LogonUI or silently restarts Windows. See docs\installer.md for recovery/validation.

This build is unsigned. Verify the separately supplied installer .sha256 first.
No enrollment, password, account record, test fixture or developer environment is
included. Upstream notices/licenses are retained; no project-wide Viso license is
currently declared. Provided without warranty. Provenance is in RELEASE.json.
"@, $utf8)
$entries = @(foreach ($file in Get-ChildItem -LiteralPath $bundle -File -Recurse -Force | Sort-Object FullName) {
    [ordered]@{ path = $file.FullName.Substring($bundle.Length + 1).Replace('\','/'); sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
})
$manifest = [ordered]@{ format = 1; version = $version; files = $entries }
$manifestPath = Join-Path $bundle 'installer\payload.json'
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 5) + "`n", $utf8)
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
# The build shell can itself be 32-bit; verify through the same native x64
# Windows PowerShell required by Setup rather than weakening the helper gate.
$systemDirectory = if ([Environment]::Is64BitProcess) { 'System32' } else { 'Sysnative' }
$powerShell = Join-Path $env:WINDIR "$systemDirectory\WindowsPowerShell\v1.0\powershell.exe"
& $powerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root 'installer\deploy.ps1') -Action ValidatePayload -Payload $bundle -ExpectedManifestHash $manifestHash
if ($LASTEXITCODE -ne 0) { throw 'Installer payload validation failed.' }
if (-not $AllowDirty) {
    if ((& git -C $root rev-parse HEAD).Trim() -ne $commit -or @(& git -C $root status --porcelain).Count) { throw 'Sources changed while building. Rebuild from committed sources.' }
}
& $Compiler /Q ("/DPayloadRoot=$bundle") ("/DVisoVersion=$version") ("/DOutputRoot=$output") (Join-Path $root 'installer\Viso.iss')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installer)) { throw 'Inno Setup installer compilation failed.' }
if (-not $AllowDirty) {
    if ((& git -C $root rev-parse HEAD).Trim() -ne $commit -or @(& git -C $root status --porcelain).Count) { throw 'Sources changed during installer compilation. Rebuild from committed sources.' }
}
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($installer + '.sha256'), "$hash  $([IO.Path]::GetFileName($installer))`n", $utf8)
$release['installer_sha256'] = $hash
$release['payload_manifest_sha256'] = $manifestHash
[IO.File]::WriteAllText(($installer + '.json'), ($release | ConvertTo-Json -Depth 5) + "`n", $utf8)
Write-Host "Complete installer: $installer" -ForegroundColor Green
Write-Host "SHA-256: $hash"
if ($changes.Count) { Write-Warning 'LOCAL DRAFT from dirty sources. Do not publish this installer.' }
