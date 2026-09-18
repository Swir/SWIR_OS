# SWIR Native Screenshot Tool 0.1

`system/apps/swir-screenshot.py` is an unprivileged GTK4 screenshot client for SWIR OS System Edition. It is intentionally designed around the XDG Desktop Portal boundary rather than compositor-specific capture binaries.

## Verified design

- production capture requests `org.freedesktop.portal.Screenshot.Screenshot` on the logged-in user's session bus;
- the request sets `interactive=true`, leaving screen/window/region selection and consent to the desktop portal;
- no `grim`, `scrot`, ImageMagick `import`, shell capture, DRM/framebuffer access, `sudo` or `pkexec` path exists;
- only a successful portal response with a local `file:` URI is accepted;
- portal results are rejected if they are remote, non-canonical, symlink-traversing, non-regular, unreadable, empty, larger than 64 MiB, undecodable, or above 40 megapixels;
- the accepted image is copied through an owner-only temporary file, `fsync`, atomic rename and final mode `0600`;
- normal output is `${XDG_PICTURES_DIR:-~/Pictures}/Screenshots/SWIR-Screenshot-YYYYMMDD-HHMMSS[-n].png`;
- the output directory must be owned by the logged-in user and must not be reached through a symlink;
- the GTK4 window previews only the verified local copy and performs no privileged operation or self-update.

## Runtime verification

`.github/workflows/system-native-screenshot-tool.yml` provides three gates:

1. static policy/self-test and desktop-entry validation;
2. a real GTK4 window mapped on headless Weston while a controlled session-D-Bus fake implements the standard Screenshot portal request/response protocol and returns a disposable local PNG;
3. Debian 13 (trixie) target-runtime verification.

The fake portal exists only in `system/tests/fake-screenshot-portal.py` for CI and is never installed into a System Edition image.

## Integration state

This milestone verifies the first-party screenshot application and its portal/security contract. Shipping integration into the canonical graphical image and SWIR shell launcher remains a separate required step; until that wiring is verified, this source milestone does **not** close the roadmap's full `essential native Linux application suite for dependable daily use` item and does not change the overall roadmap percentage.
