# SWIR OS Desktop update feeds

This directory is the repository-owned publication point for **signed Desktop update envelopes**. It is not a binary mirror and it never contains a private signing key.

## Channels

- `updates/preview/desktop-update-preview.json` — latest published preview release.
- `updates/stable/desktop-update-stable.json` — latest published stable release.

A feed file is created only after a matching immutable GitHub Release is published. The `SWIR Desktop Update Feed` workflow downloads the already-signed `desktop-update-<channel>.json` release asset, validates its channel/version/package URL, refuses a downgrade or a conflicting envelope for the same version, then advances the channel feed on `main`.

## Binary source

Desktop packages are downloaded only from immutable release URLs of this form:

```text
https://github.com/Swir/SWIR_OS/releases/download/desktop-v<VERSION>-<CHANNEL>/SWIR-Desktop-<VERSION>-<CHANNEL>.zip
```

GitHub may redirect a release download to its content delivery infrastructure. The Desktop updater allows at most one such redirect and only when the signed original URL belongs to `Swir/SWIR_OS`; the target must stay on HTTPS `*.githubusercontent.com`. The downloaded bytes still have to match the size and SHA-256 protected by the RSA-PSS signed update payload.

## Trust model

Official release packaging derives the **public** update-verification key from the protected release signing key and embeds only that public key in `desktop-update-policy.json`. The private RSA key remains outside the repository and outside shipped clients.

The raw feed on `main` is transport, not the trust root. A modified or forged feed is rejected unless its envelope validates against the embedded public key. Installed clients also reject same-version and downgrade manifests.

## Release lifecycle

```text
verified Desktop build
  -> immutable GitHub Release package
  -> RSA-PSS signed update envelope
  -> GitHub Release published
  -> feed promotion workflow
  -> updates/<channel>/desktop-update-<channel>.json
  -> Desktop Update Center
  -> signed manifest verification
  -> controlled GitHub release redirect
  -> SHA-256 + size verification
  -> staged candidate
  -> health proof / commit or rollback
```
