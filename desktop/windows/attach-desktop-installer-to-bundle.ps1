param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [Parameter(Mandatory = $true)][string]$Version,
    [ValidateSet('preview','stable')][string]$Channel = 'preview',
    [switch]$SmokeInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$versionValue = [Version]::Parse($Version)
if ($versionValue.Build -lt 0 -or $versionValue -le [Version]'0.0.0') {
    throw 'Version must be a positive three-part numeric version.'
}

$bundle = [IO.Path]::GetFullPath($BundleDir).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
if (-not (Test-Path -LiteralPath $bundle -PathType Container)) {
    throw "Release bundle directory does not exist: $bundle"
}

$packageName = "SWIR-Desktop-$Version-$Channel.zip"
$setupName = "SWIR-Desktop-Setup-$Version-$Channel.exe"
$package = Join-Path $bundle $packageName
$targetSetup = Join-Path $bundle $setupName
$targetManifest = Join-Path $bundle 'desktop-installer-build.json'

if (-not (Test-Path -LiteralPath $package -PathType Leaf) -or (Get-Item -LiteralPath $package).Length -le 0) {
    throw "Verified Desktop release package is missing or empty: $packageName"
}
if (Test-Path -LiteralPath $targetSetup -PathType Leaf) {
    throw "Release bundle already contains $setupName; refusing overwrite."
}
if (Test-Path -LiteralPath $targetManifest -PathType Leaf) {
    throw 'Release bundle already contains desktop-installer-build.json; refusing overwrite.'
}

$workspace = Join-Path ([IO.Path]::GetTempPath()) ("swir-release-installer-" + [Guid]::NewGuid().ToString('N'))
$output = Join-Path $workspace 'output'
$smokeRoot = Join-Path $workspace 'install'
New-Item -ItemType Directory -Path $output -Force | Out-Null

try {
    $builder = Join-Path $PSScriptRoot 'build-desktop-installer.ps1'
    if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) {
        throw "Desktop installer builder is missing: $builder"
    }

    & $builder -PackageZip $package -OutputDir $output -Version $Version -Channel $Channel
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop installer builder failed with exit code $LASTEXITCODE."
    }

    $setup = Join-Path $output $setupName
    $manifestPath = Join-Path $output 'desktop-installer-build.json'
    foreach ($required in @($setup, $manifestPath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf) -or (Get-Item -LiteralPath $required).Length -le 0) {
            throw "Desktop installer output is missing or empty: $required"
        }
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.schema -ne 'swir.desktop-installer-build/0.1' `
        -or $manifest.version -ne $Version `
        -or $manifest.channel -ne $Channel `
        -or $manifest.selfContained -ne $true `
        -or $manifest.singleFile -ne $true `
        -or $manifest.userPrerequisiteDownloadsRequired -ne $false) {
        throw 'Desktop installer build manifest violates the release contract.'
    }

    $packageHash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
    $setupHash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([string]$manifest.payloadSha256 -ne $packageHash) {
        throw 'Installer manifest payload SHA-256 does not match the already-verified Desktop release ZIP.'
    }
    if ([string]$manifest.installerSha256 -ne $setupHash) {
        throw 'Installer manifest SHA-256 does not match the produced Setup EXE.'
    }
    if ([long]$manifest.payloadSize -ne (Get-Item -LiteralPath $package).Length `
        -or [long]$manifest.installerSize -ne (Get-Item -LiteralPath $setup).Length) {
        throw 'Installer build manifest sizes do not match release bytes.'
    }

    $verify = Start-Process -FilePath $setup -ArgumentList @('--verify-only','--quiet') -Wait -PassThru
    if ($verify.ExitCode -ne 0) {
        throw "Setup embedded payload verification failed with exit code $($verify.ExitCode)."
    }

    if ($SmokeInstall) {
        $install = Start-Process -FilePath $setup -ArgumentList @('--no-launch','--quiet','--install-root',$smokeRoot) -Wait -PassThru
        if ($install.ExitCode -ne 0) {
            throw "Setup clean-install smoke test failed with exit code $($install.ExitCode)."
        }
        $currentPath = Join-Path $smokeRoot 'current.json'
        if (-not (Test-Path -LiteralPath $currentPath -PathType Leaf)) {
            throw 'Setup smoke test did not produce current.json.'
        }
        $current = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
        if ($current.schema -ne 'swir.desktop-current-install/0.1' -or $current.version -ne $Version -or $current.channel -ne $Channel) {
            throw 'Setup smoke-test current installation pointer is invalid.'
        }
        $installed = [IO.Path]::GetFullPath([string]$current.installDirectory).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        foreach ($required in @('SWIR.Desktop.Host.exe','desktop-host-build.json','install-receipt.json','WebView2FixedRuntime\msedgewebview2.exe')) {
            if (-not (Test-Path -LiteralPath (Join-Path $installed $required) -PathType Leaf)) {
                throw "Setup smoke test is missing installed runtime file: $required"
            }
        }
        $receipt = Get-Content -LiteralPath (Join-Path $installed 'install-receipt.json') -Raw | ConvertFrom-Json
        $receiptDirectory = [IO.Path]::GetFullPath([string]$receipt.InstallDirectory).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        if ($receipt.Schema -ne 'swir.desktop-install-receipt/0.1' `
            -or $receipt.Version -ne $Version `
            -or $receipt.Channel -ne $Channel `
            -or $receipt.PackageSha256 -ne $packageHash `
            -or -not [string]::Equals($receiptDirectory, $installed, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Setup smoke-test install receipt does not bind to the verified release package and final install path.'
        }
    }

    Copy-Item -LiteralPath $setup -Destination $targetSetup
    Copy-Item -LiteralPath $manifestPath -Destination $targetManifest

    $finalSetupHash = (Get-FileHash -LiteralPath $targetSetup -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($finalSetupHash -ne $setupHash) {
        throw 'Setup EXE changed while attaching it to the release bundle.'
    }

    Write-Host "Attached verified one-file SWIR Desktop setup: $setupName"
    Write-Host "Setup SHA-256: $setupHash"
    Write-Host "Embedded verified package SHA-256: $packageHash"
}
finally {
    Remove-Item -LiteralPath $workspace -Recurse -Force -ErrorAction SilentlyContinue
}
