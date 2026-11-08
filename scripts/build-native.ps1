param([switch]$SmokeTest, [string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$compiler = Join-Path $framework 'csc.exe'
if (-not (Test-Path $compiler)) { throw 'Viso needs the Windows .NET Framework 4.8 desktop runtime.' }
$source = Join-Path $root 'desktop\Viso'
if ($SmokeTest -and -not (Test-Path "$source\RenderingChecks.cs")) { throw 'Smoke checks are maintained on the test branch.' }
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root 'desktop\bin' }
New-Item -ItemType Directory -Path $output -Force | Out-Null
$references = @('System.dll', 'System.Core.dll', 'System.Security.dll', 'System.Xaml.dll', 'System.Web.Extensions.dll', 'WPF\WindowsBase.dll', 'WPF\PresentationCore.dll', 'WPF\PresentationFramework.dll')
$arguments = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/utf8output', "/out:$output\Viso.exe", "/win32manifest:$source\app.manifest", "/resource:$source\MainWindow.xaml,Viso.MainWindow.xaml")
foreach ($reference in $references) { $arguments += '/reference:' + (Join-Path $framework $reference) }
$arguments += (Get-ChildItem $source -Filter '*.cs' | Where-Object { $SmokeTest -or $_.Name -ne 'RenderingChecks.cs' }).FullName
if ($SmokeTest) { $arguments += '/define:VISO_TESTS' }
$arguments += (Get-ChildItem (Join-Path $root 'signin\Shared') -Filter '*.cs').FullName
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw 'Native Windows build failed.' }
Copy-Item (Join-Path $source 'Viso.exe.config') $output -Force
Write-Host "Built native app: $output\Viso.exe" -ForegroundColor Green
if ($SmokeTest) {
    $process = Start-Process (Join-Path $output 'Viso.exe') -ArgumentList '--smoke-test', '--ephemeral' -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw 'Native smoke test failed. See test-results/native/error.txt or desktop/bin/smoke-error.txt.' }
    Write-Host 'Native smoke test passed. Screenshots: test-results/native/' -ForegroundColor Green
}
