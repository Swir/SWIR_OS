param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,

    [string]$PackageSigningKeyId = '',

    [string]$PackageSigningPrivateKeyFile = '',

    [string]$PackageTrustRootsOutput = '',

    [string]$PackageSignerDll = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$source = [System.IO.Path]::GetFullPath($SourceRoot)
$output = [System.IO.Path]::GetFullPath($OutputDir)
if (-not (Test-Path $source -PathType Container)) { throw "SWIR source root does not exist: $source" }
if (-not (Test-Path (Join-Path $source 'swir-packages.js') -PathType Leaf)) { throw 'swir-packages.js is missing.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is required to export the reviewed package catalog.' }

# Refuse stale package output before any generated trust material is written into
# the output tree. Controlled signed builds are allowed to place their public
# package trust-root file inside the otherwise-empty output directory.
if (Test-Path $output -PathType Container) {
    $existing = @(Get-ChildItem -LiteralPath $output -Force)
    if ($existing.Count -gt 0) { throw "Desktop Store package output must be empty: $output" }
} else {
    New-Item -ItemType Directory -Path $output -Force | Out-Null
}

$signingRequested = (-not [string]::IsNullOrWhiteSpace($PackageSigningKeyId)) -or
                    (-not [string]::IsNullOrWhiteSpace($PackageSigningPrivateKeyFile)) -or
                    (-not [string]::IsNullOrWhiteSpace($PackageTrustRootsOutput))
$packageSigner = $null
$packagePrivateKey = $null
$packageTrustRoots = $null
if ($signingRequested) {
    if ([string]::IsNullOrWhiteSpace($PackageSigningKeyId) -or
        [string]::IsNullOrWhiteSpace($PackageSigningPrivateKeyFile) -or
        [string]::IsNullOrWhiteSpace($PackageTrustRootsOutput)) {
        throw 'Package signing requires PackageSigningKeyId, PackageSigningPrivateKeyFile and PackageTrustRootsOutput together.'
    }
    if ($PackageSigningKeyId -notmatch '^[A-Za-z0-9._-]{1,128}$') { throw 'PackageSigningKeyId is invalid.' }
    if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw '.NET is required to sign and verify Desktop Store packages.' }

    $packagePrivateKey = [System.IO.Path]::GetFullPath($PackageSigningPrivateKeyFile)
    if (-not (Test-Path $packagePrivateKey -PathType Leaf)) { throw "Package signing private-key file is missing: $packagePrivateKey" }
    $packageTrustRoots = [System.IO.Path]::GetFullPath($PackageTrustRootsOutput)
    $packageSigner = if ([string]::IsNullOrWhiteSpace($PackageSignerDll)) {
        Join-Path $PSScriptRoot 'bin\Release\net8.0-windows\SWIR.Desktop.PackageSignatureTool.dll'
    } else {
        [System.IO.Path]::GetFullPath($PackageSignerDll)
    }
    if (-not (Test-Path $packageSigner -PathType Leaf)) { throw "Package signature utility is missing: $packageSigner" }

    $trustDirectory = Split-Path $packageTrustRoots -Parent
    if (-not [string]::IsNullOrWhiteSpace($trustDirectory)) { New-Item -ItemType Directory -Path $trustDirectory -Force | Out-Null }
    & dotnet $packageSigner trust-root $PackageSigningKeyId $packagePrivateKey $packageTrustRoots
    if ($LASTEXITCODE -ne 0) { throw "Package trust-root generation failed with exit code $LASTEXITCODE" }

    $trust = Get-Content -LiteralPath $packageTrustRoots -Raw | ConvertFrom-Json
    if ($trust.schema -ne 'swir.package-trust-roots/1.0' -or
        $trust.requireSignedPackages -ne $true -or
        @($trust.roots).Count -ne 1 -or
        [string]$trust.roots[0].keyId -ne $PackageSigningKeyId) {
        throw 'Generated package trust-root policy is not fail-closed or does not match PackageSigningKeyId.'
    }
}

$packagesDir = Join-Path $output 'packages'
New-Item -ItemType Directory -Path $packagesDir -Force | Out-Null

