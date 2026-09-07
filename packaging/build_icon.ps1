param(
    [string]$SourcePng = (Join-Path $PSScriptRoot '..\design\icon-concepts\2026-09-08\D-intelligent-data.png')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sourcePath = (Resolve-Path -LiteralPath $SourcePng).Path
$desktopAssets = Join-Path $repositoryRoot 'src\electrochem_v6\desktop\assets'
$staticAssets = Join-Path $repositoryRoot 'src\electrochem_v6\ui\static'
$packagingAssets = Join-Path $PSScriptRoot 'assets'
$sizes = @(16, 20, 24, 32, 40, 48, 64, 128, 256)
$frames = [System.Collections.Generic.List[byte[]]]::new()

# Convert the complete selected artwork. No crop, background replacement,
# palette change, or additional mark is applied to the approved design.
$original = [System.Drawing.Image]::FromFile($sourcePath)
try {
    if ($original.Width -ne $original.Height) {
        throw 'The approved application icon must be square; refusing to distort it.'
    }
    foreach ($size in $sizes) {
        $bitmap = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $attributes = [System.Drawing.Imaging.ImageAttributes]::new()
        $frameStream = [System.IO.MemoryStream]::new()
        try {
            $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
            $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $attributes.SetWrapMode([System.Drawing.Drawing2D.WrapMode]::TileFlipXY)
            $graphics.DrawImage($original, [System.Drawing.Rectangle]::new(0, 0, $size, $size),
                0, 0, $original.Width, $original.Height, [System.Drawing.GraphicsUnit]::Pixel, $attributes)
            $bitmap.Save($frameStream, [System.Drawing.Imaging.ImageFormat]::Png)
            $frames.Add($frameStream.ToArray())
        }
        finally {
            $frameStream.Dispose()
            $attributes.Dispose()
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }
}
finally {
    $original.Dispose()
}

# ICO directory plus PNG-compressed 32-bit frames (supported by modern Windows).
$iconStream = [System.IO.MemoryStream]::new()
$writer = [System.IO.BinaryWriter]::new($iconStream)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$sizes.Count)
    $offset = 6 + 16 * $sizes.Count
    for ($index = 0; $index -lt $sizes.Count; $index++) {
        $dimension = if ($sizes[$index] -eq 256) { 0 } else { $sizes[$index] }
        $writer.Write([byte]$dimension)
        $writer.Write([byte]$dimension)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$frames[$index].Length)
        $writer.Write([uint32]$offset)
        $offset += $frames[$index].Length
    }
    foreach ($frame in $frames) {
        $writer.Write([byte[]]$frame)
    }
    $writer.Flush()
    $iconBytes = $iconStream.ToArray()
}
finally {
    $writer.Dispose()
    $iconStream.Dispose()
}

# Verify every directory entry through the Windows icon decoder. Isolate the
# entries because .NET Framework's multi-size selector can choose 128 when 256
# is requested (the ICO directory represents 256 with a zero dimension byte).
for ($index = 0; $index -lt $sizes.Count; $index++) {
    $size = $sizes[$index]
    $checkStream = [System.IO.MemoryStream]::new()
    $checkWriter = [System.IO.BinaryWriter]::new($checkStream)
    $icon = $null
    $nativeIcon = $null
    $decoded = $null
    try {
        $checkWriter.Write([uint16]0)
        $checkWriter.Write([uint16]1)
        $checkWriter.Write([uint16]1)
        $checkWriter.Write($iconBytes, (6 + 16 * $index), 12)
        $checkWriter.Write([uint32]22)
        $checkWriter.Write([byte[]]$frames[$index])
        $checkWriter.Flush()
        $checkStream.Position = 0
        $icon = [System.Drawing.Icon]::new($checkStream, $size, $size)
        $nativeIcon = [System.Drawing.Icon]::FromHandle($icon.Handle)
        $decoded = $nativeIcon.ToBitmap()
        if ($decoded.Width -ne $size -or $decoded.Height -ne $size) {
            throw "Windows selected an unexpected icon frame for $size pixels: icon $($icon.Width)x$($icon.Height), bitmap $($decoded.Width)x$($decoded.Height)."
        }
    }
    catch {
        throw "Windows could not decode the $size pixel icon: $_"
    }
    finally {
        if ($decoded) { $decoded.Dispose() }
        if ($nativeIcon) { $nativeIcon.Dispose() }
        if ($icon) { $icon.Dispose() }
        $checkWriter.Dispose()
        $checkStream.Dispose()
    }
}
$multiStream = [System.IO.MemoryStream]::new($iconBytes, $false)
$multiIcon = $null
try {
    $multiIcon = [System.Drawing.Icon]::new($multiStream, 32, 32)
    if ($multiIcon.Width -ne 32 -or $multiIcon.Height -ne 32) {
        throw 'Windows could not load the complete multi-frame ICO.'
    }
}
finally {
    if ($multiIcon) { $multiIcon.Dispose() }
    $multiStream.Dispose()
}

foreach ($directory in @($desktopAssets, $staticAssets, $packagingAssets)) {
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
}
$desktopPng = Join-Path $desktopAssets 'app_icon.png'
$faviconPng = Join-Path $staticAssets 'app_icon.png'
$desktopIco = Join-Path $desktopAssets 'app_icon.ico'
$packagingIco = Join-Path $packagingAssets 'app_icon.ico'
[System.IO.File]::Copy($sourcePath, $desktopPng, $true)
[System.IO.File]::Copy($sourcePath, $faviconPng, $true)
[System.IO.File]::WriteAllBytes($desktopIco, $iconBytes)
[System.IO.File]::WriteAllBytes($packagingIco, $iconBytes)

$sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
foreach ($pngPath in @($desktopPng, $faviconPng)) {
    if ((Get-FileHash -LiteralPath $pngPath -Algorithm SHA256).Hash -ne $sourceHash) {
        throw "Original PNG copy verification failed: $pngPath"
    }
}
if ((Get-FileHash -LiteralPath $desktopIco -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $packagingIco -Algorithm SHA256).Hash) {
    throw 'Desktop and packaging ICO resources differ.'
}
Write-Output "ElectroChem icon built and decoded: $($sizes -join ', ') px"
Write-Output "PNG SHA-256: $sourceHash"
Write-Output "ICO SHA-256: $((Get-FileHash -LiteralPath $desktopIco -Algorithm SHA256).Hash)"
