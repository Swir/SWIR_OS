[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackageZip,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][ValidateSet('preview','stable')][string]$Channel,
    [string]$ProjectFile = 'SWIR.Desktop.Installer.csproj',
    [string]$AuthenticodePfxPath = $env:SWIR_AUTHENTICODE_PFX_PATH,
    [string]$AuthenticodeExpectedThumbprint = $env:SWIR_AUTHENTICODE_CERT_THUMBPRINT,
    [string]$AuthenticodeTimestampServer = $env:SWIR_AUTHENTICODE_TIMESTAMP_URL
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$parsed = $null
if (-not [Version]::TryParse($Version, [ref]$parsed) -or $parsed.Build -lt 0 -or $parsed -le [Version]'0.0.0') { throw 'Version must be a positive three-part numeric version.' }
$packagePath = (Resolve-Path -LiteralPath $PackageZip -ErrorAction Stop).Path
$projectPath = (Resolve-Path -LiteralPath $ProjectFile -ErrorAction Stop).Path
$outputPath = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
if ((Get-Item -LiteralPath $packagePath).Length -le 0) { throw 'Desktop installer payload ZIP is empty.' }

$packageHash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedName = "SWIR-Desktop-$Version-$Channel.zip"
if ([IO.Path]::GetFileName($packagePath) -ne $expectedName) { throw "Installer payload filename must be $expectedName." }
$authenticodeRequired = $env:SWIR_AUTHENTICODE_REQUIRED -eq 'true'
$installerAuthenticode = $null

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('swir-installer-build-' + [guid]::NewGuid().ToString('N'))
$publish = Join-Path $tempRoot 'publish'
$metadataPath = Join-Path $tempRoot 'installer-payload.json'
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
$metadata = [ordered]@{
    schema = 'swir.desktop-installer-payload/0.1'
    version = $Version
    channel = $Channel
    packageSha256 = $packageHash
    entryPoint = 'SWIR.Desktop.Host.exe'
}
[IO.File]::WriteAllText($metadataPath, ($metadata | ConvertTo-Json -Depth 4), $utf8)

try {
    $arguments = @(
        'publish', $projectPath,
        '--configuration', 'Release',
        '--runtime', 'win-x64',
        '--self-contained', 'true',
        '--output', $publish,
        '/p:SwirInstallerBuild=true',
        "/p:SwirPayloadZip=$packagePath",
        "/p:SwirPayloadMetadata=$metadataPath",
        '/p:PublishSingleFile=true',
        '/p:IncludeNativeLibrariesForSelfExtract=true',
        '/p:PublishTrimmed=false',
        "/p:Version=$Version"
    )
    & dotnet @arguments
    if ($LASTEXITCODE -ne 0) { throw "SWIR Desktop installer publish failed with exit code $LASTEXITCODE." }

    $built = Join-Path $publish 'SWIR.Desktop.Setup.exe'
    if (-not (Test-Path -LiteralPath $built -PathType Leaf)) { throw "Installer executable missing after publish: $built" }
    $installerName = "SWIR-Desktop-Setup-$Version-$Channel.exe"
    $installerPath = Join-Path $outputPath $installerName
    Copy-Item -LiteralPath $built -Destination $installerPath -Force

    if (-not [string]::IsNullOrWhiteSpace($AuthenticodePfxPath)) {
        $signScript = Join-Path $PSScriptRoot 'sign-desktop-artifact.ps1'
        if (-not (Test-Path -LiteralPath $signScript -PathType Leaf)) { throw "Authenticode signing script is missing: $signScript" }
        $json = & $signScript -FilePath $installerPath -PfxPath $AuthenticodePfxPath -ExpectedThumbprint $AuthenticodeExpectedThumbprint -TimestampServer $AuthenticodeTimestampServer
        if ($LASTEXITCODE -ne 0) { throw "SWIR Desktop Setup Authenticode signing failed with exit code $LASTEXITCODE." }
        $installerAuthenticode = $json | ConvertFrom-Json
        if ($installerAuthenticode.schema -ne 'swir.desktop-authenticode/0.1' -or $installerAuthenticode.status -ne 'valid') { throw 'Desktop Setup Authenticode result is invalid.' }
    } elseif ($authenticodeRequired) {
        throw 'SWIR_AUTHENTICODE_REQUIRED=true but no Authenticode PFX path was supplied.'
    }

    $installerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $installerInfo = Get-Item -LiteralPath $installerPath

    $buildManifest = [ordered]@{
        schema = 'swir.desktop-installer-build/0.1'
        version = $Version
        channel = $Channel
        installerFile = $installerName
        installerSha256 = $installerHash
        installerSize = [long]$installerInfo.Length
        payloadFile = $expectedName
        payloadSha256 = $packageHash
        payloadSize = [long](Get-Item -LiteralPath $packagePath).Length
        runtimeIdentifier = 'win-x64'
        selfContained = $true
        singleFile = $true
        userPrerequisiteDownloadsRequired = $false
        authenticode = [ordered]@{
            contract = 'swir.desktop-authenticode/0.1'
            required = [bool]$authenticodeRequired
            signed = $null -ne $installerAuthenticode
            status = if ($null -eq $installerAuthenticode) { 'unsigned' } else { [string]$installerAuthenticode.status }
            signerThumbprint = if ($null -eq $installerAuthenticode) { '' } else { [string]$installerAuthenticode.signerThumbprint }
            signerSubject = if ($null -eq $installerAuthenticode) { '' } else { [string]$installerAuthenticode.signerSubject }
            timestamped = if ($null -eq $installerAuthenticode) { $false } else { [bool]$installerAuthenticode.timestamped }
        }
    }
    [IO.File]::WriteAllText((Join-Path $outputPath 'desktop-installer-build.json'), ($buildManifest | ConvertTo-Json -Depth 6), $utf8)
    Write-Host "Built $installerName"
    Write-Host "Authenticode: $($buildManifest.authenticode.status)"
    Write-Host "Installer SHA-256: $installerHash"
    Write-Host "Embedded package SHA-256: $packageHash"
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
