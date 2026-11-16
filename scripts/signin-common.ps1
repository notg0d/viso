# Shared deployment helpers; loading this file does not install or register anything.
function Assert-VisoNoReparse([string]$path) {
    $current = [IO.Path]::GetFullPath($path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse points are not allowed in the sign-in installation path: $current"
            }
        }
        $current = Split-Path $current -Parent
    }
}

function Assert-VisoAcl($acl, [bool]$readable) {
    $trusted = @('S-1-5-18', 'S-1-5-32-544')
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $trusted) {
        throw 'Sign-in files must already be owned by SYSTEM or Administrators. Untrusted existing data cannot be adopted.'
    }
    $allowed = 0
    if ($readable) { $allowed = [int][Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [int][Security.AccessControl.FileSystemRights]::Synchronize }
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin $trusted -and (([int]$rule.FileSystemRights -band (-bnot $allowed)) -ne 0)) {
            throw 'Existing sign-in files have untrusted access permissions. Remove the old installation and link accounts again.'
        }
    }
}

function Assert-VisoTree([string]$path, [bool]$readable) {
    Assert-VisoNoReparse $path
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push($path)
    while ($pending.Count) {
        $item = Get-Item -LiteralPath $pending.Pop() -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected reparse point: $($item.FullName)" }
        Assert-VisoAcl (Get-Acl -LiteralPath $item.FullName) $readable
        if ($item.PSIsContainer) {
            foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) { $pending.Push($child.FullName) }
        }
    }
}

function Initialize-VisoDeployment {
    if (-not ('Viso.Deployment' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
namespace Viso {
    public static class Deployment {
        [StructLayout(LayoutKind.Sequential)] private struct Attributes { public int Length; public IntPtr Descriptor; public int Inherit; }
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, uint revision, out IntPtr descriptor, out uint size);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool CreateDirectory(string path, ref Attributes attributes);
        [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr memory);
        public static void Create(string path, string sddl) {
            IntPtr descriptor; uint size;
            if (!ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1, out descriptor, out size)) throw new Win32Exception();
            try {
                var attributes = new Attributes { Length = Marshal.SizeOf(typeof(Attributes)), Descriptor = descriptor };
                if (!CreateDirectory(path, ref attributes)) throw new Win32Exception();
            } finally { LocalFree(descriptor); }
        }
    }
}
'@
    }
}

function New-VisoProtectedDirectory([string]$path, [bool]$readable) {
    # Create with its final owner/DACL atomically: no user-writable ProgramData window.
    Initialize-VisoDeployment
    Assert-VisoNoReparse (Split-Path $path -Parent)
    $sddl = 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    if ($readable) { $sddl += '(A;OICI;FRFX;;;BU)' }
    [Viso.Deployment]::Create($path, $sddl)
}

function Set-VisoPayloadOwner([string]$path) {
    # Only for the fresh, protected payload tree, before executing its Python runtime.
    foreach ($item in @((Get-Item -LiteralPath $path)) + @(Get-ChildItem -LiteralPath $path -Recurse -Force)) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected reparse point in copied payload.' }
        $acl = Get-Acl -LiteralPath $item.FullName
        $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier 'S-1-5-32-544'))
        Set-Acl -LiteralPath $item.FullName -AclObject $acl
    }
}

function Copy-VisoTree([string]$from, [string]$to, [string[]]$exclude = @(), [string[]]$excludeFiles = @()) {
    $arguments = @($from,$to,'/E','/COPY:DAT','/DCOPY:DAT','/R:1','/W:1','/NFL','/NDL','/NJH','/NJS','/NP','/XJ')
    if ($exclude.Count) { $arguments += '/XD'; $arguments += $exclude }
    if ($excludeFiles.Count) { $arguments += '/XF'; $arguments += $excludeFiles }
    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Could not copy $from." }
}

