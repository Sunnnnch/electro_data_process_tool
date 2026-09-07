# Shared guards for the exact directories owned by the Windows build scripts.
function Assert-DistributionRoot {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$RelativeRoot
    )
    # Only named top-level distribution roots are accepted. In particular, a
    # caller cannot make an arbitrary source directory the expected target.
    if ($RelativeRoot -cnotmatch '^dist(?:_[A-Za-z0-9][A-Za-z0-9_-]*)?$') {
        throw "Expected a repository distribution root named dist or dist_<name>: $RelativeRoot"
    }
    return Assert-ExpectedBuildPath $ProjectRoot (Join-Path $ProjectRoot $RelativeRoot) $RelativeRoot
}

function Assert-ExpectedBuildPath {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$ExpectedRelativePath
    )
    $RootPath = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $ExpectedPath = [IO.Path]::GetFullPath((Join-Path $RootPath $ExpectedRelativePath))
    $TargetPath = [IO.Path]::GetFullPath($Target)
    $RootPrefix = $RootPath + [IO.Path]::DirectorySeparatorChar
    if ($RootPath -eq [IO.Path]::GetPathRoot($RootPath).TrimEnd([IO.Path]::DirectorySeparatorChar) -or
        -not $ExpectedPath.StartsWith($RootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $TargetPath.Equals($ExpectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unexpected build path: $TargetPath"
    }
    # Resolve-Path alone does not resolve every junction. Reject reparse points
    # anywhere in the ancestor chain before any write or recursive removal.
    $ProbePath = $TargetPath
    while ($ProbePath) {
        if (Test-Path -LiteralPath $ProbePath) {
            $Item = Get-Item -LiteralPath $ProbePath -Force
            if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing build path through a reparse point: $ProbePath"
            }
            $ResolvedPath = (Resolve-Path -LiteralPath $ProbePath).ProviderPath
            if (-not ([IO.Path]::GetFullPath($ResolvedPath)).Equals($ProbePath, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Build path resolved unexpectedly: $ProbePath"
            }
        }
        $ProbePath = Split-Path -Parent $ProbePath
    }
    return $TargetPath
}

function Remove-CheckedBuildDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$ExpectedRelativePath
    )
    $VerifiedPath = Assert-ExpectedBuildPath -ProjectRoot $ProjectRoot -Target $Target -ExpectedRelativePath $ExpectedRelativePath
    if (Test-Path -LiteralPath $VerifiedPath) {
        if (Test-Path -LiteralPath (Join-Path $VerifiedPath "user_data")) {
            throw "Refusing to remove portable user_data in build output: $VerifiedPath. Preserve or relocate the data before rebuilding."
        }
        # Reject junctions inside an output before recursively removing it.
        $Links = Get-ChildItem -LiteralPath $VerifiedPath -Force -Recurse |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
            Select-Object -First 1
        if ($Links) { throw "Refusing output containing a reparse point: $($Links.FullName)" }
        Remove-Item -LiteralPath $VerifiedPath -Recurse -Force
    }
}
