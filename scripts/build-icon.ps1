param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
# Use one rendering implementation across PowerShell 7/5 and x86/x64 shells:
# native Framework WPF in STA, rather than slightly different .NET WPF builds.
# No graphics package or additional runtime is downloaded.
if ($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or [Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
    $systemDirectory = if ([Environment]::Is64BitProcess) { 'System32' } else { 'Sysnative' }
    $hostPath = Join-Path $env:WINDIR "$systemDirectory\WindowsPowerShell\v1.0\powershell.exe"
    & $hostPath -STA -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath -OutputPath $OutputPath
    if ($LASTEXITCODE -ne 0) { throw 'Windows icon generation failed.' }
    return
}
Add-Type -AssemblyName WindowsBase, PresentationCore, PresentationFramework
# Avoid driver-dependent antialiasing differences in generated release assets.
[Windows.Media.RenderOptions]::ProcessRenderMode = [Windows.Interop.RenderMode]::SoftwareOnly
$source = Join-Path (Split-Path $PSScriptRoot -Parent) 'desktop\Viso\Assets\Logo.xaml'
$logo = [Windows.Markup.XamlReader]::Parse([IO.File]::ReadAllText($source))
$logo.Freeze()
$sizes = @(16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
$images = @()
foreach ($size in $sizes) {
    $visual = New-Object Windows.Media.DrawingVisual
    $drawing = $visual.RenderOpen()
    try { $drawing.DrawImage($logo, (New-Object Windows.Rect 0, 0, ($size * 4), ($size * 4))) }
    finally { $drawing.Close() }
    $large = New-Object Windows.Media.Imaging.RenderTargetBitmap ($size * 4), ($size * 4), 96, 96, ([Windows.Media.PixelFormats]::Pbgra32)
    $large.Render($visual)
    $visual = New-Object Windows.Media.DrawingVisual
    [Windows.Media.RenderOptions]::SetBitmapScalingMode($visual, [Windows.Media.BitmapScalingMode]::HighQuality)
    $drawing = $visual.RenderOpen()
    try { $drawing.DrawImage($large, (New-Object Windows.Rect 0, 0, $size, $size)) }
    finally { $drawing.Close() }
    $bitmap = New-Object Windows.Media.Imaging.RenderTargetBitmap $size, $size, 96, 96, ([Windows.Media.PixelFormats]::Pbgra32)
    $bitmap.Render($visual)
    $stream = New-Object IO.MemoryStream
    try {
        if ($size -eq 256) {
            $encoder = New-Object Windows.Media.Imaging.PngBitmapEncoder
            $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
            $encoder.Save($stream)
        } else {
            # Small entries use conventional 32-bit DIBs plus an AND mask for
            # Explorer/.NET icon consumers; the 256px entry uses PNG compression.
            $converted = New-Object Windows.Media.Imaging.FormatConvertedBitmap $bitmap, ([Windows.Media.PixelFormats]::Bgra32), $null, 0
            $pixels = New-Object byte[] ($size * $size * 4)
            $converted.CopyPixels($pixels, ($size * 4), 0)
            $maskStride = [int]([Math]::Ceiling($size / 32.0) * 4)
            $mask = New-Object byte[] ($maskStride * $size)
            $writer = New-Object IO.BinaryWriter $stream
            $writer.Write([uint32]40); $writer.Write([int]$size); $writer.Write([int]($size * 2))
            $writer.Write([uint16]1); $writer.Write([uint16]32); $writer.Write([uint32]0)
            $writer.Write([uint32]($pixels.Length + $mask.Length))
            foreach ($unused in 1..4) { $writer.Write([uint32]0) }
            for ($row = $size - 1; $row -ge 0; $row--) {
                $writer.Write($pixels, ($row * $size * 4), ($size * 4))
                for ($column = 0; $column -lt $size; $column++) {
                    if ($pixels[($row * $size + $column) * 4 + 3] -eq 0) {
                        $offset = ($size - 1 - $row) * $maskStride + [int][Math]::Floor($column / 8.0)
                        $mask[$offset] = $mask[$offset] -bor (0x80 -shr ($column % 8))
                    }
                }
            }
            $writer.Write($mask); $writer.Flush()
        }
        $images += ,$stream.ToArray()
    } finally { $stream.Dispose() }
}
$stream = New-Object IO.MemoryStream
try {
    $writer = New-Object IO.BinaryWriter $stream
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$sizes.Count)
    $offset = 6 + $sizes.Count * 16
    for ($index = 0; $index -lt $sizes.Count; $index++) {
        $dimension = if ($sizes[$index] -eq 256) { 0 } else { $sizes[$index] }
        $writer.Write([byte]$dimension); $writer.Write([byte]$dimension)
        $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32)
        $writer.Write([uint32]$images[$index].Length); $writer.Write([uint32]$offset)
        $offset += $images[$index].Length
    }
    foreach ($image in $images) { $writer.Write([byte[]]$image) }
    $writer.Flush()
    $bytes = $stream.ToArray()
    New-Item -ItemType Directory -Path (Split-Path $OutputPath -Parent) -Force | Out-Null
    if (-not [IO.File]::Exists($OutputPath) -or [Convert]::ToBase64String([IO.File]::ReadAllBytes($OutputPath)) -ne [Convert]::ToBase64String($bytes)) {
        [IO.File]::WriteAllBytes($OutputPath, $bytes)
    }
} finally { $stream.Dispose() }
Write-Host "Built Viso icon: $OutputPath (10 sizes, 16-256px)"