function Copy-VisoRuntime([string]$root, [string]$destination, [switch]$ProtectedPayload) {
    $base = & "$root\.venv\Scripts\python.exe" -I -c 'import sys; print(sys.base_prefix)'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$base\python.exe")) { throw 'Cannot locate the Python runtime.' }
    $runtime = Join-Path $destination 'runtime'
    New-Item $runtime -ItemType Directory | Out-Null
    Get-ChildItem $base -File | Where-Object { $_.Name -match '^python.*\.(exe|dll)$|^vcruntime.*\.dll$|^LICENSE' } | Copy-Item -Destination $runtime
    Copy-VisoTree "$base\DLLs" "$runtime\DLLs" @() @('_test*.pyd', '_ctypes_test.pyd', 'xx*.pyd')
    Copy-VisoTree "$base\Lib" "$runtime\Lib" @('site-packages','__pycache__','test','tests','idlelib','ensurepip')
    & "$root\.venv\Scripts\python.exe" -I -B "$root\scripts\package-runtime.py" $root $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Could not package the pinned Python dependencies.' }
    Copy-VisoTree "$root\backend\viso" "$destination\backend\viso" @('__pycache__')
    if (Test-Path "$root\backend\__init__.py") { Copy-Item "$root\backend\__init__.py" "$destination\backend\__init__.py" }
    Copy-Item "$root\backend\run_native.py" "$destination\backend\run_native.py"
    # Copy only pinned models/notices, never local downloads or partial files.
    New-Item "$destination\models\licenses" -ItemType Directory -Force | Out-Null
    Copy-Item "$root\models\manifest.json" "$destination\models\manifest.json"
    $manifest = Get-Content -LiteralPath "$root\models\manifest.json" -Raw | ConvertFrom-Json
    foreach ($model in $manifest.models) {
        Copy-Item (Join-Path "$root\models" $model.file) "$destination\models"
        Copy-Item (Join-Path "$root\models\licenses" ($model.directory + '.txt')) "$destination\models\licenses"
    }
    Copy-Item "$root\THIRD_PARTY_NOTICES.md" $destination
    if ($ProtectedPayload) {
        Set-VisoPayloadOwner $destination
        Assert-VisoTree $destination $true
    }
    # Generate fresh caches with this runtime, not the developer's venv caches.
    # Checked hashes survive relocation and reject changed source. -B prevents
    # incidental import writes; compileall explicitly writes the build artifacts.
    & "$runtime\python.exe" -I -B -m compileall -q --invalidation-mode checked-hash -s $destination "$runtime\Lib"
    if ($LASTEXITCODE -ne 0) { throw 'Could not precompile the packaged Python runtime.' }
    Assert-VisoPayloadPaths $destination
    Test-VisoRuntime $destination
}

