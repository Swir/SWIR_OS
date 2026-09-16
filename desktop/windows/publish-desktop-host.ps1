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
    [string]$WebView2RuntimeDir = $env:SWIR_WEBVIEW2_FIXED_RUNTIME_DIR
)
$ErrorActionPreference = 'Stop'
$parsedVersion = $null
if (-not [Version]::TryParse($ReleaseVersion, [ref]$parsedVersion) -or $parsedVersion.Build -lt 0) { throw "ReleaseVersion must be a three-part numeric version such as 0.5.7. Got: $ReleaseVersion" }
if ($parsedVersion -le [Version]'0.0.0') { throw 'ReleaseVersion must be greater than 0.0.0.' }
$projectPath = (Resolve-Path -LiteralPath $ProjectFile).Path
$programPath = (Resolve-Path -LiteralPath $ProgramFile).Path
$publishPath = [System.IO.Path]::GetFullPath($PublishDir)
$hostVersion = "$ReleaseVersion-$Channel"
$runtimeIdentifier = 'win-x64'
$targetFramework = 'net8.0-windows'

# Production packaging is fail-closed: a real official Microsoft Fixed Version Runtime must be supplied.
# Only named CI contract workflows may synthesize an executable-shaped fixture, because those jobs verify
# package topology and trust/update lifecycles rather than the Microsoft browser runtime itself.
$ciFixtureWorkflows = @('Desktop Release Contract', 'Desktop Release Candidate Trust Contract')
if ([string]::IsNullOrWhiteSpace($WebView2RuntimeDir) -and $env:GITHUB_ACTIONS -eq 'true' -and $env:GITHUB_WORKFLOW -in $ciFixtureWorkflows) {
    $fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('swir-webview2-contract-fixture-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
    $fixtureSource = Join-Path $env:SystemRoot 'System32\where.exe'
    if (-not (Test-Path -LiteralPath $fixtureSource -PathType Leaf)) { throw "Could not create CI WebView2 fixture; missing system executable: $fixtureSource" }
    Copy-Item -LiteralPath $fixtureSource -Destination (Join-Path $fixtureRoot 'msedgewebview2.exe') -Force
    [System.IO.File]::WriteAllText((Join-Path $fixtureRoot '.swir-ci-contract-fixture'), 'packaging-topology-only')
    $WebView2RuntimeDir = $fixtureRoot
    Write-Host "Using isolated WebView2 packaging fixture for contract workflow: $env:GITHUB_WORKFLOW"
}

if ([string]::IsNullOrWhiteSpace($WebView2RuntimeDir)) {
    throw 'A WebView2 Fixed Version Runtime directory is required. Set -WebView2RuntimeDir or SWIR_WEBVIEW2_FIXED_RUNTIME_DIR; Desktop releases must not require users to install WebView2 separately.'
}
$webView2Source = [System.IO.Path]::GetFullPath($WebView2RuntimeDir)
if (-not (Test-Path -LiteralPath $webView2Source -PathType Container)) { throw "WebView2 Fixed Runtime directory does not exist: $webView2Source" }
$webView2Exe = Join-Path $webView2Source 'msedgewebview2.exe'
if (-not (Test-Path -LiteralPath $webView2Exe -PathType Leaf)) { throw "WebView2 Fixed Runtime is incomplete; missing: $webView2Exe" }

$sourceBytes = [System.IO.File]::ReadAllBytes($programPath)
$sourceText = [System.Text.Encoding]::UTF8.GetString($sourceBytes)
$pattern = "version: '(?<version>[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?)'"
$matches = [System.Text.RegularExpressions.Regex]::Matches($sourceText, $pattern)
if ($matches.Count -ne 2) { throw "Expected exactly two Desktop Host version literals in Program.cs, found $($matches.Count). Refusing an ambiguous release build." }
$patchedText = [System.Text.RegularExpressions.Regex]::Replace($sourceText, $pattern, "version: '$hostVersion'")
$patchedMatches = [System.Text.RegularExpressions.Regex]::Matches($patchedText, [regex]::Escape("version: '$hostVersion'"))
if ($patchedMatches.Count -ne 2) { throw "Desktop Host version injection did not produce exactly two $hostVersion literals." }
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

try {
    [System.IO.File]::WriteAllText($programPath, $patchedText, $utf8NoBom)
    if (Test-Path -LiteralPath $publishPath) { Remove-Item -LiteralPath $publishPath -Recurse -Force }
    New-Item -ItemType Directory -Path $publishPath -Force | Out-Null

    & dotnet publish $projectPath `
        --configuration Release `
        --runtime $runtimeIdentifier `
        --self-contained true `
        --output $publishPath `
        /p:PublishSingleFile=true `
        /p:IncludeNativeLibrariesForSelfExtract=true `
        /p:PublishTrimmed=false
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed with exit code $LASTEXITCODE" }
} finally {
    [System.IO.File]::WriteAllBytes($programPath, $sourceBytes)
}

$hostExe = Join-Path $publishPath 'SWIR.Desktop.Host.exe'
if (-not (Test-Path -LiteralPath $hostExe -PathType Leaf)) { throw "Desktop Host publish output is missing: $hostExe" }

$bundledWebView2 = Join-Path $publishPath 'WebView2FixedRuntime'
if (Test-Path -LiteralPath $bundledWebView2) { Remove-Item -LiteralPath $bundledWebView2 -Recurse -Force }
New-Item -ItemType Directory -Path $bundledWebView2 -Force | Out-Null
Copy-Item -Path (Join-Path $webView2Source '*') -Destination $bundledWebView2 -Recurse -Force
$bundledWebView2Exe = Join-Path $bundledWebView2 'msedgewebview2.exe'
if (-not (Test-Path -LiteralPath $bundledWebView2Exe -PathType Leaf)) { throw 'Bundled WebView2 runtime copy is incomplete.' }

$commit = if ([string]::IsNullOrWhiteSpace($SourceCommit)) { 'local-unpinned' } else { $SourceCommit.Trim().ToLowerInvariant() }
if ($commit -ne 'local-unpinned' -and $commit -notmatch '^[0-9a-f]{40}$') { throw "SourceCommit must be a 40-character Git SHA when supplied. Got: $SourceCommit" }
$webView2Version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($webView2Exe).FileVersion
if ([string]::IsNullOrWhiteSpace($webView2Version)) { $webView2Version = 'fixture-or-unknown' }
$isContractFixture = Test-Path -LiteralPath (Join-Path $webView2Source '.swir-ci-contract-fixture') -PathType Leaf

$manifest = [ordered]@{
    schema = 'swir.desktop-host-build/0.1'
    releaseVersion = $ReleaseVersion
    channel = $Channel
    hostVersion = $hostVersion
    sourceCommit = $commit
    entryPoint = 'SWIR.Desktop.Host.exe'
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
            sourcePolicy = 'microsoft-official-fixed-version-runtime'
            contractFixture = [bool]$isContractFixture
        }
    }
}
$manifestPath = Join-Path $publishPath 'desktop-host-build.json'
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $utf8NoBom)

$restoredBytes = [System.IO.File]::ReadAllBytes($programPath)
if (-not [System.Linq.Enumerable]::SequenceEqual([byte[]]$sourceBytes, [byte[]]$restoredBytes)) { throw 'Program.cs was not restored byte-for-byte after Desktop Host publish.' }

Write-Host "SWIR Desktop Host published as $hostVersion ($runtimeIdentifier, self-contained .NET + bundled WebView2 Fixed Runtime)"
Write-Host "Build manifest: $manifestPath"
