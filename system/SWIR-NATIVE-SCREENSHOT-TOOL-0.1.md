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

`.github/workflows/system-native-screenshot-tool.yml` provides four gates:

1. static policy/self-test, desktop-entry validation and shell/provisioning syntax checks;
2. a shipping contract that requires the fixed SWIR shell launcher, trusted image staging, compile/ownership checks and absence of the fake CI portal from production provisioning;
3. a real GTK4 window mapped on headless Weston while a controlled session-D-Bus fake implements the standard Screenshot portal request/response protocol and returns a disposable local PNG;
4. Debian 13 (trixie) target-runtime verification.

The fake portal exists only in `system/tests/fake-screenshot-portal.py` for CI and is never installed into a System Edition image.

## Shipping integration

The canonical graphical System Edition provisioning path stages `swir-screenshot.py` as root-owned `/usr/local/bin/swir-screenshot`, installs its desktop entry below `/usr/share/applications`, compiles it with the target Python runtime and verifies both staged files before the image is accepted. The native SWIR shell exposes a fixed `Screenshot` launcher with no user-controlled shell interpolation.

The graphical UEFI E2E lane additionally requires the staged executable and desktop entry inside the disposable image and verifies that the mapped shell runtime evidence contains the `Screenshot` launcher. This proves packaging/launcher integration in the tested UEFI VM lane; it does not claim physical-hardware qualification or that every desktop portal backend is supported.

## Roadmap accounting

Shipping Screenshot Tool improves the native daily-use suite but does **not** by itself complete the broad `essential native Linux application suite for dependable daily use` deliverable. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist criteria are actually satisfied.
