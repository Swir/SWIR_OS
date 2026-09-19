# SWIR Native File Handlers 0.1

System Edition has source-controlled first-party desktop handlers for the Product Baseline **text/code** and **archive** categories, with real local-file runtime behavior and dedicated Wayland verification.

## Text/code handler

`system/apps/swir-text-editor.py` is a first-party GTK4 local UTF-8 editor using `Gio.ApplicationFlags.HANDLES_OPEN`. `system/apps/swir-text-editor.desktop` registers common plain-text/code types and passes exactly one local path with `%f`.

The editor fails closed for remote/URI input, symbolic-link paths, hard-linked/non-regular files, NUL/binary content, invalid UTF-8 and files larger than 4 MiB. Save is explicit and revalidates the original device/inode/link state before an atomic same-directory temporary-file + `fsync` + `os.replace` update. Existing ordinary permission bits are preserved. It does not invoke a shell, privilege broker, package manager or self-updater.

## Archive handler

`system/apps/swir-archive-manager.desktop` routes one local archive to the verified first-party Archive Manager mode:

`/usr/local/bin/swir-files --archive-manager --archive-open <local-file>`

The underlying Archive Manager enforces canonical local input, archive size/entry bounds, whole-member validation, traversal/symlink/special-member rejection and exclusive no-follow extraction writes.

## Verification boundary

`.github/workflows/system-native-file-handlers.yml` validates both desktop entries, runs the Text Editor and Archive Manager self-tests, and exercises both applications in a headless Wayland session against real local sample files. The test confirms a real text edit/save and a real safe archive extraction while preserving the no-privilege boundary.

## Default Apps integration

The handlers are now staged by `system/session/provision-graphical-session.sh` into the System image and are included in the six-category Settings Default Apps registry together with browser, media, image and PDF. `.github/workflows/system-native-default-apps.yml` verifies the per-user Gio association for all six categories and launches representative text/code and archive inputs through the selected default handlers.

This closes the text/archive integration gap identified when the handlers were introduced. It does not by itself close the broader roadmap item for the full essential native application suite or change the project percentage.
