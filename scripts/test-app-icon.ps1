param([Parameter(Mandatory=$true)][string]$Bundle, [string]$Installer)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitProcess -or [Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') { throw 'Use native x64 Windows PowerShell with -STA.' }
$Bundle = [IO.Path]::GetFullPath($Bundle)
$root = Split-Path $PSScriptRoot -Parent
Add-Type -AssemblyName WindowsBase, PresentationCore, PresentationFramework, System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class VisoIconProbe {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)] public static extern uint ExtractIconEx(string file, int index, out IntPtr large, out IntPtr small, uint count);
    [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr icon);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
}
'@
$checks = 0
function Check([bool]$condition, [string]$message) { if (-not $condition) { throw $message }; $script:checks++ }
function Check-Colors($bitmap, [string]$label) {
    $blue = 0; $white = 0
    for ($y = 0; $y -lt $bitmap.Height; $y++) {
        for ($x = 0; $x -lt $bitmap.Width; $x++) {
            $pixel = $bitmap.GetPixel($x, $y)
            if ($pixel.A -gt 200 -and $pixel.R -lt 110 -and $pixel.G -gt 110 -and $pixel.G -lt 195 -and $pixel.B -gt 220) { $blue++ }
            if ($pixel.A -gt 200 -and $pixel.R -gt 155 -and $pixel.G -gt 185 -and $pixel.B -gt 220) { $white++ }
        }
    }
    Check ($blue -gt $bitmap.Width * $bitmap.Height * .35) "$label does not contain the blue Viso tile."
    Check ($white -ge [Math]::Max(4, $bitmap.Width * $bitmap.Height * .012)) "$label does not contain a readable white face-scan mark."
}
function Check-Handle([IntPtr]$handle, [string]$label) {
    Check ($handle -ne [IntPtr]::Zero) "$label has no Windows icon handle."
    $icon = [Drawing.Icon]::FromHandle($handle).Clone()
    $bitmap = $null
    try { $bitmap = $icon.ToBitmap(); Check-Colors $bitmap $label }
    finally { if ($bitmap) { $bitmap.Dispose() }; $icon.Dispose() }
}
function Check-ShellIcon([string]$file) {
    $large = [IntPtr]::Zero; $small = [IntPtr]::Zero
    try {
        $count = [VisoIconProbe]::ExtractIconEx($file, 0, [ref]$large, [ref]$small, 1)
        Check ($count -gt 0) "Windows could not extract the embedded executable icon: $file (count=$count)"
        Check-Handle $large 'Shell large icon'
        Check-Handle $small 'Shell small icon'
    } finally {
        if ($large -ne [IntPtr]::Zero) { [VisoIconProbe]::DestroyIcon($large) | Out-Null }
        if ($small -ne [IntPtr]::Zero) { [VisoIconProbe]::DestroyIcon($small) | Out-Null }
    }
}
$temporary = Join-Path (Join-Path $env:LOCALAPPDATA 'Temp\opencode') ('Viso icon ' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$window = $null
try {
    $iconPath = Join-Path $Bundle 'Viso.ico'
    $stream = [IO.File]::OpenRead($iconPath)
    try { $decoder = New-Object Windows.Media.Imaging.IconBitmapDecoder $stream, ([Windows.Media.Imaging.BitmapCreateOptions]::PreservePixelFormat), ([Windows.Media.Imaging.BitmapCacheOption]::OnLoad) }
    finally { $stream.Dispose() }
    $expected = @(16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
    Check ($decoder.Frames.Count -eq $expected.Count) 'Multi-resolution icon frames are missing.'
    foreach ($frame in $decoder.Frames) {
        Check ($expected -contains $frame.PixelWidth -and $frame.PixelHeight -eq $frame.PixelWidth) 'Icon contains an unexpected frame size.'
        $png = Join-Path $temporary ("icon-$($frame.PixelWidth).png")
        $encoder = New-Object Windows.Media.Imaging.PngBitmapEncoder
        $encoder.Frames.Add($frame)
        $stream = [IO.File]::Create($png)
        try { $encoder.Save($stream) } finally { $stream.Dispose() }
        $bitmap = New-Object Drawing.Bitmap $png
        try {
            Check ($bitmap.GetPixel(0, 0).A -eq 0) 'The icon has an opaque square outside the rounded tile.'
            Check-Colors $bitmap "ICO $($frame.PixelWidth)px"
        } finally { $bitmap.Dispose() }
    }
    $assembly = [Reflection.Assembly]::LoadFrom((Join-Path $Bundle 'Viso.exe'))
    $stream = $assembly.GetManifestResourceStream('Viso.AppIcon.ico')
    Check ($null -ne $stream) 'The desktop does not embed its WPF icon.'
    try {
        $copy = New-Object IO.MemoryStream
        try { $stream.CopyTo($copy); Check ([Convert]::ToBase64String($copy.ToArray()) -eq [Convert]::ToBase64String([IO.File]::ReadAllBytes($iconPath))) 'Managed icon resource differs from the shell icon source.' }
        finally { $copy.Dispose() }
    } finally { $stream.Dispose() }
    & (Join-Path $PSScriptRoot 'build-icon.ps1') -OutputPath (Join-Path $temporary 'regenerated.ico')
    Check ((Get-FileHash (Join-Path $temporary 'regenerated.ico')).Hash -eq (Get-FileHash $iconPath).Hash) 'Icon generation is not reproducible.'
    $icon = $assembly.GetType('Viso.AppIcon', $true).GetMethod('Load').Invoke($null, $null)
    Check ($icon.IsFrozen -and $icon.PixelWidth -eq 256) 'Header/window icon is not frozen and high-DPI ready.'
    $stream = $assembly.GetManifestResourceStream('Viso.MainWindow.xaml')
    try { $window = [Windows.Markup.XamlReader]::Load($stream) } finally { $stream.Dispose() }
    $window.Icon = $icon
    $window.Show()
    foreach ($width in 780, 1040) {
        $window.Width = $width; $window.UpdateLayout()
        $brand = $window.FindName('BrandLogo')
        $brand.GetBindingExpression([Windows.Controls.Image]::SourceProperty).UpdateTarget()
        $window.UpdateLayout()
        # Layout rounding can shift the logical size by a fraction of a pixel at
        # the monitor's non-integer DPI scale; retain the 24-DIP design bounds.
        Check ($brand.Source -eq $icon -and $brand.Width -eq 24 -and $brand.Height -eq 24 -and [Math]::Abs($brand.ActualWidth - 24) -lt 1 -and [Math]::Abs($brand.ActualHeight - 24) -lt 1) ("Title-bar logo is missing or mis-sized: source=$($brand.Source), width=$($brand.ActualWidth), height=$($brand.ActualHeight), window=$width")
    }
    $handle = (New-Object Windows.Interop.WindowInteropHelper $window).Handle
    Check-Handle ([VisoIconProbe]::SendMessage($handle, 0x7F, [IntPtr]0, [IntPtr]::Zero)) 'Actual WPF small window icon'
    Check-Handle ([VisoIconProbe]::SendMessage($handle, 0x7F, [IntPtr]1, [IntPtr]::Zero)) 'Actual WPF big window icon'
    Check-ShellIcon (Join-Path $Bundle 'Viso.exe')
    if ($Installer) { Check-ShellIcon ([IO.Path]::GetFullPath($Installer)) }
    Write-Host "App icon checks passed: $checks; all 10 ICO sizes, reproducibility, embedded shell/WPF icons and header binding."
    Write-Host 'No app controller, runtime, camera, enrollment, service or account operation was started.'
} finally {
    if ($window) { $window.Close() }
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
