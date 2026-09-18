# SWIR Shell Themes 0.1

SWIR OS System Edition supports installable, per-user shell themes/skins without allowing a theme package to become executable code.

## Package format

A `.swirtheme` package is a bounded UTF-8 JSON document using schema `swir.theme/1.0`. The top-level object must contain exactly:

- `schema`
- `id`
- `name`
- `tokens`

The token object is an exact allowlist: `background`, `surface`, `primary`, `accent`, `text`, `muted`, `border`, `radius`, `spacing`, and `fontScale`.

Theme packages cannot supply CSS, selectors, commands, scripts, URLs, file paths, plugins or executable payloads. Colors must be six-digit hex values; geometry and font scaling are bounded. Text/background and text/surface contrast must satisfy the verified accessibility floor before a package can be installed.

## Installation and storage

SWIR Settings exposes **Import .swirtheme** and installs only a local regular file that passes the runtime policy. Packages are normalized before storage beneath `${XDG_DATA_HOME:-~/.local/share}/swir/themes/`.

The theme directory is owner-only `0700`; installed packages are `0600`; symbolic-link package inputs and symbolic-link storage paths fail closed. Installation uses a same-directory temporary file, `fsync` and atomic replacement.

The selected theme id is persisted in the existing owner-only SWIR user settings file. Existing settings created before theme support remain compatible and default to `builtin.swir-dark`.

## Runtime application

`system/apps/core_runtime.py` validates packages and compiles only verified tokens into a fixed SWIR Shell CSS template. Package content cannot create CSS property names or selectors.

`system/session/swir-shell.py` loads the selected package during shell startup and adds the generated CSS at application priority above the built-in SWIR styling. The shell remains unprivileged.

If a selected package is missing, corrupt, unsafe, low-contrast or otherwise invalid, the shell recovers to the immutable built-in **SWIR Dark** theme. SWIR Settings also provides a permanent **Reset to SWIR Default** action.

## Verification

`.github/workflows/system-shell-themes.yml` verifies:

- settings/theme schema compatibility and owner-only storage;
- exact token allowlisting and size/id bounds;
- rejection of arbitrary extra fields, path traversal ids, CSS/URL injection and low-contrast themes;
- rejection of symbolic-link package inputs;
- import of a valid theme in the real GTK4 Settings window on headless Wayland;
- application of that theme by the real SWIR Shell window;
- recovery to `builtin.swir-dark` when the configured theme is unavailable;
- absence of `eval`, `exec`, shell execution or privileged helpers in the theme path.

This milestone covers the System Edition shell theme/skin framework and safe recovery contract. It does not imply arbitrary application theming, third-party plugin execution, a theme marketplace, or completion of the broader native-application-suite roadmap item.
