param([switch]$Test)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if ($Test -and -not (Test-Path "$root\signin\Tests\ServiceTests.cs")) { throw 'Validation sources are maintained on the test branch.' }
$out = Join-Path $root 'signin\bin'
New-Item $out -ItemType Directory -Force | Out-Null
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw 'Install Visual Studio C++ Build Tools and the Windows SDK first.' }
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'The Visual Studio x64 C++ toolset is required.' }
$vc = Get-ChildItem (Join-Path $vs 'VC\Tools\MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$kits = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots').KitsRoot10
$sdk = Get-ChildItem (Join-Path $kits 'Include') -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'um\credentialprovider.h') } | Sort-Object Name -Descending | Select-Object -First 1
if (-not $sdk) { throw 'The Windows 10/11 SDK is required.' }
$compiler = Join-Path $vc.FullName 'bin\Hostx64\x64\cl.exe'
$previousInclude, $previousLib, $previousPath = $env:INCLUDE, $env:LIB, $env:PATH
try {
    $env:INCLUDE = (Join-Path $vc.FullName 'include') + ';' + (($('ucrt','shared','um','winrt') | ForEach-Object { Join-Path $sdk.FullName $_ }) -join ';')
    $env:LIB = (Join-Path $vc.FullName 'lib\x64') + ';' + (Join-Path $kits "Lib\$($sdk.Name)\ucrt\x64") + ';' + (Join-Path $kits "Lib\$($sdk.Name)\um\x64")
    $env:PATH = (Split-Path $compiler) + ';' + $env:PATH
    $common = @('/nologo','/std:c++17','/utf-8','/EHsc','/W4','/WX','/O2','/MT','/guard:cf','/DUNICODE','/D_UNICODE','/D_WIN32_WINNT=0x0A00',"/Fo$out\")
    $libraries = @('ole32.lib','uuid.lib','shlwapi.lib','secur32.lib','credui.lib','advapi32.lib','gdi32.lib','propsys.lib','shell32.lib','comctl32.lib','user32.lib')
    & $compiler @common /LD "$root\signin\Provider\Provider.cpp" "$root\signin\Provider\Auth.cpp" /link @libraries "/OUT:$out\VisoCredentialProvider.dll" "/IMPLIB:$out\VisoCredentialProvider.lib" /EXPORT:DllGetClassObject,PRIVATE /EXPORT:DllCanUnloadNow,PRIVATE /DYNAMICBASE /NXCOMPAT /GUARD:CF
    if ($LASTEXITCODE -ne 0) { throw 'Credential Provider build failed.' }
    $framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
    $sources = @((Get-ChildItem "$root\signin\Shared\*.cs").FullName) + @((Get-ChildItem "$root\signin\Service\*.cs").FullName)
    $references = @('System.dll','System.Core.dll','System.Security.dll','System.ServiceProcess.dll','System.Web.Extensions.dll') | ForEach-Object { '/reference:' + (Join-Path $framework $_) }
    & "$framework\csc.exe" /nologo /target:exe /platform:x64 /optimize+ /utf8output "/out:$out\VisoSignInService.exe" @references @sources
    if ($LASTEXITCODE -ne 0) { throw 'Windows sign-in service build failed.' }
    if ($Test) {
        & $compiler @common "$root\signin\Tests\ProviderTests.cpp" "$root\signin\Provider\Auth.cpp" /link @libraries "/OUT:$out\ProviderTests.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Provider test build failed.' }
        & "$out\ProviderTests.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Provider tests failed.' }
        & "$framework\csc.exe" /nologo /target:exe /platform:x64 /optimize+ /main:Viso.SignIn.Tests "/out:$out\ServiceTests.exe" @references @sources "$root\signin\Tests\ServiceTests.cs"
        if ($LASTEXITCODE -ne 0) { throw 'Service test build failed.' }
        & "$out\ServiceTests.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Service tests failed.' }
        & "$root\.venv\Scripts\python.exe" -m unittest backend.tests.test_signin -v
        if ($LASTEXITCODE -ne 0) { throw 'Sign-in worker tests failed.' }
        & (Join-Path $PSScriptRoot 'test-signin-deployment.ps1')
    }
    Write-Host "Built Windows sign-in components: $out" -ForegroundColor Green
} finally { $env:INCLUDE = $previousInclude; $env:LIB = $previousLib; $env:PATH = $previousPath }
