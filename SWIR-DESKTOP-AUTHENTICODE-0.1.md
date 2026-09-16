# SWIR Desktop Authenticode Contract 0.1

SWIR OS Desktop uses two independent trust layers for public Windows delivery:

1. SWIR release/catalog signatures protect the package/update model inside the product.
2. Windows Authenticode signs public PE executables such as the Desktop Host and the one-file Setup so Windows can verify publisher identity and detect post-signing modification.

These layers are complementary. Authenticode does not replace the signed catalog, release bundle SHA-256 checks, package receipts or bundled-runtime integrity.

## Contract

The repository contract identifier is:

```text
swir.desktop-authenticode/0.1
```

The signing helper is `desktop/windows/sign-desktop-artifact.ps1`. It requires:

- a PFX containing a private key,
- a Code Signing EKU (`1.3.6.1.5.5.7.3.3`),
- an explicitly pinned certificate SHA-1 thumbprint,
- SHA-256 artifact signing,
- an HTTPS timestamp server whenever timestamping is requested.

After signing, the helper re-reads the Authenticode signature and fails unless Windows reports `Valid` and the signer matches the pinned thumbprint. When a timestamp URL is supplied, a timestamp certificate must also be present.

## Secret handling

Production private signing material must never be committed. Release infrastructure should provide these values from protected secrets or a future hardware/cloud signing service:

```text
SWIR_AUTHENTICODE_PFX_PATH
SWIR_AUTHENTICODE_PFX_PASSWORD
SWIR_AUTHENTICODE_CERT_THUMBPRINT
SWIR_AUTHENTICODE_TIMESTAMP_URL
SWIR_AUTHENTICODE_REQUIRED=true
```

`SWIR_AUTHENTICODE_REQUIRED=true` makes Host and Setup builds fail closed if the signing identity is unavailable. Normal local/contract builds may remain unsigned unless that flag is enabled.

## Host integration

`publish-desktop-host.ps1` signs `SWIR.Desktop.Host.exe` after the self-contained publish and before `desktop-host-build.json` calculates the Host SHA-256. Therefore the integrity manifest always binds the final signed bytes, not the pre-signing executable.

The build manifest records:

```text
authenticode.contract
authenticode.required
authenticode.signed
authenticode.status
authenticode.signerThumbprint
authenticode.signerSubject
authenticode.timestamped
```

## Setup integration

`build-desktop-installer.ps1` signs `SWIR-Desktop-Setup-<version>-<channel>.exe` before computing `installerSha256` and `installerSize`. `desktop-installer-build.json` therefore binds the final signed Setup bytes and records the same Authenticode contract fields.

## CI verification

`Desktop Authenticode Contract` creates an isolated, short-lived CI Code Signing certificate, trusts it only inside the disposable Windows runner and verifies:

- pinned-thumbprint signing succeeds;
- a wrong thumbprint fails before acceptance;
- post-signing tampering invalidates Authenticode;
- the self-contained Desktop Host is signed before its integrity SHA-256 is recorded;
- the one-file Setup is signed before its installer SHA-256 is recorded;
- Host and Setup manifests report required, valid Authenticode state.

The CI certificate is not a production publisher identity and is deleted from the runner certificate stores at the end of the contract.

## Production gate still required

The implementation and CI contract do not create a real public publisher certificate. Before publishing a public SWIR OS Desktop release, the release environment must be provisioned with a real protected code-signing identity and an approved HTTPS timestamp service. A public-release workflow should set `SWIR_AUTHENTICODE_REQUIRED=true` and refuse publication when the production identity is absent or invalid.
