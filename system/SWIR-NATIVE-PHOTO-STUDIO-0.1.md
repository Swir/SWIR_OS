# SWIR Native Photo Studio 0.1

`system/apps/swir-photo-studio.py` is the first-party native GTK4 image viewer/editor for SWIR OS System Edition. It is deliberately unprivileged and non-destructive: opening an image never mutates the source, edits remain in bounded memory history, and saving always uses an explicit export copy.

## Verified scope

The implementation is required to provide and the dedicated CI gate verifies:

- a real `dev.swir.PhotoStudio` GTK4 window under Wayland;
- local regular image input only, with remote/URI text and symlink-traversing source paths rejected;
- a 64 MiB input-file bound and a 40 megapixel decoded/edit-result bound;
- common PNG, JPEG, WebP, GIF, BMP and TIFF input through distro-managed GdkPixbuf loaders;
- rotate left/right, horizontal/vertical flip and bounded resize operations;
- bounded 24-state undo/redo history;
- explicit PNG/JPEG/WebP export copies using same-directory temporary files, `fsync`, atomic replacement and owner-only mode `0600`;
- source bytes remaining unchanged through the edit/export E2E path;
- no `sudo`, `pkexec`, arbitrary shell execution, package mutation or self-updater;
- desktop MIME integration and installation into the trusted graphical System Edition image path;
- exact Debian 13 GTK4/GdkPixbuf target-runtime verification.

## Safety boundaries

Photo Studio is a user-session application. Codec/loader security updates remain on the signed System Edition package/update path. The application does not download image codecs, plugins or binaries itself and does not gain elevated privileges for file access.

The initial milestone intentionally focuses on dependable basic editing rather than pretending to be a professional raster suite. Layers, paint brushes, RAW-development, filters, metadata editing and cloud sync are outside this 0.1 scope.

## Roadmap accounting

The dedicated roadmap item `native SWIR Photo Studio with dependable basic editing, undo/redo and common-format export` can be marked complete only after the exact implementation head passes the Photo Studio policy, Wayland runtime and Debian 13 target-runtime jobs together with the affected System Edition integration gates. This item does not complete the broader `essential native Linux application suite for dependable daily use` deliverable.
