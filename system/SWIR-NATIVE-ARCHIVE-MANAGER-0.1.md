# SWIR Native Archive Manager 0.1

`system/apps/swir-archive-manager.py` is the first-party native GTK4 archive inspector/extractor for SWIR OS System Edition. It is deliberately unprivileged and treats archive extraction as a hostile-input boundary rather than calling a shell or a general-purpose unpack command.

## Verified scope

The implementation and dedicated CI gate are required to verify:

- a real `dev.swir.ArchiveManager` GTK4 window under Wayland;
- canonical readable local archive input only; remote/URI input and symlink-traversing source paths are rejected;
- ZIP plus TAR/TAR.GZ/TGZ/TAR.XZ/TXZ/TAR.BZ2/TBZ2 inspection using Python's distribution-managed standard library;
- a 512 MiB compressed input bound, 5,000-entry bound, 512 MiB per-file bound and 2 GiB total expanded-data bound;
- full member-table validation before extraction begins;
- rejection of absolute paths, `..` traversal, overlong paths, ZIP symlink entries, encrypted ZIP members, TAR symlinks/hardlinks/devices/FIFOs and other special members;
- extraction only into a newly created directory below a user-selected canonical writable parent;
- directory traversal through `dir_fd` plus `O_NOFOLLOW`, and regular-file creation with `O_EXCL | O_NOFOLLOW`, owner-only file mode `0600` and directory mode `0700`;
- no overwrite of pre-existing extraction targets;
- no `sudo`, `pkexec`, shell execution, package mutation or self-updater;
- desktop MIME integration and installation into the trusted graphical System Edition image path;
- exact Debian 13 GTK4/Python target-runtime verification.

## Safety boundaries

Extraction intentionally fails closed if any member violates the policy. If an I/O failure occurs after the new extraction directory has been created, Archive Manager does not claim a rollback that it cannot prove; the partial new directory is left visible for inspection instead of recursively deleting paths that could have changed concurrently.

The application does not execute archive contents, preserve setuid/setgid bits, create device nodes, reproduce archive symlinks or download codecs/helpers. Archive parsing security updates remain on the signed System Edition Python/package path.

## Roadmap accounting

This foundation improves the native daily-use suite but does **not** by itself complete the broad `essential native Linux application suite for dependable daily use` deliverable. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist criteria are actually satisfied.
