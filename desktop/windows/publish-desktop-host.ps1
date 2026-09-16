[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PublishDir,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseVersion,
    [Parameter(Mandatory = $true)]
    [ValidateSet('preview', 'stable')]
    [string]$Channel,
    [string]$ProjectFile = 'SWIR.Desktop.Host.csproj',
    [string]$ProgramFile = 'Program.cs',
    [string]$SourceCommit = $env:GITHUB_SHA,
    [string]$WebView2RuntimeDir = $env:SWIR_WEBVIEW2_FIXED_RUNTIME_DIR,
    [string]$WebView2LockFile = '',
    [string]$AuthenticodePfxPath = $env:SWIR_AUTHENTICODE_PFX_PATH,
    [string]$AuthenticodeExpectedThumbprint = $env:SWIR_AUTHENTICODE_CERT_THUMBPRINT,
    [string]$AuthenticodeTimestampServer = $env:SWIR_AUTHENTICODE_TIMESTAMP_URL
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$parsedVersion = $null
if (-not [Version]::TryParse($ReleaseVersion, [ref]$parsedVersion) -or $parsedVersion.Build -lt 0) { throw "ReleaseVersion must be a three-part numeric version such as 0.5.7. Got: $ReleaseVersion" }
if ($parsedVersion -le [Version]'0.0.0') { throw 'ReleaseVersion must be greater than 0.0.0.' }
$projectPath = (Resolve-Path -LiteralPath $ProjectFile).Path
$programPath = (Resolve-Path -LiteralPath $ProgramFile).Path
$publishPath = [System.IO.Path]::GetFullPath($PublishDir)
$hostVersion = "$ReleaseVersion-$Channel"
$runtimeIdentifier = 'win-x64'
$targetFramework = 'net8.0-windows'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$autoAcquiredRoot = $null
$authenticodeRequired = $env:SWIR_AUTHENTICODE_REQUIRED -eq 'true'
$hostAuthenticode = $null

function Get-SwirSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-SwirSha256([string]$Value) {
    return -not [string]::IsNullOrWhiteSpace($Value) -and $Value -match '^[a-fA-F0-9]{64}$'
}

function Assert-MicrosoftHttpsUrl([string]$Value) {
    $uri = $null
    if (-not [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$uri)) { throw 'WebView2 provenance source URL must be absolute.' }
    if ($uri.Scheme -ne 'https') { throw 'WebView2 provenance source URL must use HTTPS.' }
    $hostName = $uri.DnsSafeHost.ToLowerInvariant()
    if (-not ($hostName -eq 'microsoft.com' -or $hostName.EndsWith('.microsoft.com'))) {
        throw "WebView2 provenance source host is not an approved Microsoft host: $hostName"
    }
    return $uri.AbsoluteUri
}

# Contract workflows may synthesize only an executable-shaped fixture. Real release packaging instead
# auto-acquires the repository-pinned Microsoft Fixed Version Runtime when no explicit directory is supplied.
$ciFixtureWorkflows = @('Desktop Release Contract', 'Desktop Release Candidate Trust Contract', 'Desktop Authenticode Contract')
if ([string]::IsNullOrWhiteSpace($WebView2RuntimeDir) -and $env:GITHUB_ACTIONS -eq 'true' -and $env:GITHUB_WORKFLOW -in $ciFixtureWorkflows) {
    $fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('swir-webview2-contract-fixture-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
    $fixtureSource = Join-Path $env:SystemRoot 'System32\where.exe'
    if (-not (Test-Path -LiteralPath $fixtureSource -PathType Leaf)) { throw "Could not create CI WebView2 fixture; missing system executable: $fixtureSource" }
    Copy-Item -LiteralPath $fixtureSource -Destination (Join-Path $fixtureRoot 'msedgewebview2.exe') -Force
    [System.IO.File]::WriteAllText((Join-Path $fixtureRoot '.swir-ci-contract-fixture'), 'packaging-topology-only', $utf8NoBom)
    $WebView2RuntimeDir = $fixtureRoot
    Write-Host "Using isolated WebView2 packaging fixture for contract workflow: $env:GITHUB_WORKFLOW"
}

if ([string]::IsNullOrWhiteSpace($WebView2RuntimeDir)) {
    if ([string]::IsNullOrWhiteSpace($WebView2LockFile)) { $WebView2LockFile = Join-Path $PSScriptRoot 'webview2-fixed-runtime.lock.json' }
    $lockPath = (Resolve-Path -LiteralPath $WebView2LockFile -ErrorAction Stop).Path
    $lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
    if ($lock.schema -ne 'swir.webview2-fixed-runtime-lock/0.1') { throw 'WebView2 lock schema mismatch.' }
    if ($lock.architecture -ne 'x64') { throw 'Desktop win-x64 release requires an x64 WebView2 lock.' }
    if ($lock.version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$') { throw 'WebView2 lock version is invalid.' }
    if (-not (Test-SwirSha256 ([string]$lock.sha256))) { throw 'WebView2 lock SHA-256 is invalid.' }
    if ($lock.userDownloadRequired -ne $false -or $lock.distribution -ne 'fixed-version-bundled') { throw 'WebView2 lock must describe a bundled no-user-download Fixed Version Runtime.' }
    [void](Assert-MicrosoftHttpsUrl ([string]$lock.sourceUrl))

    $acquireScript = Join-Path $PSScriptRoot 'acquire-webview2-fixed-runtime.ps1'
    if (-not (Test-Path -LiteralPath $acquireScript -PathType Leaf)) { throw "WebView2 acquisition script is missing: $acquireScript" }
    $autoAcquiredRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('swir-webview2-fixed-' + [guid]::NewGuid().ToString('N'))
    & $acquireScript -SourceUrl ([string]$lock.sourceUrl) -ExpectedSha256 ([string]$lock.sha256) -ExpectedVersion ([string]$lock.version) -DestinationDir $autoAcquiredRoot
    if ($LASTEXITCODE -ne 0) { throw "WebView2 acquisition failed with exit code $LASTEXITCODE." }
    $WebView2RuntimeDir = $autoAcquiredRoot
    Write-Host "Auto-acquired repository-pinned WebView2 Fixed Runtime $($lock.version)."
}

$webView2Source = [System.IO.Path]::GetFullPath($WebView2RuntimeDir)
if (-not (Test-Path -LiteralPath $webView2Source -PathType Container)) { throw "WebView2 Fixed Runtime directory does not exist: $webView2Source" }
$webView2Exe = Join-Path $webView2Source 'msedgewebview2.exe'
if (-not (Test-Path -LiteralPath $webView2Exe -PathType Leaf)) { throw "WebView2 Fixed Runtime is incomplete; missing: $webView2Exe" }
$isContractFixture = Test-Path -LiteralPath (Join-Path $webView2Source '.swir-ci-contract-fixture') -PathType Leaf
$sourceProvenancePath = Join-Path $webView2Source '.swir-webview2-provenance.json'

if (-not $isContractFixture) {
    if (-not (Test-Path -LiteralPath $sourceProvenancePath -PathType Leaf)) { throw 'Real WebView2 Fixed Runtime must include acquisition provenance.' }
    $sourceProvenance = Get-Content -LiteralPath $sourceProvenancePath -Raw | ConvertFrom-Json
    if ($sourceProvenance.schema -ne 'swir.webview2-provenance/0.1' -or $sourceProvenance.sourcePolicy -ne 'swir.webview2-fixed-source-policy/0.1') { throw 'WebView2 provenance contract mismatch.' }
    if ($sourceProvenance.architecture -ne 'x64' -or $sourceProvenance.userDownloadRequired -ne $false) { throw 'WebView2 provenance architecture/download policy mismatch.' }
    [void](Assert-MicrosoftHttpsUrl ([string]$sourceProvenance.sourceUrl))
    if (-not (Test-SwirSha256 ([string]$sourceProvenance.archiveSha256))) { throw 'WebView2 provenance archive SHA-256 is invalid.' }
    if ($sourceProvenance.executable.path -ne 'msedgewebview2.exe' -or -not (Test-SwirSha256 ([string]$sourceProvenance.executable.sha256))) { throw 'WebView2 provenance executable identity is invalid.' }
    if ($sourceProvenance.executable.authenticode -ne 'valid' -or ([string]$sourceProvenance.executable.signerSubject) -notmatch '(?i)(CN|O)=Microsoft Corporation') { throw 'WebView2 provenance does not prove a valid Microsoft Authenticode signer.' }
    if ([string]$sourceProvenance.executable.sha256 -ne (Get-SwirSha256 $webView2Exe)) { throw 'WebView2 provenance executable SHA-256 does not match source bytes.' }
}

$sourceBytes = [System.IO.File]::ReadAllBytes($programPath)
$sourceText = [System.Text.Encoding]::UTF8.GetString($sourceBytes)
$pattern = "version: '(?<version>[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?)'"
$matches = [System.Text.RegularExpressions.Regex]::Matches($sourceText, $pattern)
if ($matches.Count -ne 2) { throw "Expected exactly two Desktop Host version literals in Program.cs, found $($matches.Count). Refusing an ambiguous release build." }
$patchedText = [System.Text.RegularExpressions.Regex]::Replace($sourceText, $pattern, "version: '$hostVersion'")
$patchedMatches = [System.Text.RegularExpressions.Regex]::Matches($patchedText, [regex]::Escape("version: '$hostVersion'"))
if ($patchedMatches.Count -ne 2) { throw "Desktop Host version injection did not produce exactly two $hostVersion literals." }

try {
    [System.IO.File]::WriteAllText($programPath, $patchedText, $utf8NoBom)
    if (Test-Path -LiteralPath $publishPath) { Remove-Item -LiteralPath $publishPath -Recurse -Force }
    New-Item -ItemType Directory -Path $publishPath -Force | Out-Null

    & dotnet publish $projectPath `
        --configuration Release `
        --runtime $runtimeIdentifier `
        --self-contained true `
        --output $publishPath `
        /p:SWIRBundledRelease=true `
        /p:PublishSingleFile=true `
        /p:IncludeNativeLibrariesForSelfExtract=true `
        /p:PublishTrimmed=false
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed with exit code $LASTEXITCODE" }
} finally {
    [System.IO.File]::WriteAllBytes($programPath, $sourceBytes)
}

$hostExe = Join-Path $publishPath 'SWIR.Desktop.Host.exe'
if (-not (Test-Path -LiteralPath $hostExe -PathType Leaf)) { throw "Desktop Host publish output is missing: $hostExe" }

if (-not [string]::IsNullOrWhiteSpace($AuthenticodePfxPath)) {
    $signScript = Join-Path $PSScriptRoot 'sign-desktop-artifact.ps1'
    if (-not (Test-Path -LiteralPath $signScript -PathType Leaf)) { throw "Authenticode signing script is missing: $signScript" }
    $json = & $signScript -FilePath $hostExe -PfxPath $AuthenticodePfxPath -ExpectedThumbprint $AuthenticodeExpectedThumbprint -TimestampServer $AuthenticodeTimestampServer
    if ($LASTEXITCODE -ne 0) { throw "Desktop Host Authenticode signing failed with exit code $LASTEXITCODE." }
    $hostAuthenticode = $json | ConvertFrom-Json
    if ($hostAuthenticode.schema -ne 'swir.desktop-authenticode/0.1' -or $hostAuthenticode.status -ne 'valid') { throw 'Desktop Host Authenticode result is invalid.' }
} elseif ($authenticodeRequired) {
    throw 'SWIR_AUTHENTICODE_REQUIRED=true but no Authenticode PFX path was supplied.'
}

$bundledWebView2 = Join-Path $publishPath 'WebView2FixedRuntime'
if (Test-Path -LiteralPath $bundledWebView2) { Remove-Item -LiteralPath $bundledWebView2 -Recurse -Force }
New-Item -ItemType Directory -Path $bundledWebView2 -Force | Out-Null
Copy-Item -Path (Join-Path $webView2Source '*') -Destination $bundledWebView2 -Recurse -Force
$bundledWebView2Exe = Join-Path $bundledWebView2 'msedgewebview2.exe'
if (-not (Test-Path -LiteralPath $bundledWebView2Exe -PathType Leaf)) { throw 'Bundled WebView2 runtime copy is incomplete.' }
$bundledProvenancePath = Join-Path $bundledWebView2 '.swir-webview2-provenance.json'

if ($isContractFixture) {
    $fixtureProvenance = [ordered]@{
        schema = 'swir.webview2-provenance/0.1'
        sourcePolicy = 'ci-contract-fixture'
        sourceUrl = 'fixture://windows-system32/where.exe'
        archiveSha256 = ('0' * 64)
        version = 'fixture-or-unknown'
        architecture = 'x64'
        executable = [ordered]@{
            path = 'msedgewebview2.exe'
            sha256 = Get-SwirSha256 $bundledWebView2Exe
            authenticode = 'fixture'
            signerSubject = 'CI contract fixture only'
            signerThumbprint = ''
        }
        userDownloadRequired = $false
        contractFixture = $true
    }
    [System.IO.File]::WriteAllText($bundledProvenancePath, ($fixtureProvenance | ConvertTo-Json -Depth 6 -Compress), $utf8NoBom)
}
if (-not (Test-Path -LiteralPath $bundledProvenancePath -PathType Leaf)) { throw 'Bundled WebView2 runtime provenance is missing.' }
$bundledProvenance = Get-Content -LiteralPath $bundledProvenancePath -Raw | ConvertFrom-Json
if ($bundledProvenance.schema -ne 'swir.webview2-provenance/0.1' -or $bundledProvenance.userDownloadRequired -ne $false) { throw 'Bundled WebView2 provenance contract is invalid.' }
if ([string]$bundledProvenance.executable.sha256 -ne (Get-SwirSha256 $bundledWebView2Exe)) { throw 'Bundled WebView2 provenance SHA-256 does not match copied runtime.' }

$commit = if ([string]::IsNullOrWhiteSpace($SourceCommit)) { 'local-unpinned' } else { $SourceCommit.Trim().ToLowerInvariant() }
if ($commit -ne 'local-unpinned' -and $commit -notmatch '^[0-9a-f]{40}$') { throw "SourceCommit must be a 40-character Git SHA when supplied. Got: $SourceCommit" }
$webView2Version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($webView2Exe).FileVersion
if ([string]::IsNullOrWhiteSpace($webView2Version)) { $webView2Version = [string]$bundledProvenance.version }
$hostInfo = Get-Item -LiteralPath $hostExe
$webViewInfo = Get-Item -LiteralPath $bundledWebView2Exe
$provenanceInfo = Get-Item -LiteralPath $bundledProvenancePath

$authenticodeManifest = [ordered]@{
    contract = 'swir.desktop-authenticode/0.1'
    required = [bool]$authenticodeRequired
    signed = $null -ne $hostAuthenticode
    status = if ($null -eq $hostAuthenticode) { 'unsigned' } else { [string]$hostAuthenticode.status }
    signerThumbprint = if ($null -eq $hostAuthenticode) { '' } else { [string]$hostAuthenticode.signerThumbprint }
    signerSubject = if ($null -eq $hostAuthenticode) { '' } else { [string]$hostAuthenticode.signerSubject }
    timestamped = if ($null -eq $hostAuthenticode) { $false } else { [bool]$hostAuthenticode.timestamped }
}

$manifest = [ordered]@{
    schema = 'swir.desktop-host-build/0.1'
    releaseVersion = $ReleaseVersion
    channel = $Channel
    hostVersion = $hostVersion
    sourceCommit = $commit
    entryPoint = 'SWIR.Desktop.Host.exe'
    authenticode = $authenticodeManifest
    deployment = [ordered]@{
        contract = 'swir.desktop-bundled-runtime/0.1'
        mode = 'self-contained-bundled'
        runtimeIdentifier = $runtimeIdentifier
        targetFramework = $targetFramework
        selfContained = $true
        singleFile = $true
        trimmed = $false
        userPrerequisiteDownloadsRequired = $false
        dotnet = [ordered]@{
            mode = 'self-contained'
            bundled = $true
            major = 8
        }
        webView2 = [ordered]@{
            mode = 'fixed-version-bundled'
            bundled = $true
            relativePath = 'WebView2FixedRuntime'
            executable = 'msedgewebview2.exe'
            version = $webView2Version
            sourcePolicy = [string]$bundledProvenance.sourcePolicy
            sourceUrl = [string]$bundledProvenance.sourceUrl
            archiveSha256 = [string]$bundledProvenance.archiveSha256
            provenanceFile = '.swir-webview2-provenance.json'
            provenanceContract = 'swir.webview2-provenance/0.1'
            contractFixture = [bool]$isContractFixture
            windows10AppContainerAclPolicy = 'host-ensures-read-execute'
        }
    }
    integrity = [ordered]@{
        contract = 'swir.desktop-bundled-integrity/0.1'
        algorithm = 'SHA-256'
        entryPoint = [ordered]@{
            path = 'SWIR.Desktop.Host.exe'
            sha256 = Get-SwirSha256 $hostExe
            size = [long]$hostInfo.Length
        }
        webView2Executable = [ordered]@{
            path = 'WebView2FixedRuntime/msedgewebview2.exe'
            sha256 = Get-SwirSha256 $bundledWebView2Exe
            size = [long]$webViewInfo.Length
        }
        webView2Provenance = [ordered]@{
            path = 'WebView2FixedRuntime/.swir-webview2-provenance.json'
            sha256 = Get-SwirSha256 $bundledProvenancePath
            size = [long]$provenanceInfo.Length
        }
    }
}
$manifestPath = Join-Path $publishPath 'desktop-host-build.json'
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 10), $utf8NoBom)

$restoredBytes = [System.IO.File]::ReadAllBytes($programPath)
if (-not [System.Linq.Enumerable]::SequenceEqual([byte[]]$sourceBytes, [byte[]]$restoredBytes)) { throw 'Program.cs was not restored byte-for-byte after Desktop Host publish.' }

if ($autoAcquiredRoot -and (Test-Path -LiteralPath $autoAcquiredRoot -PathType Container)) {
    Remove-Item -LiteralPath $autoAcquiredRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "SWIR Desktop Host published as $hostVersion ($runtimeIdentifier, self-contained .NET + bundled WebView2 Fixed Runtime)"
Write-Host "Authenticode: $($authenticodeManifest.status)"
Write-Host "Bundled integrity: SHA-256 host + WebView2 executable + acquisition provenance"
Write-Host "Build manifest: $manifestPath"