$catalogJson = & node -e @'
const fs=require('fs'),vm=require('vm');
const p=process.argv[1];
const source=fs.readFileSync(p,'utf8');
const sandbox={window:{}};
vm.createContext(sandbox);
vm.runInContext(source,sandbox,{filename:p,timeout:3000});
const catalog=sandbox.window.SWIR_PACKAGE_CATALOG;
if(!Array.isArray(catalog)||!catalog.length) throw new Error('SWIR_PACKAGE_CATALOG must be non-empty');
process.stdout.write(JSON.stringify(catalog));
'@ (Join-Path $source 'swir-packages.js')
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($catalogJson)) { throw 'Could not export SWIR package catalog.' }
$catalog = @($catalogJson | ConvertFrom-Json)
if ($catalog.Count -eq 0) { throw 'Exported package catalog is empty.' }

$artifactRecords = [System.Collections.Generic.List[object]]::new()
$seenIdentity = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$seenOutput = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$sourcePrefix = $source.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-SafeRelativePath([string]$RelativePath, [string]$Context) {
    $normalized = $RelativePath.Replace('\\','/').Trim()
    if ($normalized.StartsWith('./')) { $normalized = $normalized.Substring(2) }
    if ([string]::IsNullOrWhiteSpace($normalized) -or [System.IO.Path]::IsPathRooted($normalized) -or $normalized.StartsWith('/') -or $normalized -match '(^|/)\.\.(/|$)') {
        throw "Unsafe relative path in ${Context}: $RelativePath"
    }
    return $normalized
}

