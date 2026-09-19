# SWIR Native File Handlers 0.1

System Edition now has source-controlled desktop-handler foundations for the missing Product Baseline **text/code** and **archive** categories. This milestone adds real local-file runtime behavior and dedicated verification; it does **not** claim that Settings exposes all six Default Apps categories or that the final boot image stages these registrations yet.

## Text/code handler

`system/apps/swir-text-editor.py` is a first-party GTK4 local UTF-8 editor using `Gio.ApplicationFlags.HANDLES_OPEN`. `system/apps/swir-text-editor.desktop` registers common plain-text/code types and passes exactly one local path with `%f`.

The editor fails closed for remote/URI input, symbolic-link paths, hard-linked/non-regular files, NUL/binary content, invalid UTF-8 and files larger than 4 MiB. Save is explicit and revalidates the original device/inode/link state before an atomic same-directory temporary-file + `fsync` + `os.replace` update. Existing ordinary permission bits are preserved. It does not invoke a shell, privilege broker, package manager or self-updater.

## Archive handler

`system/apps/swir-archive-manager.desktop` routes one local archive to the already verified first-party Archive Manager mode:

`/usr/local/bin/swir-files --archive-manager --archive-open <local-file>`

The underlying Archive Manager continues to enforce canonical local input, archive size/entry bounds, whole-member validation, traversal/symlink/special-member rejection and exclusive no-follow extraction writes.

## Verification boundary

`.github/workflows/system-native-file-handlers.yml` validates both desktop entries, runs the text editor and Archive Manager self-tests, and exercises both applications in a headless Wayland session against real local sample files. The test confirms a real text edit/save and a real safe archive extraction while preserving the no-privilege boundary.

## Remaining integration before Default Apps completion

This milestone intentionally leaves the Product Baseline Default Apps claim open. A later integration must:

1. stage `swir-text-editor`, `swir-text-editor.desktop` and `swir-archive-manager.desktop` into the final System image through the trusted provisioning path;
2. extend Settings from the currently verified four categories to all six (`browser`, `media`, `image`, `pdf`, `text`, `archive`);
3. prove per-user Gio default association mutation and resolution for all six categories on the staged image;
4. rerun the image/Wayland gate before the Default Apps portion can be called complete.

No roadmap checkbox or project percentage changes solely because these registrations exist.
