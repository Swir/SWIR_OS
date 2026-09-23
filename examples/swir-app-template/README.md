# SWIR App SDK starter

This directory is a minimal **Web Edition developer template** for the current SWIR App SDK and package contract. It is an example source tree, not a published Store application and not a claim that browser applications satisfy the native System Edition baseline.

## What the example proves

The starter uses the current `swir.app/1.0` manifest and the package-side `SwirAppBridge`. It demonstrates only three portable surfaces:

- `sdk.bridge.info()` for bounded runtime/package identity;
- `sdk.locale.info()` and `sdk.locale.formatNumber()` for locale-aware UI;
- permission-checked package storage through `bridge.storage.get/set/remove`.

The manifest declares only `storage`. No file, network, identity, notification or privileged capability is requested.

## Start a new app

1. Copy this directory and change `id`, `packageId`, `name`, `author`, `appData`, icon and accent in `app.json`.
2. Keep third-party/example package IDs outside the reserved `swir.*` namespace.
3. During repository development, add the reviewed manifest to `SWIR_PACKAGE_CATALOG` and keep its Web entry same-origin. The bridge host only accepts packages that exist in the trusted catalog and are opened in a managed SWIR iframe matching the registered entry.
4. Install/review the package through the normal Store/package flow so declared permissions can be explicitly granted. A manifest declaration is metadata, not authority.
5. Open the app from the SWIR shell. Do not use a direct `file://` launch as proof that the package bridge works.
6. Run `node scripts/check-web-sdk-template.mjs` before committing changes to the template or SDK contract.

The repository-root Web entry in this example is `./examples/swir-app-template/index.html`. A future packaged `.swirapp` archive may use a package-root entry such as `./index.html`; that is a different packaging context and must still pass native trust and integrity verification.

## Security model

Do not bypass the bridge with direct parent-window access, `localStorage`, IndexedDB, arbitrary `fetch()` calls or shell internals. The host broker binds requests to the trusted catalog entry, managed frame origin and package ID, then checks both manifest declaration and user-granted permission before sensitive operations.

Remote JavaScript is not treated as a trusted SWIR package payload. Add a permission only when the app actually consumes the corresponding approved API. Network access, when declared and granted, is still constrained by the App Bridge HTTPS and private-target policy.

The starter deliberately fails with a clear status if the package is not registered/opened through the managed shell. It does not silently fall back to raw browser storage because that would hide a broken integration.

## Files

- `app.json` — package manifest aligned with SWIR App SDK `1.6.1`, Platform API `2` and Web Edition.
- `index.html` — accessible, self-contained UI with no remote assets.
- `app.js` — App Bridge example with bounded private app-data storage.
- `icon.svg` — original local icon for the template.

For the full contract and additional SDK surfaces, read [`../../SWIR-APP-DEVELOPER-GUIDE-1.0.md`](../../SWIR-APP-DEVELOPER-GUIDE-1.0.md) and [`../../SWIR-APP-PACKAGE-1.0.md`](../../SWIR-APP-PACKAGE-1.0.md).