function Copy-PackageAsset([string]$RelativePath, [string]$StageRoot, [System.Collections.Generic.HashSet[string]]$Copied) {
    $safe = Assert-SafeRelativePath $RelativePath 'package asset'
    if (-not $Copied.Add($safe)) { return }
    $src = [System.IO.Path]::GetFullPath((Join-Path $source $safe))
    if (-not $src.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Package asset escaped source root: $safe" }
    if (-not (Test-Path $src -PathType Leaf)) { throw "Package asset is missing: $safe" }
    $item = Get-Item -LiteralPath $src -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Package asset cannot be a symlink/reparse point: $safe" }
    $dest = Join-Path $StageRoot $safe
    New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $src -Destination $dest -Force
}

foreach ($pkg in ($catalog | Sort-Object packageId, version)) {
    if ($pkg.desktop -ne $true) { continue }
    [string]$packageId = $pkg.packageId
    [string]$version = $pkg.version
    [string]$entryRaw = $pkg.entry
    if ($pkg.schema -ne 'swir.app/1.0') { throw "Unsupported package schema for ${packageId}: $($pkg.schema)" }
    if ($packageId -notmatch '^swir\.[a-z0-9][a-z0-9._-]{1,126}$') { throw "Invalid packageId: $packageId" }
    if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$') { throw "Invalid package version for ${packageId}: $version" }
    if ([string]::IsNullOrWhiteSpace([string]$pkg.name) -or [string]::IsNullOrWhiteSpace([string]$pkg.author) -or [string]::IsNullOrWhiteSpace([string]$pkg.type)) {
        throw "Package identity/runtime fields are incomplete for $packageId"
    }
    $identity = "$packageId@$version"
    if (-not $seenIdentity.Add($identity)) { throw "Duplicate Desktop package identity: $identity" }
    $entry = Assert-SafeRelativePath $entryRaw "$identity entry"

    $stage = Join-Path ([System.IO.Path]::GetTempPath()) ("swirapp-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    try {
        $copied = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        Copy-PackageAsset $entry $stage $copied

        # Include reviewed local dependencies directly referenced by the entry document. Remote
        # URLs, data URLs, fragments and absolute paths are deliberately never imported.
        $entryText = Get-Content -LiteralPath (Join-Path $source $entry) -Raw
        $matches = [regex]::Matches($entryText, '(?i)(?:src|href)\s*=\s*["''](\./[^"''?#]+)')
        foreach ($match in $matches) {
            $dep = [string]$match.Groups[1].Value
            if (-not [string]::IsNullOrWhiteSpace($dep)) { Copy-PackageAsset $dep $stage $copied }
        }

        $manifest = [ordered]@{}
        foreach ($prop in $pkg.PSObject.Properties) { $manifest[$prop.Name] = $prop.Value }
        $manifest['entry'] = './' + $entry.Replace('\\','/')
        $manifestPath = Join-Path $stage 'swir-package.json'
        [System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 20), [System.Text.UTF8Encoding]::new($false))

        $safeName = ($packageId -replace '[^A-Za-z0-9._-]', '_')
        $fileName = "$safeName-$version.swirapp"
        if (-not $seenOutput.Add($fileName)) { throw "Duplicate package artifact filename: $fileName" }
        $zipPath = Join-Path $output ($fileName + '.zip')
        $artifactPath = Join-Path $packagesDir $fileName
        Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal -Force
        Move-Item -LiteralPath $zipPath -Destination $artifactPath -Force

        if ($signingRequested) {
            & dotnet $packageSigner sign $artifactPath $PackageSigningKeyId $packagePrivateKey
            if ($LASTEXITCODE -ne 0) { throw "Package signing failed for $identity with exit code $LASTEXITCODE" }
            & dotnet $packageSigner verify $artifactPath $packageTrustRoots
            if ($LASTEXITCODE -ne 0) { throw "Package signature verification failed for $identity with exit code $LASTEXITCODE" }
        }

        $archive = [System.IO.Compression.ZipFile]::OpenRead($artifactPath)
        try {
            $rootManifests = @($archive.Entries | Where-Object { $_.FullName.Replace('\\','/') -ceq 'swir-package.json' })
            if ($rootManifests.Count -ne 1) { throw "Built artifact must contain exactly one root swir-package.json: $identity" }
            $reader = [System.IO.StreamReader]::new($rootManifests[0].Open())
            try { $builtManifest = ($reader.ReadToEnd() | ConvertFrom-Json) } finally { $reader.Dispose() }
            if ($builtManifest.packageId -ne $packageId -or $builtManifest.version -ne $version) { throw "Built package identity mismatch: $identity" }
            $entryInZip = $archive.GetEntry($entry.Replace('\\','/'))
            if ($null -eq $entryInZip) { throw "Built package is missing entry file $entry for $identity" }
            if ($signingRequested) {
                $signatureEntries = @($archive.Entries | Where-Object { $_.FullName.Replace('\\','/') -ceq 'swir-package-signature.json' })
                if ($signatureEntries.Count -ne 1) { throw "Signed package must contain exactly one swir-package-signature.json: $identity" }
            }
        } finally { $archive.Dispose() }

        # The signed bytes are authoritative. Catalog hashes are calculated only after
        # the embedded signature has been written and independently verified.
        $sha = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $artifactRecords.Add([ordered]@{
            packageId = $packageId
            version = $version
            desktop = [ordered]@{
                sha256 = $sha
                url = "packages/$fileName"
            }
        })
    }
    finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$expectedDesktopCount = @($catalog | Where-Object { $_.desktop -eq $true }).Count
if ($artifactRecords.Count -eq 0) { throw 'No Desktop-installable packages were produced.' }
if ($artifactRecords.Count -ne $expectedDesktopCount) { throw "Desktop package artifact count mismatch: built $($artifactRecords.Count), expected $expectedDesktopCount" }

$commit = (& git -C $source rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-fA-F]{40}$') { throw 'Could not resolve source commit for artifact map.' }
$map = [ordered]@{
    schema = 'swir.catalog-artifacts/1.0'
    generatedFrom = $commit.ToLowerInvariant()
    artifacts = @($artifactRecords)
}
$mapPath = Join-Path $output 'catalog-artifacts.json'
[System.IO.File]::WriteAllText($mapPath, ($map | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))

$mode = if ($signingRequested) { "signed:$PackageSigningKeyId" } else { 'unsigned-compatible' }
Write-Host "Built $($artifactRecords.Count) reviewed Desktop Store package artifacts ($mode)."
Write-Host "Artifact map: $mapPath"
Write-Host "Package directory: $packagesDir"
if ($signingRequested) { Write-Host "Package trust roots: $packageTrustRoots" }