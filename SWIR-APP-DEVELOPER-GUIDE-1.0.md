# SWIR App Developer Guide 1.0

## Scope

This guide documents the current **Web Edition application-development path** for SWIR OS. It complements [`SWIR-APP-PACKAGE-1.0.md`](SWIR-APP-PACKAGE-1.0.md) and the live SDK/bridge implementation. It does not redefine the System Edition rule: essential bundled System applications remain native Linux applications, while managed Windows software uses the separate Wine/Proton compatibility layer.

A working starter lives at [`examples/swir-app-template/`](examples/swir-app-template/README.md).

## Runtime model

```text
reviewed SWIR package manifest
          |
          v
trusted Web package catalog
          |
          v
managed same-origin SWIR iframe
          |
          v
SwirAppBridge (package side)
          |
          v
SwirAppBridgeHost (shell broker)
          |
          +--> verify catalog package identity
          +--> verify managed frame origin + entry
          +--> verify declared + granted permission
          |
          v
approved SDK / platform service
```

Package code should use `window.SwirAppBridge`. Root-shell code can use `window.SwirAppSDK`, but package applications must not depend on reaching through `parent` to shell internals.

## Package manifest

The current schema is `swir.app/1.0`. Required fields are:

- `schema`
- `id`
- `packageId`
- `name`
- `version`
- `author`
- `type`
- `entry`

A Web package should additionally declare only the permissions it actually consumes and should state its compatibility requirements. The starter is intentionally conservative:

```json
{
  "schema": "swir.app/1.0",
  "id": "hello-template",
  "packageId": "example.hello",
  "name": "SWIR SDK Starter",
  "version": "1.0.0",
  "author": "Your Name",
  "type": "iframe",
  "entry": "./examples/swir-app-template/index.html",
  "permissions": ["storage"],
  "compatibility": {
    "minOS": "1.7.0",
    "minSDK": "1.6.1",
    "platformApi": 2,
    "editions": ["WEB"]
  }
}
```

The `swir.*` package namespace is reserved for official SWIR packages. Example and third-party package IDs should use their own namespace.

## Package-side bridge

Load the package bridge from the repository origin and bind it to the reviewed package identity:

```html
<script
  src="../../swir-app-bridge.js"
  data-swir-package="example.hello"
  data-swir-app="hello-template"></script>
```

The current bridge exposes these package-side groups:

```text
SwirAppBridge.storage.get / set / remove
SwirAppBridge.files.consumeOpen
SwirAppBridge.network.request / json
SwirAppBridge.locale.info / translate / format*
SwirAppBridge.sdk.identity.active
SwirAppBridge.sdk.notifications.send
SwirAppBridge.sdk.shell.notify
SwirAppBridge.sdk.bridge.info
```

Availability is not authority. The host broker checks the catalog package, frame origin/entry and permission state before dispatching sensitive calls.

## Permission examples

The current portable permission vocabulary includes:

| Permission | Typical bridge/API use |
|---|---|
| `storage` | private application data through bridge storage |
| `files.read` | consume a user/OS-selected file handoff |
| `files.write` | approved file/save paths in supported adapters |
| `network` | bounded App Bridge HTTPS request |
| `identity.basic` | active profile's basic public identity |
| `notifications` | application notification service |
| `clipboard` | supported clipboard features |
| `downloads` | explicit export/download flows |

A manifest permission is only a declaration. The platform must still grant it, and the broker must still enforce it. Do not add permissions pre-emptively.

## Locale example

The bridge exposes read-only locale state and locale-aware formatting for isolated packages:

```js
const bridge = window.SwirAppBridge;
const locale = await bridge.sdk.locale.info();
document.documentElement.lang = locale.locale;
document.documentElement.dir = locale.direction === 'rtl' ? 'rtl' : 'ltr';
const countLabel = await bridge.sdk.locale.formatNumber(3);
```

Missing application translations should fall back safely rather than producing blank controls. Native System applications consume equivalent native locale services and do not require the Web App Bridge for essential operation.

## Private application data example

```js
const bridge = window.SwirAppBridge;
const previous = await bridge.storage.get('launchCount', 0);
await bridge.storage.set('launchCount', Number(previous || 0) + 1);
```

The caller must declare and receive an appropriate permission such as `storage`. Do not replace this with direct `localStorage` or IndexedDB access in a package template; doing so bypasses the portable namespace and hides permission/integration failures.

## Network example and limits

If the app genuinely needs network access, declare `network` and use the bridge:

```js
const data = await window.SwirAppBridge.network.json({
  url: 'https://example.invalid/api/status',
  method: 'GET',
  headers: { accept: 'application/json' }
});
```

The current host accepts HTTPS only, blocks private/loopback/local targets, restricts methods and headers, omits credentials, disables cache, rejects redirects and bounds request/response sizes. Those restrictions are part of the security boundary, not inconveniences to work around.

## Package lifecycle and compatibility

Before an install, SWIR's resolver can validate OS, SDK, Platform API, edition and dependency requirements. Root-shell tooling exposes the richer lifecycle through `SwirAppSDK.packages.*`, including compatibility checks, dependency planning, integrity/trust helpers and the secure install pipeline. Package applications should not invoke shell package-management internals through the bridge.

For Web Edition, official entries are repository/same-origin assets. Arbitrary remote JavaScript is not considered a trusted package. Desktop `.swirapp` installation additionally requires native package integrity/signature policy; this guide does not weaken or replace those gates.

## Validation

The repository keeps the starter tied to the current contracts with:

```text
node --check examples/swir-app-template/app.js
node scripts/check-web-sdk-template.mjs
```

The validator checks manifest compatibility against the shipping SDK, entry and bridge identity, declared permission vocabulary, forbidden direct browser/shell bypasses and safe local SVG usage. The dedicated GitHub Actions contract runs the same checks when the SDK, bridge, package contract, guide or starter changes.

A template milestone is complete only when this example and its contract checks are present and passing. It does not imply Store publication, production package signing, a public Desktop release or native System application readiness.
