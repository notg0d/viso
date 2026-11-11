param([string]$OutputDirectory, [switch]$AllowDirty)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'signin-common.ps1') # Helpers only; no installation/registration.

$commit = & git -C $root rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'A Git checkout is required to record release provenance.' }
$changes = & git -C $root status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Could not check release source status.' }
if ($changes -and -not $AllowDirty) { throw 'Commit the validated release sources first. -AllowDirty is for local drafts only.' }
$source = Get-Content (Join-Path $root 'desktop\Viso\Program.cs') -Raw
if ($source -notmatch 'AssemblyVersion\("(\d+\.\d+\.\d+)\.\d+"\)') { throw 'Cannot read the desktop version.' }
$version = $Matches[1]
$name = "Viso-$version-windows-x64"
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root 'desktop\releases' }
$bundle = Join-Path $output $name
$archive = Join-Path $output ($name + '.zip')
if ((Test-Path $bundle) -or (Test-Path $archive) -or (Test-Path ($archive + '.sha256'))) {
    throw 'Release output already exists. Choose a fresh -OutputDirectory; existing artifacts are never overwritten.'
}
New-Item $bundle -ItemType Directory -Force | Out-Null
& (Join-Path $PSScriptRoot 'build-native.ps1') -OutputDirectory $bundle
Copy-VisoRuntime $root $bundle

$runtime = Get-Content (Join-Path $bundle 'runtime\packages.json') -Raw | ConvertFrom-Json
$release = [ordered]@{
    version = $version
    source_commit = $commit.Trim()
    source_dirty = [bool]$changes
    built_utc = [DateTime]::UtcNow.ToString('o')
    platform = 'windows-x64'
    minimum_dotnet_framework = '4.8'
    python = $runtime.python
    dependencies = $runtime.dependencies
    windows_signin_installer_included = $false
}
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $bundle 'RELEASE.json'), ($release | ConvertTo-Json -Depth 4) + "`n", $utf8)
$readme = @"
Viso $version - Windows x64 desktop (experimental)

1. Extract the ENTIRE ZIP to a folder owned by your Windows user.
2. Open Viso.exe. Keep backend, models, runtime and Viso.exe.config beside it.

Requires 64-bit Windows 10/11 and .NET Framework 4.8. Python and the pinned
recognition models are included. No Python, Node.js, .NET SDK, administrator
installation or first-run model download is required. A webcam is optional
for the Image lab and required for live enrollment. Allow desktop camera
access in Windows Settings. The ZIP is not a single-file executable.

The executable is unsigned: Windows SmartScreen may warn. Verify the ZIP's
SHA-256 against the separately published .sha256 file before running it.

For memory-only enrollment, open PowerShell in this folder and run:
    .\Viso.exe --ephemeral
Normal launch saves a current-user/machine DPAPI-encrypted profile in
.viso\profile.dpapi beside the app. Preferences use .viso\desktop.json.
No enrollment, account password, or developer data is included in this ZIP.
Enrollment data is not cloud-synced. Camera frames are processed in memory.
Keep .viso private; deleting the app folder also deletes its local profile.
For an update, close Viso, extract to a new folder, and copy only your own
.viso folder if you want to retain local enrollment/preferences on this PC.

Launching Viso does not install or alter Windows sign-in. The Unlock test is
a simulator. No Credential Provider, Windows service, or privileged installer
is included. Settings can explicitly link to an already installed Viso service;
do not select Link / update account unless you intend to change that link.
RGB face/blink checks are experimental, not Windows Hello certified or proven
replay-resistant. Keep your normal Windows password/PIN available.

Guides: https://github.com/notg0d/viso/blob/v$version/docs/getting-started.md
Security: https://github.com/notg0d/viso/blob/v$version/docs/security.md
Sign-in (separate source installation):
    https://github.com/notg0d/viso/blob/v$version/docs/windows-signin.md

Upstream notices: THIRD_PARTY_NOTICES.md, models\licenses,
runtime\LICENSE.txt, and runtime\Lib\site-packages\*.dist-info license files.
Runtime versions: RELEASE.json and runtime\packages.json.
SHA256SUMS.txt covers every payload file except itself.
No project-wide Viso license is declared; upstream licenses are not a license
grant for all Viso code. This experimental build is provided without warranty.
"@
[IO.File]::WriteAllText((Join-Path $bundle 'README.txt'), $readme + "`n", $utf8)

# A final payload audit catches accidental development files or personal state.
$files = @(Get-ChildItem -LiteralPath $bundle -File -Recurse -Force)
foreach ($file in $files) {
    $relative = $file.FullName.Substring($bundle.Length + 1).Replace('\', '/')
    if ($relative -match '(^|/)(\.viso|\.venv|\.git|__pycache__|tests?|test-results|node_modules|experiments)(/|$)' -or
        $relative -match '\.(pyc|pyo|partial|dpapi|log)$' -or $relative -match '(^|/)test_[^/]*\.py$' -or
        $relative -match '(^|/)pip([/-]|$)' -or $file.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Excluded file found in release payload: $relative"
    }
}
$hashes = foreach ($file in $files | Sort-Object FullName) {
    (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $file.FullName.Substring($bundle.Length + 1).Replace('\', '/')
}
[IO.File]::WriteAllLines((Join-Path $bundle 'SHA256SUMS.txt'), [string[]]$hashes, $utf8)
if (-not $AllowDirty) {
    $finalCommit = & git -C $root rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $finalCommit.Trim() -ne $commit.Trim()) { throw 'Source commit changed during packaging.' }
    $finalChanges = & git -C $root status --porcelain
    if ($LASTEXITCODE -ne 0 -or $finalChanges) { throw 'Source files changed during packaging. Build again from committed sources.' }
}
Compress-Archive -LiteralPath $bundle -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($archive + '.sha256'), "$hash  $name.zip`n", $utf8)
Write-Host "Runnable desktop ZIP: $archive" -ForegroundColor Green
Write-Host "SHA-256: $hash"
if ($changes) { Write-Warning 'Draft built from dirty sources. Do not publish this artifact.' }
