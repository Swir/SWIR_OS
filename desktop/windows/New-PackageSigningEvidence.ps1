param(
    [Parameter(Mandatory = $true)] [string]$StoreDir,
    [Parameter(Mandatory = $true)] [string]$TrustRootsPath,
    [Parameter(Mandatory = $true)] [string]$SignerDll,
    [Parameter(Mandatory = $true)] [string]$SourceCommit,
    [Parameter(Mandatory = $true)] [string]$ExpectedKeyId,
    [Parameter(Mandatory = $true)] [string]$OutputPath,
    [ValidateSet('contract','production')] [string]$EvidenceKind = 'contract',
    [string]$GitHubRepository = '',
    [string]$GitHubRunId = '',
    [string]$GitHubRunAttempt = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is required to generate package signing evidence.' }

$generator = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\scripts\generate-package-signing-evidence.mjs'))
if (-not (Test-Path $generator -PathType Leaf)) { throw "Package signing evidence generator is missing: $generator" }

& node $generator `
    $StoreDir `
    $TrustRootsPath `
    $SignerDll `
    $SourceCommit `
    $ExpectedKeyId `
    $OutputPath `
    $EvidenceKind `
    $GitHubRepository `
    $GitHubRunId `
    $GitHubRunAttempt

if ($LASTEXITCODE -ne 0) { throw "Package signing evidence generator failed with exit code $LASTEXITCODE" }
