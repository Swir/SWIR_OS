# SWIR OS Desktop update feeds

This directory is the repository-owned publication point for **signed Desktop update envelopes**. It is not a binary mirror and it never contains a private signing key.

## Channels

- `updates/preview/desktop-update-preview.json` — latest published preview release.
- `updates/stable/desktop-update-stable.json` — latest published stable release.

A feed file is created only after a matching immutable GitHub Release is published. The `SWIR Desktop Update Feed` workflow downloads both the already-signed `desktop-update-<channel>.json` release asset and the exact `SWIR-Desktop-<version>-<channel>.zip` package. Promotion is fail-closed: before `main` can advance, the workflow validates the channel/version/package URL, verifies the envelope with the pinned RSA public key, requires the signed `KeyId` to match the pinned key id, independently recomputes the package size and SHA-256, and refuses a downgrade or a conflicting envelope for the same version.

## Binary source

Desktop packages are downloaded only from immutable release URLs of this form:

```text
https://github.com/Swir/SWIR_OS/releases/download/desktop-v<VERSION>-<CHANNEL>/SWIR-Desktop-<VERSION>-<CHANNEL>.zip
```

GitHub may redirect a release download to its content delivery infrastructure. The Desktop updater allows at most one such redirect and only when the signed original URL belongs to `Swir/SWIR_OS`; the target must stay on HTTPS `*.githubusercontent.com`. The downloaded bytes still have to match the size and SHA-256 protected by the RSA-PSS signed update payload.

## Trust model

Official release packaging derives the **public** update-verification key from the protected release signing key and embeds only that public key in `desktop-update-policy.json`. The private RSA key remains outside the repository and outside shipped clients.

Feed promotion uses the same public trust boundary through repository variables:

- `SWIR_DESKTOP_UPDATE_KEY_ID` — the pinned release key identifier expected in the signed envelope.
- `SWIR_DESKTOP_UPDATE_PUBLIC_KEY_PEM_B64` — base64-encoded PEM public RSA key corresponding to the protected release signing key.

These values are public verification material, not private signing secrets. If either value is absent, invalid, mismatched, or unable to validate the RSA-PSS-SHA256 signature, feed promotion stops without changing the published feed. The release package is also verified independently against the signed size and SHA-256 before promotion.

The raw feed on `main` is transport, not the trust root. A modified or forged feed is rejected unless its envelope validates against the embedded public key. Installed clients also reject same-version and downgrade manifests.

## Release lifecycle

```text
verified Desktop build
  -> immutable GitHub Release package
  -> RSA-PSS signed update envelope
  -> GitHub Release published
  -> pinned public-key + KeyId verification
  -> independent release-package size + SHA-256 verification
  -> feed promotion workflow
  -> updates/<channel>/desktop-update-<channel>.json
  -> Desktop Update Center
  -> signed manifest verification
  -> controlled GitHub release redirect
  -> SHA-256 + size verification
  -> staged candidate
  -> health proof / commit or rollback
```
