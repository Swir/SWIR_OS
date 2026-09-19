# SWIR Native Default Apps 0.1

System Edition Settings provides a native GTK4 **Default Apps** panel for verified first-party desktop categories instead of exposing only the browser selector.

## Current verified categories

| Category | Canonical handler types | First-party application |
|---|---|---|
| Browser | `x-scheme-handler/http`, `x-scheme-handler/https`, `text/html` | `swir-browser.desktop` |
| Media player | `audio/mpeg`, `video/mp4` | `swir-player.desktop` |
| Image viewer / editor | `image/png`, `image/jpeg` | `swir-photo-studio.desktop` |
| PDF viewer | `application/pdf` | `swir-pdf-viewer.desktop` |

Settings discovers applications through the native Gio desktop application registry. A candidate is offered only when it advertises **every canonical handler type** for the category, which avoids presenting a partial association as a complete category default.

## Text/code and archive handler readiness

The System source now contains two concrete first-party handler registrations that are being qualified before they are added to the Settings panel and final image staging:

- `swir-text-editor.desktop` launches the native GTK4 `swir-text-editor.py` for `text/plain`, `application/json` and `text/x-python`. The editor accepts native local paths only, rejects symbolic-link paths, bounds UTF-8 files to 2 MiB, detects on-disk changes using file identity/mtime/size and saves by same-directory atomic replacement while preserving the existing mode.
- `swir-archive-manager.desktop` delegates ZIP/TAR-family inputs to the existing `swir-files --archive-manager --archive-open` path. It advertises only archive MIME classes corresponding to formats already accepted by the bounded Archive Manager implementation.

`.github/workflows/system-native-file-handlers.yml` validates both desktop registrations, runs the existing fail-closed Archive Manager self-test, and exercises real local-file open/edit/save behavior for SWIR Text Editor in a headless Wayland session.

These two handler registrations are **readiness evidence, not a 6/6 Default Apps completion claim**. Text/code and archive remain open in Settings until both desktop files and the new executable are staged by the production graphical-session provisioner and the six-category Gio mutation E2E passes from that staged shape.

## Mutation boundary

Default changes are per-user desktop associations. Settings calls the Gio `AppInfo` default-handler API for the selected application and then verifies that every canonical handler type resolves back to the same desktop application ID.

The panel does **not**:

- invoke `sudo`, `pkexec` or a privileged broker;
- install or remove packages;
- modify system-owned desktop files;
- edit `/etc` or package-manager configuration;
- uninstall SWIR first-party applications when an alternative is selected.

## Runtime evidence

`.github/workflows/system-native-default-apps.yml` installs the four currently integrated first-party `.desktop` files into an isolated temporary `XDG_DATA_HOME`, validates their metadata, starts a headless Wayland session, maps real SWIR Settings, applies all four first-party defaults, verifies Gio resolves each canonical MIME/scheme type back to the expected desktop ID, and checks owner-only Settings/evidence files.

`.github/workflows/system-native-file-handlers.yml` separately qualifies the new text/code and archive handler foundation without weakening the existing four-category gate or pretending production image staging has already happened.

This is real user-level handler/runtime evidence in isolated CI profiles. It is not a roadmap-completion claim for the entire essential native application suite.
