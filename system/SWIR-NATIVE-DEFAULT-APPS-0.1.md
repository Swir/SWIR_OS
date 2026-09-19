# SWIR Native Default Apps 0.1

System Edition Settings provides a native GTK4 **Default Apps** panel for all six Product Baseline categories. Every first-party handler is source-controlled, staged through the trusted graphical-session provisioning path, and verified as a per-user Gio association without privileged mutation.

## Verified categories

| Category | Canonical handler types | First-party application |
|---|---|---|
| Browser | `x-scheme-handler/http`, `x-scheme-handler/https`, `text/html` | `swir-browser.desktop` |
| Media player | `audio/mpeg`, `video/mp4` | `swir-player.desktop` |
| Image viewer / editor | `image/png`, `image/jpeg` | `swir-photo-studio.desktop` |
| PDF viewer | `application/pdf` | `swir-pdf-viewer.desktop` |
| Text / code editor | `text/plain`, `text/markdown`, `application/json`, `text/x-python` | `swir-text-editor.desktop` |
| Archive manager | `application/zip`, `application/x-tar`, `application/gzip`, `application/x-xz`, `application/x-bzip2` | `swir-archive-manager.desktop` |

Settings discovers applications through the native Gio desktop application registry. A candidate is offered only when it advertises **every canonical handler type** for the category, which prevents a partial association from being presented as a complete category default.

## Mutation boundary

Default changes are per-user desktop associations. Settings calls the Gio `AppInfo` default-handler API for the selected application and then verifies that every canonical handler type resolves back to the same desktop application ID.

The panel does **not**:

- invoke `sudo`, `pkexec` or a privileged broker;
- install or remove packages;
- modify system-owned desktop files;
- edit `/etc` or package-manager configuration;
- uninstall SWIR first-party applications when an alternative is selected.

## Image staging and runtime evidence

`system/session/provision-graphical-session.sh` stages the Text Editor binary and both text/archive desktop registrations into the final System image beside the four previously staged Default Apps handlers. The provisioning path verifies trusted regular-file ownership/modes and rebuilds the desktop database inside the root filesystem.

`.github/workflows/system-native-default-apps.yml` validates all six desktop registrations and their image-staging declarations, maps real SWIR Settings in a controlled headless Wayland session, applies all six first-party defaults, and verifies Gio resolves every canonical MIME/scheme type back to the expected desktop ID. The gate then launches representative Python/text and ZIP inputs through the **default Gio registry** and requires runtime evidence from the selected Text Editor and Archive Manager, proving the associations are usable rather than metadata-only.

This completes the Product Baseline Default Apps **six-category integration slice**. It does not by itself close the broader roadmap item for the entire essential native Linux application suite, and it does not change the project percentage without that wider deliverable being fully implemented and verified.
