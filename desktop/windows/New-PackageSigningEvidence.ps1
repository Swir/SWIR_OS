param(
    [Parameter(Mandatory = $true)]
    [string]$StoreDir,

    [Parameter(Mandatory = $true)]
    [string]$TrustRootsPath,

    [Parameter(Mandatory = $true)]
    [string]$SignerDll,

    [Parameter(Mandatory = $true)]
    [string]$SourceCommit,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedKeyId,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [ValidateSet('contract','production')]
    [string]$EvidenceKind = 'contract',

    [string]$GitHubRepository = '',
    [string]$GitHubRunId = '',
    [string]$GitHubRunAttempt = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Sha256Hex([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([Convert]::ToHexString($sha.ComputeHash($Bytes))).ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-SafePackageRelativePath([string]$RelativePath) {
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or $RelativePath -notmatch '^packages/[A-Za-z0-9._-]+\.swirapp$') {
        throw "Unsafe signed package artifact path: $RelativePath"
    }
    return $RelativePath
}

$store = [System.IO.Path]::GetFullPath($StoreDir)
$trustPath = [System.IO.Path]::GetFullPath($TrustRootsPath)
$signer = [System.IO.Path]::GetFullPath($SignerDll)
$output = [System.IO.Path]::GetFullPath($OutputPath)

if (-not (Test-Path $store -PathType Container)) { throw "Signed Store directory is missing: $store" }
if (-not (Test-Path $trustPath -PathType Leaf)) { throw "Package trust-root file is missing: $trustPath" }
if (-not (Test-Path $signer -PathType Leaf)) { throw "Package signature verifier is missing: $signer" }
if ($SourceCommit -notmatch '^[0-9a-fA-F]{40}$') { throw 'SourceCommit must be an exact 40-hex Git commit.' }
$sourceCommitNormalized = $SourceCommit.ToLowerInvariant()
if ($ExpectedKeyId -notmatch '^[A-Za-z0-9._-]{1,128}$') { throw 'ExpectedKeyId is invalid.' }
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw '.NET is required for independent package signature verification.' }

$trustRaw = [System.IO.File]::ReadAllBytes($trustPath)
$trust = [System.Text.Encoding]::UTF8.GetString($trustRaw) | ConvertFrom-Json
if ($trust.schema -ne 'swir.package-trust-roots/1.0' -or $trust.requireSignedPackages -ne $true) {
    throw 'Package trust-root policy must be fail-closed.'
}
$roots = @($trust.roots)
if ($roots.Count -ne 1) { throw "Exactly one package signing trust root is required for release evidence; found $($roots.Count)." }
$root = $roots[0]
if ([string]$root.keyId -ne $ExpectedKeyId) { throw 'Package trust-root keyId does not match ExpectedKeyId.' }
if ([string]$root.algorithm -ne 'Ed25519' -or [string]$root.format -ne 'raw' -or $root.enabled -ne $true) {
    throw 'Package trust root must be enabled raw Ed25519.'
}
$scope = @($root.scope)
if ($scope.Count -ne 1 -or [string]$scope[0] -ne 'package:swirapp') {
    throw 'Package trust root scope must be exactly package:swirapp.'
}
try {
    $publicKey = [Convert]::FromBase64String(([string]$root.publicKey).Trim())
}
catch {
    throw 'Package trust-root public key is not canonical base64.'
}
if ($publicKey.Length -ne 32) { throw 'Package trust-root Ed25519 public key must be exactly 32 bytes.' }
$canonicalPublicKey = [Convert]::ToBase64String($publicKey)
if ($canonicalPublicKey -cne ([string]$root.publicKey).Trim()) { throw 'Package trust-root public key must use canonical base64.' }
$publicKeySha256 = Get-Sha256Hex $publicKey
$trustPolicySha256 = Get-Sha256Hex $trustRaw

$mapPath = Join-Path $store 'catalog-artifacts.json'
if (-not (Test-Path $mapPath -PathType Leaf)) { throw "Catalog artifact map is missing: $mapPath" }
$map = Get-Content -LiteralPath $mapPath -Raw | ConvertFrom-Json
if ($map.schema -ne 'swir.catalog-artifacts/1.0') { throw 'Catalog artifact map schema is invalid.' }
if ([string]$map.generatedFrom -ne $sourceCommitNormalized) { throw 'Catalog artifact map source commit does not match SourceCommit.' }
$artifacts = @($map.artifacts)
if ($artifacts.Count -lt 1) { throw 'Signed package evidence requires at least one reviewed Desktop package.' }

$storePrefix = $store.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
$seenIdentity = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$seenPath = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$packageEvidence = [System.Collections.Generic.List[object]]::new()

foreach ($artifact in ($artifacts | Sort-Object packageId, version)) {
    [string]$packageId = $artifact.packageId
    [string]$version = $artifact.version
    if ([string]::IsNullOrWhiteSpace($packageId) -or [string]::IsNullOrWhiteSpace($version)) {
        throw 'Catalog artifact map contains an incomplete package identity.'
    }
    $identity = "$packageId@$version"
    if (-not $seenIdentity.Add($identity)) { throw "Duplicate package identity in artifact map: $identity" }

    $relative = Assert-SafePackageRelativePath ([string]$artifact.desktop.url)
    if (-not $seenPath.Add($relative)) { throw "Duplicate package artifact path in artifact map: $relative" }
    $artifactPath = [System.IO.Path]::GetFullPath((Join-Path $store $relative))
    if (-not $artifactPath.StartsWith($storePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Package artifact escaped Store root: $relative"
    }
    if (-not (Test-Path $artifactPath -PathType Leaf)) { throw "Signed package artifact is missing: $relative" }

    $actualSha = Get-FileSha256 $artifactPath
    $mappedSha = ([string]$artifact.desktop.sha256).ToLowerInvariant()
    if ($mappedSha -notmatch '^[0-9a-f]{64}$' -or $actualSha -ne $mappedSha) {
        throw "Signed package artifact SHA-256 mismatch: $relative"
    }
    $size = (Get-Item -LiteralPath $artifactPath).Length
    if ($size -le 0) { throw "Signed package artifact is empty: $relative" }

    $verifyOutput = @(& dotnet $signer verify $artifactPath $trustPath 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Independent embedded package signature verification failed for $identity: $($verifyOutput -join ' ')"
    }
    $jsonLine = $verifyOutput | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Last 1
    try { $verified = ([string]$jsonLine | ConvertFrom-Json) }
    catch { throw "Package verifier did not emit valid JSON provenance for $identity." }
    if ($verified.verified -ne $true -or [string]$verified.KeyId -ne $ExpectedKeyId -or [string]$verified.PackageId -ne $packageId -or [string]$verified.Version -ne $version) {
        throw "Verified package provenance does not match expected identity/key for $identity."
    }
    $contentSha = ([string]$verified.ContentSha256).ToLowerInvariant()
    if ($contentSha -notmatch '^[0-9a-f]{64}$') { throw "Verifier content SHA-256 is invalid for $identity." }

    $packageEvidence.Add([ordered]@{
        packageId = $packageId
        version = $version
        path = $relative
        size = $size
        artifactSha256 = $actualSha
        contentSha256 = $contentSha
        keyId = $ExpectedKeyId
        signatureVerified = $true
    })
}

$outputDirectory = Split-Path $output -Parent
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) { New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null }
$evidence = [ordered]@{
    schema = 'swir.package-signing-evidence/1.0'
    evidenceKind = $EvidenceKind
    sourceCommit = $sourceCommitNormalized
    keyId = $ExpectedKeyId
    algorithm = 'Ed25519'
    generatedAt = [DateTimeOffset]::UtcNow.ToString('O')
    trustRoot = [ordered]@{
        policySha256 = $trustPolicySha256
        publicKeySha256 = $publicKeySha256
        scope = 'package:swirapp'
        requireSignedPackages = $true
    }
    builder = [ordered]@{
        repository = $GitHubRepository
        runId = $GitHubRunId
        runAttempt = $GitHubRunAttempt
    }
    packageCount = $packageEvidence.Count
    packages = @($packageEvidence)
}

[System.IO.File]::WriteAllText(
    $output,
    ($evidence | ConvertTo-Json -Depth 12) + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false))

Write-Host "Package signing evidence written: $output"
Write-Host "Source commit: $sourceCommitNormalized"
Write-Host "Package key id: $ExpectedKeyId"
Write-Host "Public trust-root SHA-256: $publicKeySha256"
Write-Host "Verified package count: $($packageEvidence.Count)"
