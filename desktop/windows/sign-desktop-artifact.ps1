[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [string]$PfxPath = $env:SWIR_AUTHENTICODE_PFX_PATH,
    [string]$PfxPassword = $env:SWIR_AUTHENTICODE_PFX_PASSWORD,
    [string]$ExpectedThumbprint = $env:SWIR_AUTHENTICODE_CERT_THUMBPRINT,
    [string]$TimestampServer = $env:SWIR_AUTHENTICODE_TIMESTAMP_URL
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Normalize-Thumbprint([string]$Value) {
    return (($Value -replace '[^A-Fa-f0-9]', '').ToUpperInvariant())
}

$artifact = (Resolve-Path -LiteralPath $FilePath -ErrorAction Stop).Path
if ((Get-Item -LiteralPath $artifact).Length -le 0) { throw "Authenticode target is empty: $artifact" }
if ([string]::IsNullOrWhiteSpace($PfxPath)) { throw 'SWIR Authenticode PFX path is required.' }
if ([string]::IsNullOrWhiteSpace($PfxPassword)) { throw 'SWIR Authenticode PFX password is required.' }
if ([string]::IsNullOrWhiteSpace($ExpectedThumbprint)) { throw 'Pinned SWIR Authenticode certificate thumbprint is required.' }
$pfx = (Resolve-Path -LiteralPath $PfxPath -ErrorAction Stop).Path
$expected = Normalize-Thumbprint $ExpectedThumbprint
if ($expected -notmatch '^[A-F0-9]{40}$') { throw 'Pinned SWIR Authenticode certificate thumbprint must be a 40-hex SHA-1 certificate thumbprint.' }

if (-not [string]::IsNullOrWhiteSpace($TimestampServer)) {
    $timestampUri = $null
    if (-not [Uri]::TryCreate($TimestampServer, [UriKind]::Absolute, [ref]$timestampUri) -or $timestampUri.Scheme -ne 'https') {
        throw 'Authenticode timestamp server must be an absolute HTTPS URL.'
    }
    $TimestampServer = $timestampUri.AbsoluteUri
}

$flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::UserKeySet -bor
         [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($pfx, $PfxPassword, $flags)
try {
    if (-not $certificate.HasPrivateKey) { throw 'SWIR Authenticode PFX does not contain a private key.' }
    $actualThumbprint = Normalize-Thumbprint $certificate.Thumbprint
    if ($actualThumbprint -ne $expected) { throw "SWIR Authenticode certificate thumbprint mismatch. Expected $expected, got $actualThumbprint." }

    $hasCodeSigningEku = $false
    foreach ($extension in $certificate.Extensions) {
        if ($extension -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
            foreach ($oid in $extension.EnhancedKeyUsages) {
                if ($oid.Value -eq '1.3.6.1.5.5.7.3.3') { $hasCodeSigningEku = $true; break }
            }
        }
        if ($hasCodeSigningEku) { break }
    }
    if (-not $hasCodeSigningEku) { throw 'SWIR Authenticode certificate is missing the Code Signing EKU.' }

    $parameters = @{
        FilePath = $artifact
        Certificate = $certificate
        HashAlgorithm = 'SHA256'
        Force = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($TimestampServer)) { $parameters['TimestampServer'] = $TimestampServer }
    $signed = Set-AuthenticodeSignature @parameters
    if ($null -eq $signed) { throw 'Set-AuthenticodeSignature did not return a signature result.' }

    $verified = Get-AuthenticodeSignature -FilePath $artifact
    if ($verified.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "SWIR Authenticode verification failed after signing: $($verified.Status) / $($verified.StatusMessage)"
    }
    if ($null -eq $verified.SignerCertificate) { throw 'Signed SWIR artifact has no signer certificate.' }
    $verifiedThumbprint = Normalize-Thumbprint $verified.SignerCertificate.Thumbprint
    if ($verifiedThumbprint -ne $expected) { throw 'Signed SWIR artifact signer does not match the pinned certificate thumbprint.' }
    $timestamped = $null -ne $verified.TimeStamperCertificate
    if (-not [string]::IsNullOrWhiteSpace($TimestampServer) -and -not $timestamped) {
        throw 'A timestamp server was requested but the signed SWIR artifact has no timestamp certificate.'
    }

    [ordered]@{
        schema = 'swir.desktop-authenticode/0.1'
        status = 'valid'
        hashAlgorithm = 'SHA256'
        signerThumbprint = $verifiedThumbprint
        signerSubject = [string]$verified.SignerCertificate.Subject
        timestamped = [bool]$timestamped
        timestampServer = if ([string]::IsNullOrWhiteSpace($TimestampServer)) { $null } else { $TimestampServer }
    } | ConvertTo-Json -Depth 4 -Compress
} finally {
    $certificate.Dispose()
}
