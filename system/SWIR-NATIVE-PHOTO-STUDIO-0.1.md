# SWIR Native Photo Studio 0.3

`system/apps/swir-photo-studio.py` is the first-party native GTK4 image viewer/editor for SWIR OS System Edition. It is deliberately unprivileged and non-destructive: opening an image never mutates the source, edits remain in bounded memory history, and saving always uses an explicit export copy.

## Verified scope

The implementation and dedicated CI gate verify:

- a real `dev.swir.PhotoStudio` GTK4 window under Wayland;
- local regular image input only, with remote/URI text and symlink-traversing source paths rejected;
- a 64 MiB input-file bound and a 40 megapixel decoded/edit-result bound;
- common PNG, JPEG, WebP, GIF, BMP and TIFF input through distro-managed GdkPixbuf loaders;
- rotate left/right, horizontal/vertical flip and bounded resize operations;
- both bounded center crop and user-selectable rectangular crop with explicit out-of-bounds rejection;
- bounded exposure, brightness, contrast and saturation adjustments implemented in memory without spawning external image tools;
- grayscale and sepia filters that preserve the image alpha channel;
- bounded text annotation using a deterministic embedded 5x7 glyph set (`A-Z`, digits and a small safe punctuation subset), maximum 64 characters and scale `1..6`;
- bounded line/drawing annotation with in-image endpoints and width `1..12`, using the SWIR cyan annotation color;
- bounded 24-state undo/redo history across basic, color, crop and annotation edits;
- explicit PNG/JPEG/WebP export copies using same-directory temporary files, `fsync`, atomic replacement and owner-only mode `0600`;
- source bytes remaining unchanged through the full edit/export E2E path;
- no `sudo`, `pkexec`, arbitrary shell execution, package mutation, external image-processing commands or self-updater;
- desktop MIME integration and installation into the trusted graphical System Edition image path;
- exact Debian 13 GTK4/GdkPixbuf target-runtime verification.

## Editing model and safety boundaries

Photo Studio is a user-session application. Pixel adjustments and annotations operate only on process-owned memory and create a fresh GdkPixbuf result before it is pushed into bounded history. Exposure is limited to ±2 EV, brightness to ±1.0, contrast to `-0.9..2.0`, saturation to `-1.0..2.0`, and every crop rectangle must remain fully inside decoded image bounds. The same 40 megapixel ceiling applies to edit results.

Text is deliberately bounded instead of loading arbitrary remote fonts or plugins. Input is normalized to uppercase ASCII and rejected if it contains controls, unsupported characters, exceeds 64 characters, or cannot fit fully inside the image at the selected origin/scale. Line annotation similarly rejects out-of-image endpoints and oversized brush widths. Both operations preserve the existing alpha channel.

Codec/loader security updates remain on the signed System Edition package/update path. The application does not download image codecs, plugins, filters, fonts or binaries itself and does not gain elevated privileges for file access. Source files remain read-only and exports are explicit copies.

The 0.3 milestone now covers the dependable Product Baseline editing set: crop, rotate/flip, resize, exposure/brightness/contrast, color control, filters, text, drawing/annotation, undo/redo and common-format export. Layer compositing, RAW development, arbitrary font loading, metadata mutation and cloud sync remain outside this baseline.

## Runtime evidence

The Wayland E2E contract emits `swir.native-photo-studio-runtime-evidence/0.4` and fails closed unless one mapped GTK4 session verifies:

- the owner-only SWIR language preference drives reviewed English, Polish and Norwegian Bokmål primary controls with deterministic English fallback, applied LTR/RTL direction, keyboard-focusable controls and localized tooltips;
- source immutability;
- undo/redo, rotate, resize and a non-default rectangular crop;
- exposure, brightness, contrast and saturation producing real pixel changes;
- grayscale producing equal RGB channels and sepia producing a distinct warm result;
- bounded text annotation producing real pixel changes;
- bounded line drawing producing real pixel changes;
- PNG and JPEG export with atomic replacement and mode `0600`;
- no privileged operation, external image command or self-update path.

The deterministic self-test additionally checks invalid crop rejection, out-of-range exposure rejection, empty/control/non-ASCII/oversized annotation text rejection, out-of-bounds line rejection, excessive line width rejection, remote URI rejection, symlink source rejection and symlink export rejection.

## Roadmap accounting

The dedicated roadmap item `native SWIR Photo Studio with dependable basic editing, undo/redo and common-format export` remains complete because 0.3 is a verified expansion of that already-completed milestone, not a new roadmap checkbox.

Photo Studio is no longer the known Product Baseline feature-depth blocker for the umbrella `essential native Linux application suite for dependable daily use` deliverable. That umbrella item is still kept open in this change until the native-suite gate explicitly re-audits every baseline capability and dedicated per-application evidence together; this Photo Studio milestone alone does **not** increase the project percentage.
