# SWIR Native Photo Studio 0.2

`system/apps/swir-photo-studio.py` is the first-party native GTK4 image viewer/editor for SWIR OS System Edition. It is deliberately unprivileged and non-destructive: opening an image never mutates the source, edits remain in bounded memory history, and saving always uses an explicit export copy.

## Verified scope

The implementation is required to provide and the dedicated CI gate verifies:

- a real `dev.swir.PhotoStudio` GTK4 window under Wayland;
- local regular image input only, with remote/URI text and symlink-traversing source paths rejected;
- a 64 MiB input-file bound and a 40 megapixel decoded/edit-result bound;
- common PNG, JPEG, WebP, GIF, BMP and TIFF input through distro-managed GdkPixbuf loaders;
- rotate left/right, horizontal/vertical flip and bounded resize operations;
- bounded center-crop with explicit out-of-bounds rejection;
- bounded exposure, brightness, contrast and saturation adjustments implemented in memory without spawning external image tools;
- grayscale and sepia filters that preserve the image alpha channel;
- bounded 24-state undo/redo history across basic and advanced edits;
- explicit PNG/JPEG/WebP export copies using same-directory temporary files, `fsync`, atomic replacement and owner-only mode `0600`;
- source bytes remaining unchanged through the full edit/export E2E path;
- no `sudo`, `pkexec`, arbitrary shell execution, package mutation, external image-processing commands or self-updater;
- desktop MIME integration and installation into the trusted graphical System Edition image path;
- exact Debian 13 GTK4/GdkPixbuf target-runtime verification.

## Editing model and safety boundaries

Photo Studio is a user-session application. Pixel adjustments use only memory owned by the process and create a fresh GdkPixbuf result before that result is pushed into bounded history. Exposure is limited to ±2 EV, brightness to ±1.0, contrast to `-0.9..2.0`, saturation to `-1.0..2.0`, and crop rectangles must remain fully inside the decoded image bounds. The same 40 megapixel ceiling applies to edit results.

Codec/loader security updates remain on the signed System Edition package/update path. The application does not download image codecs, plugins, filters or binaries itself and does not gain elevated privileges for file access. Source files remain read-only and exports are explicit copies.

The 0.2 milestone extends dependable everyday editing without pretending to be a professional raster suite. Freehand painting, layer compositing, RAW development, arbitrary text/font rendering, metadata mutation and cloud sync remain outside the verified scope.

## Runtime evidence

The Wayland E2E contract emits `swir.native-photo-studio-runtime-evidence/0.2` and fails closed unless it verifies, in one mapped GTK4 session:

- source immutability;
- undo/redo, rotate, resize and crop;
- exposure, brightness, contrast and saturation producing real pixel changes;
- grayscale producing equal RGB channels and sepia producing a distinct warm result;
- PNG and JPEG export with atomic replacement and mode `0600`;
- no privileged operation, external image command or self-update path.

The deterministic self-test additionally checks invalid crop rejection, out-of-range exposure rejection, remote URI rejection, symlink source rejection and symlink export rejection.

## Roadmap accounting

The dedicated roadmap item `native SWIR Photo Studio with dependable basic editing, undo/redo and common-format export` remains complete because 0.2 is a verified expansion of that already-completed milestone, not a new roadmap checkbox. This enhancement therefore does **not** increase the project percentage by itself and does not complete the broader `essential native Linux application suite for dependable daily use` deliverable.
