# SWIR Native PDF Viewer 0.1

`system/apps/swir-pdf-viewer.py` is the first-party native GTK4/Poppler PDF reader for SWIR OS System Edition. It is deliberately unprivileged and read-only: opening a document never mutates the source, never launches document content, and never downloads helper binaries or codecs.

## Verified scope

The implementation is required to provide and the dedicated CI gate verifies:

- a real `dev.swir.PdfViewer` GTK4 window under Wayland;
- local regular `.pdf` input only, with remote files and symlink source paths rejected;
- a 512 MiB source-file bound and a 4,000-page document bound;
- rendering through distro-managed Poppler GLib bindings and Cairo integration;
- previous/next page navigation and bounded 25%–400% zoom;
- source documents remaining read-only throughout the viewer path;
- no `sudo`, `pkexec`, arbitrary shell execution, package mutation or self-updater;
- `application/pdf` desktop MIME integration and a fixed SWIR Shell launcher;
- installation into the trusted graphical System Edition image path;
- exact Debian 13 GTK4/Poppler target-runtime verification.

## Safety boundaries

PDF Viewer is a user-session application. Poppler/Cairo security updates remain on the signed System Edition package/update path. The viewer never invokes embedded actions, scripts, attachments or external helpers; this 0.1 scope is document rendering/navigation only.

Encrypted/password-protected documents, annotations, form editing, signatures, OCR, attachment extraction and document mutation are outside the initial 0.1 scope. Their absence must not be presented as a completed advanced document-workflow feature.

## Roadmap accounting

This milestone advances the broader native daily-use application suite but does not by itself complete that umbrella roadmap deliverable. A separate roadmap item should only be marked complete if one already exists for this exact verified scope, or after the canonical roadmap is deliberately expanded without double-counting existing scope.
