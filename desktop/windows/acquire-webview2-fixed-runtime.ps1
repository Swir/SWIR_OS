param(
    [string]$SourceUrl = '',
    [string]$ExpectedSha256 = '',
    [string]$ExpectedVersion = '',
    [string]$DestinationDir = '',
    [switch]$PolicyOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PolicyContract = 'swir.webview2-fixed-source-policy/0.1'
$ProvenanceContract = 'swir.webview2-provenance/0.1'
$Architecture = 'x64'

function Assert-OfficialSourceUrl([string]$Value) {
    $uri = $null
    if (-not [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$uri)) { throw 'WebView2 source URL must be absolute.' }
    if ($uri.Scheme -ne 'https') { throw 'WebView2 source URL must use HTTPS.' }
    $host = $uri.DnsSafeHost.ToLowerInvariant()
    if (-not ($host -eq 'microsoft.com' -or $host.EndsWith('.microsoft.com'))) {
        throw "WebView2 source host is not an approved Microsoft host: $host"
    }
    return $uri
}

function Assert-Sha256([string]$Value) {
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[a-f0-9]{64}$') { throw 'Expected WebView2 SHA-256 must be exactly 64 hex characters.' }
    return $normalized
}

function Assert-Version([string]$Value) {
    $normalized = $Value.Trim()
    if ($normalized -notmatch '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$') { throw 'Expected WebView2 version must use four numeric components.' }
    return $normalized
}

$source = Assert-OfficialSourceUrl $SourceUrl
$expectedHash = Assert-Sha256 $ExpectedSha256
$expectedVersion = Assert-Version $ExpectedVersion

if ($PolicyOnly) {
    [ordered]@{
        contract = $PolicyContract
        approved = $true
        source = $source.AbsoluteUri
        version = $expectedVersion
        architecture = $Architecture
        sha256 = $expectedHash
        requireAuthenticode = $true
        requireMicrosoftSigner = $true
        userDownloadRequired = $false
    } | ConvertTo-Json -Compress
    return
}

if ([string]::IsNullOrWhiteSpace($DestinationDir)) { throw 'DestinationDir is required outside PolicyOnly mode.' }
if ($env:OS -ne 'Windows_NT') { throw 'WebView2 Fixed Version acquisition must run on Windows.' }

$destination = [System.IO.Path]::GetFullPath($DestinationDir)
if (Test-Path $destination) {
    if (-not (Test-Path $destination -PathType Container)) { throw "Destination is not a directory: $destination" }
    if (@(Get-ChildItem -LiteralPath $destination -Force).Count -ne 0) { throw "Destination must be empty: $destination" }
} else {
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("swir-webview2-" + [Guid]::NewGuid().ToString('N'))
$archive = Join-Path $tempRoot 'Microsoft.WebView2.FixedVersionRuntime.x64.cab'
$extract = Join-Path $tempRoot 'expanded'
New-Item -ItemType Directory -Path $extract -Force | Out-Null

try {
    Write-Host "Downloading pinned WebView2 Fixed Version $expectedVersion from approved Microsoft source..."
    Invoke-WebRequest -Uri $source.AbsoluteUri -OutFile $archive -UseBasicParsing -MaximumRedirection 5
    if (-not (Test-Path $archive -PathType Leaf) -or (Get-Item $archive).Length -lt 50MB) {
        throw 'Downloaded WebView2 package is missing or implausibly small.'
    }

    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) { throw "WebView2 package SHA-256 mismatch. Expected $expectedHash, got $actualHash." }

    $header = [System.IO.File]::ReadAllBytes($archive)[0..3]
    $magic = [System.Text.Encoding]::ASCII.GetString($header)
    if ($magic -ne 'MSCF') { throw 'WebView2 Fixed Version package is not a CAB archive.' }

    $expandExe = Join-Path $env:SystemRoot 'System32\expand.exe'
    if (-not (Test-Path $expandExe -PathType Leaf)) { throw 'Windows expand.exe is unavailable.' }
    & $expandExe $archive '-F:*' $extract | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "WebView2 CAB extraction failed with exit code $LASTEXITCODE." }

    $candidates = @(Get-ChildItem -LiteralPath $extract -Recurse -Filter 'msedgewebview2.exe' -File)
    if ($candidates.Count -lt 1) { throw 'Extracted WebView2 package does not contain msedgewebview2.exe.' }
    $matching = @($candidates | Where-Object {
        $fv = [string]$_.VersionInfo.FileVersion
        $pv = [string]$_.VersionInfo.ProductVersion
        $fv -eq $expectedVersion -or $pv -eq $expectedVersion -or $fv.StartsWith("$expectedVersion ") -or $pv.StartsWith("$expectedVersion ")
    })
    if ($matching.Count -ne 1) { throw "Expected exactly one WebView2 executable matching version $expectedVersion; found $($matching.Count)." }
    $exe = $matching[0]

    $signature = Get-AuthenticodeSignature -LiteralPath $exe.FullName
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or -not $signature.SignerCertificate) {
        throw "WebView2 executable Authenticode signature is not valid: $($signature.Status)."
    }
    $subject = [string]$signature.SignerCertificate.Subject
    if ($subject -notmatch '(?i)(CN|O)=Microsoft Corporation') { throw "WebView2 executable signer is not Microsoft Corporation: $subject" }

    foreach ($required in @('msedge.dll','icudtl.dat')) {
        if (-not (Test-Path (Join-Path $exe.Directory.FullName $required) -PathType Leaf)) { throw "Extracted WebView2 runtime is missing $required." }
    }

    Copy-Item -Path (Join-Path $exe.Directory.FullName '*') -Destination $destination -Recurse -Force
    $publishedExe = Join-Path $destination 'msedgewebview2.exe'
    if (-not (Test-Path $publishedExe -PathType Leaf)) { throw 'Staged WebView2 runtime is missing its executable.' }
    $publishedExeHash = (Get-FileHash -LiteralPath $publishedExe -Algorithm SHA256).Hash.ToLowerInvariant()

    $provenance = [ordered]@{
        schema = $ProvenanceContract
        sourcePolicy = $PolicyContract
        sourceUrl = $source.AbsoluteUri
        archiveSha256 = $actualHash
        version = $expectedVersion
        architecture = $Architecture
        executable = [ordered]@{
            path = 'msedgewebview2.exe'
            sha256 = $publishedExeHash
            authenticode = 'valid'
            signerSubject = $subject
            signerThumbprint = [string]$signature.SignerCertificate.Thumbprint
        }
        userDownloadRequired = $false
    }
    [System.IO.File]::WriteAllText((Join-Path $destination '.swir-webview2-provenance.json'), ($provenance | ConvertTo-Json -Depth 5 -Compress), [System.Text.UTF8Encoding]::new($false))
    Write-Host "Verified WebView2 Fixed Version runtime staged: $destination"
    Write-Host "Version: $expectedVersion"
    Write-Host "Archive SHA-256: $actualHash"
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