function Assert-VisoPayloadPaths([string]$folder) {
    # Read-only structural audit: never execute an unprotected installer payload.
    $folder = [IO.Path]::GetFullPath($folder).TrimEnd('\')
    Assert-VisoNoReparse $folder
    $bytecode = $null
    foreach ($item in Get-ChildItem -LiteralPath $folder -Recurse -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are not allowed in the payload.' }
        $relative = $item.FullName.Substring($folder.Length + 1).Replace('\','/')
        if ($relative -match '(^|/)(\.viso|\.venv|\.git|tests?|test-results|node_modules|experiments)(/|$)' -or
            $relative -match '\.(dpapi|pyo|partial|log)$' -or $relative -match '(^|/)test_[^/]*\.py$' -or $relative -match '(^|/)pip([/-]|$)') {
            throw "Private or development data was found in the payload: $relative"
        }
        if ($relative -notmatch '(^|/)__pycache__(/|$)|\.pyc$') { continue }
        if (-not $bytecode) {
            $inventory = Get-Content -LiteralPath (Join-Path $folder 'runtime\packages.json') -Raw | ConvertFrom-Json
            $bytecode = $inventory.bytecode
            if ($inventory.python -notmatch '^(\d+)\.(\d+)\.\d+$') { throw 'Invalid packaged Python version.' }
            $tag = 'cpython-' + $Matches[1] + $Matches[2]
            if (-not $bytecode -or $bytecode.cache_tag -cne $tag -or $bytecode.magic -cnotmatch '^[0-9a-f]{4}0d0a$' -or $bytecode.invalidation -cne 'checked-hash') {
                throw 'Invalid packaged bytecode inventory.'
            }
        }
        if ($item.PSIsContainer) {
            if ($relative -cnotmatch '^runtime/Lib/(?:[^/]+/)*__pycache__$' -or @($relative.Split('/') | Where-Object { $_ -ceq '__pycache__' }).Count -ne 1) { throw 'Unexpected bytecode directory.' }
            continue
        }
        if ($relative -cnotmatch ('^runtime/Lib/(?<parent>(?:[^/]+/)*)__pycache__/(?<module>[^/]+)\.' + [regex]::Escape($bytecode.cache_tag) + '\.pyc$')) { throw 'Unexpected bytecode path or interpreter tag.' }
        $source = Join-Path $folder ('runtime/Lib/' + $Matches['parent'] + $Matches['module'] + '.py')
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Bytecode without corresponding source is not allowed.' }
        $stream = [IO.File]::OpenRead($item.FullName)
        try {
            $header = New-Object byte[] 16
            if ($stream.Length -le 16 -or $stream.Read($header, 0, 16) -ne 16) { throw 'Truncated packaged bytecode.' }
        } finally { $stream.Dispose() }
        $magic = [BitConverter]::ToString($header, 0, 4).Replace('-','').ToLowerInvariant()
        if ($magic -cne $bytecode.magic -or [BitConverter]::ToUInt32($header, 4) -ne 3) { throw 'Only checked-hash bytecode for the packaged interpreter is allowed.' }
    }
}

function Get-VisoBytecodeCheck {
    # Used only with a trusted runtime. Installer manifest validation stays read-only.
    return @'
import importlib.util, json, marshal, pathlib, sys, types
root = pathlib.Path(sys.argv[1]).resolve()
runtime = root / 'runtime'
inventory = json.loads((runtime / 'packages.json').read_text(encoding='utf-8'))
assert inventory['python'] == sys.version.split()[0]
assert inventory['bytecode'] == {'cache_tag': sys.implementation.cache_tag, 'magic': importlib.util.MAGIC_NUMBER.hex(), 'invalidation': 'checked-hash'}
sources = list((runtime / 'Lib').rglob('*.py'))
assert sources, 'No packaged Python sources'
expected = set()
def check_code(code, filename):
    assert isinstance(code, types.CodeType), filename
    assert code.co_filename.replace('\\', '/') == filename, code.co_filename
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            check_code(value, filename)
for source in sources:
    cache = pathlib.Path(importlib.util.cache_from_source(str(source)))
    expected.add(cache)
    data = cache.read_bytes()
    assert data[:4] == importlib.util.MAGIC_NUMBER and int.from_bytes(data[4:8], 'little') == 3, cache
    assert data[8:16] == importlib.util.source_hash(source.read_bytes()), cache
    check_code(marshal.loads(data[16:]), source.relative_to(root).as_posix())
assert set(root.rglob('*.pyc')) == expected, 'Unexpected or missing bytecode'
print(f'Checked-hash bytecode, source hashes and relative code filenames passed ({len(expected)} modules).')
'@
}

function Test-VisoRuntime([string]$destination) {
    # Shared by source deployment and the offline, protected installer staging path.
    # Import isolation plus actual model checksums/loading/inference; no camera access.
    $runtime = Join-Path $destination 'runtime'
    & "$runtime\python.exe" -I -B -c (Get-VisoBytecodeCheck) $destination
    if ($LASTEXITCODE -ne 0) { throw 'The packaged Python bytecode did not validate.' }
    $check = @'
import pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import cv2, numpy, mediapipe
for module in (cv2, numpy, mediapipe):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root / 'runtime'), module.__name__
assert pathlib.Path(sys.base_prefix).resolve() == root / 'runtime', sys.base_prefix
from backend.viso.recognition import FaceEngine
engine = FaceEngine(root / 'models')
try:
    assert engine.observe(numpy.zeros((480, 640, 3), dtype=numpy.uint8)).face_count == 0
finally:
    engine.close()
print('Private runtime, isolated imports, model checksums and blank-frame inference passed.')
'@
    & "$runtime\python.exe" -I -B -c $check $destination
    if ($LASTEXITCODE -ne 0) { throw 'The packaged recognition runtime did not initialize.' }
}
