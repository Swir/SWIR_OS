# SWIR Native Default Apps 0.1

System Edition Settings now provides a native GTK4 **Default Apps** panel for verified first-party desktop categories instead of exposing only the browser selector.

## Current verified categories

| Category | Canonical handler types | First-party application |
|---|---|---|
| Browser | `x-scheme-handler/http`, `x-scheme-handler/https`, `text/html` | `swir-browser.desktop` |
| Media player | `audio/mpeg`, `video/mp4` | `swir-player.desktop` |
| Image viewer / editor | `image/png`, `image/jpeg` | `swir-photo-studio.desktop` |
| PDF viewer | `application/pdf` | `swir-pdf-viewer.desktop` |

Settings discovers applications through the native Gio desktop application registry. A candidate is offered only when it advertises **every canonical handler type** for the category, which avoids presenting a partial association as a complete category default.

## Mutation boundary

Default changes are per-user desktop associations. Settings calls the Gio `AppInfo` default-handler API for the selected application and then verifies that every canonical handler type resolves back to the same desktop application ID.

The panel does **not**:

- invoke `sudo`, `pkexec` or a privileged broker;
- install or remove packages;
- modify system-owned desktop files;
- edit `/etc` or package-manager configuration;
- uninstall SWIR first-party applications when an alternative is selected.

The current change intentionally leaves **text/code** and **archive** Default Apps categories open. They require first-party desktop-handler registration and file-opening behavior that must be implemented and runtime-verified before those Product Baseline categories can be claimed complete.

## Runtime evidence

`.github/workflows/system-native-default-apps.yml` installs the four reviewed first-party `.desktop` files into an isolated temporary `XDG_DATA_HOME`, validates their metadata, starts a headless Wayland session, maps real SWIR Settings, applies all four first-party defaults, verifies Gio resolves each canonical MIME/scheme type back to the expected desktop ID, and checks owner-only Settings/evidence files.

This is a real user-level handler mutation test in an isolated CI profile. It is not a roadmap-completion claim for the entire essential native application suite.
