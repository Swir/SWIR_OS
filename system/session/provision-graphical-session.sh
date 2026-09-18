#!/usr/bin/env bash
set -euo pipefail

ROOTFS=""
MODE="production"
SOURCE_ROOT=""
while (($#)); do
  case "$1" in
    --rootfs) ROOTFS="${2:-}"; shift 2 ;;
    --source-root) SOURCE_ROOT="${2:-}"; shift 2 ;;
    --e2e) MODE="e2e"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "graphical session provisioning requires root" >&2; exit 77; }
[[ -n "$ROOTFS" && "$ROOTFS" = /* && "$ROOTFS" != / ]] || { echo "--rootfs must be an absolute non-root path" >&2; exit 64; }
[[ -d "$ROOTFS" && ! -L "$ROOTFS" ]] || { echo "rootfs must be a real directory" >&2; exit 73; }
ROOTFS="$(readlink -f "$ROOTFS")"
[[ "$(stat -c '%u' "$ROOTFS")" = 0 ]] || { echo "rootfs must be root-owned" >&2; exit 78; }
(( (8#$(stat -c '%a' "$ROOTFS") & 8#022) == 0 )) || { echo "rootfs must not be group/world writable" >&2; exit 78; }
command -v node >/dev/null || { echo "host node runtime is required to stage the SWIR package UI runtime" >&2; exit 69; }

if [[ -z "$SOURCE_ROOT" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SOURCE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi
[[ "$SOURCE_ROOT" = /* && -d "$SOURCE_ROOT" && ! -L "$SOURCE_ROOT" ]] || { echo "source root invalid" >&2; exit 64; }
SOURCE_ROOT="$(readlink -f "$SOURCE_ROOT")"

for source_file in \
  system/session/swir-session-launcher.sh \
  system/session/swir-shell.py \
  system/apps/core_runtime.py \
  system/apps/hardware_center_runtime.py \
  system/apps/package_status_runtime.py \
  system/apps/package_transaction_client.py \
  system/apps/package_mutation_flow.py \
  system/apps/swir-browser.py \
  system/apps/swir-browser.desktop \
  system/apps/swir-player.py \
  system/apps/swir-player.desktop \
  system/apps/swir-photo-studio.py \
  system/apps/swir-photo-studio.desktop \
  system/apps/swir-pdf-viewer.py \
  system/apps/swir-pdf-viewer.desktop \
  system/apps/swir-calculator.py \
  system/apps/swir-calculator.desktop \
  system/apps/swir-files.py \
  system/apps/swir-hardware-center.py \
  system/apps/swir-network-center.py \
  system/apps/swir-notes.py \
  system/apps/swir-settings.py \
  system/apps/swir-software-center.py \
  system/apps/swir-system-monitor.py \
  system/apps/swir-terminal.py \
  system/apps/swir-update-center.py \
  system/hardware/hardware-service.mjs \
  system/hardware/driver-resolver.mjs \
  system/hardware/driver-center-service.mjs \
  system/hardware/driver-center-report.mjs \
  system/hardware/hardware-catalog.json \
  system/contracts/trusted-sources.json \
  system/image/stage-package-ui-runtime.mjs \
  system/image/system-package-ui-runtime-provisioning.mjs; do
  [[ -f "$SOURCE_ROOT/$source_file" && ! -L "$SOURCE_ROOT/$source_file" ]] || {
    echo "required trusted source file missing or symlinked: $source_file" >&2
    exit 69
  }
done

safe_target() {
  local rel="$1" dest current part
  [[ "$rel" == /* && "$rel" != / ]] || { echo "unsafe managed path: $rel" >&2; exit 73; }
  [[ "$rel" != *'/../'* && "$rel" != */.. && "$rel" != /..* ]] || { echo "unsafe managed path: $rel" >&2; exit 73; }
  dest="$ROOTFS$rel"
  current="$ROOTFS"
  IFS='/' read -r -a parts <<< "${rel#/}"
  for part in "${parts[@]}"; do
    [[ -n "$part" && "$part" != . && "$part" != .. ]] || { echo "unsafe managed path component: $rel" >&2; exit 73; }
    current="$current/$part"
    if [[ -L "$current" ]]; then echo "refusing symlink traversal: $rel" >&2; exit 73; fi
  done
  printf '%s\n' "$dest"
}

verify_trusted_regular_file() {
  local rel="$1" require_exec="${2:-no}" target file_mode
  target="$(safe_target "$rel")"
  [[ -f "$target" && ! -L "$target" ]] || { echo "required trusted file missing: $rel" >&2; exit 69; }
  [[ "$(stat -c '%u' "$target")" = 0 ]] || { echo "required trusted file must be root-owned: $rel" >&2; exit 78; }
  file_mode="$(stat -c '%a' "$target")"
  (( (8#$file_mode & 8#022) == 0 )) || { echo "required trusted file writable by group/world: $rel" >&2; exit 78; }
  if [[ "$require_exec" == yes && ! -x "$target" ]]; then
    echo "required trusted executable is not executable: $rel" >&2
    exit 69
  fi
}

ensure_exact_symlink() {
  local rel="$1" expected="$2" replaceable="${3:-}" parent dest current
  parent="$(dirname "$rel")"
  safe_target "$parent" >/dev/null
  dest="$ROOTFS$rel"
  if [[ -L "$dest" ]]; then
    current="$(readlink "$dest")"
    if [[ "$current" == "$expected" ]]; then return 0; fi
    case "|$replaceable|" in
      *"|$current|"*) rm -- "$dest" ;;
      *) echo "refusing unexpected managed symlink $rel -> $current" >&2; exit 73 ;;
    esac
  elif [[ -e "$dest" ]]; then
    echo "refusing to replace non-symlink managed path: $rel" >&2
    exit 73
  fi
  ln -s -- "$expected" "$dest"
  [[ -L "$dest" && "$(readlink "$dest")" == "$expected" ]] || { echo "failed to install trusted symlink: $rel" >&2; exit 70; }
}

# First-party UI runtimes are installed only from the configured signed Debian
# repositories. WebKitGTK, GStreamer, GdkPixbuf and Poppler are distro-managed
# so browser/media/image/document security updates stay in the SWIR
# package/update transaction path instead of ad-hoc application self-updaters.
RUNTIME_PACKAGES=(
  gir1.2-vte-3.91
  libvte-2.91-gtk4-0
  nodejs
  gir1.2-webkit-6.0
  gir1.2-gstreamer-1.0
  gir1.2-gdkpixbuf-2.0
  gir1.2-poppler-0.18
  python3-gi-cairo
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good
  gstreamer1.0-libav
  gstreamer1.0-gtk4
  desktop-file-utils
)
RUNTIME_MISSING=0
for pkg in "${RUNTIME_PACKAGES[@]}"; do
  chroot "$ROOTFS" dpkg-query -W -f='${db:Status-Abbrev}' "$pkg" 2>/dev/null | grep -qx 'ii ' || RUNTIME_MISSING=1
done
if [[ $RUNTIME_MISSING -eq 1 ]]; then
  chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${RUNTIME_PACKAGES[@]}"
fi

for pkg in greetd weston plymouth plymouth-themes wayland-utils dbus-user-session python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-vte-3.91 libvte-2.91-gtk4-0 gir1.2-webkit-6.0 gir1.2-gstreamer-1.0 gir1.2-gdkpixbuf-2.0 gir1.2-poppler-0.18 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-gtk4 network-manager nodejs desktop-file-utils; do
  chroot "$ROOTFS" dpkg-query -W -f='${db:Status-Abbrev}' "$pkg" 2>/dev/null | grep -qx 'ii ' || {
    echo "required graphical/runtime package is not installed: $pkg" >&2
    exit 69
  }
done
for file in /usr/sbin/greetd /usr/sbin/agreety /usr/bin/weston /usr/bin/wayland-info /usr/bin/plymouth /usr/sbin/plymouth-set-default-theme /usr/bin/python3.13 /usr/bin/node /usr/bin/nmcli /usr/bin/apt-cache /usr/bin/apt-get /usr/bin/dpkg-query /usr/bin/update-desktop-database; do
  verify_trusted_regular_file "$file" yes
done
[[ -L "$ROOTFS/usr/bin/python3" && "$(readlink "$ROOTFS/usr/bin/python3")" == python3.13 ]] || {
  echo "unexpected Debian 13 python3 interpreter symlink" >&2
  exit 69
}
verify_trusted_regular_file /usr/lib/systemd/system/greetd.service no
verify_trusted_regular_file /usr/lib/systemd/system/graphical.target no

node "$SOURCE_ROOT/system/image/stage-package-ui-runtime.mjs" \
  --rootfs "$ROOTFS" \
  --source-root "$SOURCE_ROOT" \
  --production

install -d -m 0755 \
  "$(safe_target /etc/greetd)" \
  "$(safe_target /usr/local/bin)" \
  "$(safe_target /usr/local/lib/swir)" \
  "$(safe_target /usr/local/lib/swir/hardware)" \
  "$(safe_target /usr/local/lib/swir/contracts)" \
  "$(safe_target /usr/share/applications)" \
  "$(safe_target /usr/share/wayland-sessions)" \
  "$(safe_target /usr/share/plymouth/themes/swir)" \
  "$(safe_target /etc/systemd/system/graphical.target.wants)"

install -m 0755 "$SOURCE_ROOT/system/session/swir-session-launcher.sh" "$(safe_target /usr/local/bin/swir-session)"
install -m 0755 "$SOURCE_ROOT/system/session/swir-shell.py" "$(safe_target /usr/local/bin/swir-shell)"
install -m 0644 "$SOURCE_ROOT/system/apps/core_runtime.py" "$(safe_target /usr/local/lib/swir/core_runtime.py)"
install -m 0644 "$SOURCE_ROOT/system/apps/hardware_center_runtime.py" "$(safe_target /usr/local/lib/swir/hardware_center_runtime.py)"
install -m 0644 "$SOURCE_ROOT/system/apps/package_status_runtime.py" "$(safe_target /usr/local/lib/swir/package_status_runtime.py)"
install -m 0644 "$SOURCE_ROOT/system/apps/package_transaction_client.py" "$(safe_target /usr/local/lib/swir/package_transaction_client.py)"
install -m 0644 "$SOURCE_ROOT/system/apps/package_mutation_flow.py" "$(safe_target /usr/local/lib/swir/package_mutation_flow.py)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-browser.py" "$(safe_target /usr/local/bin/swir-browser)"
install -m 0644 "$SOURCE_ROOT/system/apps/swir-browser.desktop" "$(safe_target /usr/share/applications/swir-browser.desktop)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-player.py" "$(safe_target /usr/local/bin/swir-player)"
install -m 0644 "$SOURCE_ROOT/system/apps/swir-player.desktop" "$(safe_target /usr/share/applications/swir-player.desktop)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-photo-studio.py" "$(safe_target /usr/local/bin/swir-photo-studio)"
install -m 0644 "$SOURCE_ROOT/system/apps/swir-photo-studio.desktop" "$(safe_target /usr/share/applications/swir-photo-studio.desktop)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-pdf-viewer.py" "$(safe_target /usr/local/bin/swir-pdf-viewer)"
install -m 0644 "$SOURCE_ROOT/system/apps/swir-pdf-viewer.desktop" "$(safe_target /usr/share/applications/swir-pdf-viewer.desktop)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-calculator.py" "$(safe_target /usr/local/bin/swir-calculator)"
install -m 0644 "$SOURCE_ROOT/system/apps/swir-calculator.desktop" "$(safe_target /usr/share/applications/swir-calculator.desktop)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-files.py" "$(safe_target /usr/local/bin/swir-files)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-hardware-center.py" "$(safe_target /usr/local/bin/swir-hardware-center)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-network-center.py" "$(safe_target /usr/local/bin/swir-network-center)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-notes.py" "$(safe_target /usr/local/bin/swir-notes)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-settings.py" "$(safe_target /usr/local/bin/swir-settings)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-software-center.py" "$(safe_target /usr/local/bin/swir-software-center)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-system-monitor.py" "$(safe_target /usr/local/bin/swir-system-monitor)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-terminal.py" "$(safe_target /usr/local/bin/swir-terminal)"
install -m 0755 "$SOURCE_ROOT/system/apps/swir-update-center.py" "$(safe_target /usr/local/bin/swir-update-center)"
install -m 0644 "$SOURCE_ROOT/system/hardware/hardware-service.mjs" "$(safe_target /usr/local/lib/swir/hardware/hardware-service.mjs)"
install -m 0644 "$SOURCE_ROOT/system/hardware/driver-resolver.mjs" "$(safe_target /usr/local/lib/swir/hardware/driver-resolver.mjs)"
install -m 0644 "$SOURCE_ROOT/system/hardware/driver-center-service.mjs" "$(safe_target /usr/local/lib/swir/hardware/driver-center-service.mjs)"
install -m 0644 "$SOURCE_ROOT/system/hardware/driver-center-report.mjs" "$(safe_target /usr/local/lib/swir/hardware/driver-center-report.mjs)"
install -m 0644 "$SOURCE_ROOT/system/hardware/hardware-catalog.json" "$(safe_target /usr/local/lib/swir/hardware/hardware-catalog.json)"
install -m 0644 "$SOURCE_ROOT/system/contracts/trusted-sources.json" "$(safe_target /usr/local/lib/swir/contracts/trusted-sources.json)"
install -m 0644 "$SOURCE_ROOT/system/boot/plymouth/swir.plymouth" "$(safe_target /usr/share/plymouth/themes/swir/swir.plymouth)"
install -m 0644 "$SOURCE_ROOT/system/boot/plymouth/swir.script" "$(safe_target /usr/share/plymouth/themes/swir/swir.script)"
chroot "$ROOTFS" /usr/bin/python3 -m py_compile \
  /usr/local/bin/swir-shell \
  /usr/local/bin/swir-browser \
  /usr/local/bin/swir-player \
  /usr/local/bin/swir-photo-studio \
  /usr/local/bin/swir-pdf-viewer \
  /usr/local/bin/swir-calculator \
  /usr/local/bin/swir-files \
  /usr/local/bin/swir-hardware-center \
  /usr/local/bin/swir-network-center \
  /usr/local/bin/swir-notes \
  /usr/local/bin/swir-settings \
  /usr/local/bin/swir-software-center \
  /usr/local/bin/swir-system-monitor \
  /usr/local/bin/swir-terminal \
  /usr/local/bin/swir-update-center \
  /usr/local/lib/swir/core_runtime.py \
  /usr/local/lib/swir/hardware_center_runtime.py \
  /usr/local/lib/swir/package_status_runtime.py \
  /usr/local/lib/swir/package_transaction_client.py \
  /usr/local/lib/swir/package_mutation_flow.py
chroot "$ROOTFS" /usr/bin/update-desktop-database /usr/share/applications

cat > "$(safe_target /usr/share/wayland-sessions/swir.desktop)" <<'EOF'
[Desktop Entry]
Name=SWIR OS
Comment=SWIR OS System Edition native Wayland session
Exec=/usr/local/bin/swir-session
TryExec=/usr/local/bin/swir-session
Type=Application
DesktopNames=SWIR
EOF
chmod 0644 "$(safe_target /usr/share/wayland-sessions/swir.desktop)"

if [[ "$MODE" == production ]]; then
  cat > "$(safe_target /etc/greetd/config.toml)" <<'EOF'
[terminal]
vt = 7

[default_session]
command = "/usr/sbin/agreety --cmd /usr/local/bin/swir-session"
user = "_greetd"
EOF
else
  if ! chroot "$ROOTFS" /usr/bin/id -u swir-e2e >/dev/null 2>&1; then
    chroot "$ROOTFS" /usr/sbin/useradd --create-home --shell /bin/bash --user-group swir-e2e
  fi
  [[ "$(chroot "$ROOTFS" /usr/bin/id -u swir-e2e)" -ge 1000 ]] || { echo "E2E session account must be unprivileged" >&2; exit 70; }
  E2E_AUTH_VALUE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  printf 'swir-e2e:%s\n' "$E2E_AUTH_VALUE" | chroot "$ROOTFS" /usr/sbin/chpasswd
  install -m 0755 "$SOURCE_ROOT/system/session/greetd-e2e-greeter.py" "$(safe_target /usr/local/lib/swir/greetd-e2e-greeter.py)"
  cat > "$(safe_target /etc/greetd/config.toml)" <<EOF
[terminal]
vt = 7

[default_session]
command = "/usr/bin/env SWIR_E2E_USERNAME=swir-e2e SWIR_E2E_PASSWORD=$E2E_AUTH_VALUE /usr/local/lib/swir/greetd-e2e-greeter.py"
user = "_greetd"
EOF
fi
chmod 0644 "$(safe_target /etc/greetd/config.toml)"

ensure_exact_symlink /etc/systemd/system/display-manager.service /usr/lib/systemd/system/greetd.service
ensure_exact_symlink /etc/systemd/system/graphical.target.wants/greetd.service /usr/lib/systemd/system/greetd.service
ensure_exact_symlink /etc/systemd/system/default.target /usr/lib/systemd/system/graphical.target "/lib/systemd/system/graphical.target|/usr/lib/systemd/system/multi-user.target|/lib/systemd/system/multi-user.target"

chroot "$ROOTFS" /usr/sbin/plymouth-set-default-theme swir
[[ "$(chroot "$ROOTFS" /usr/sbin/plymouth-set-default-theme)" == swir ]] || { echo "SWIR Plymouth theme was not selected" >&2; exit 70; }
chroot "$ROOTFS" /usr/sbin/update-initramfs -u -k all

if [[ "$MODE" == production ]]; then
  grep -Fq '/usr/sbin/agreety --cmd /usr/local/bin/swir-session' "$ROOTFS/etc/greetd/config.toml" || {
    echo "production greetd configuration lost authenticated greeter path" >&2; exit 70;
  }
  ! grep -Fq 'SWIR_E2E_PASSWORD=' "$ROOTFS/etc/greetd/config.toml" || { echo "test authentication value leaked into production config" >&2; exit 70; }
fi
! grep -Fq '[initial_session]' "$ROOTFS/etc/greetd/config.toml" || { echo "autologin initial_session is forbidden" >&2; exit 70; }
[[ -f "$ROOTFS/etc/pam.d/greetd" && ! -L "$ROOTFS/etc/pam.d/greetd" ]] || { echo "greetd PAM policy missing" >&2; exit 70; }

verify_trusted_regular_file /usr/local/bin/swir-shell yes
verify_trusted_regular_file /usr/local/bin/swir-browser yes
verify_trusted_regular_file /usr/share/applications/swir-browser.desktop no
verify_trusted_regular_file /usr/local/bin/swir-player yes
verify_trusted_regular_file /usr/share/applications/swir-player.desktop no
verify_trusted_regular_file /usr/local/bin/swir-photo-studio yes
verify_trusted_regular_file /usr/share/applications/swir-photo-studio.desktop no
verify_trusted_regular_file /usr/local/bin/swir-pdf-viewer yes
verify_trusted_regular_file /usr/share/applications/swir-pdf-viewer.desktop no
verify_trusted_regular_file /usr/local/bin/swir-calculator yes
verify_trusted_regular_file /usr/share/applications/swir-calculator.desktop no
verify_trusted_regular_file /usr/local/bin/swir-files yes
verify_trusted_regular_file /usr/local/bin/swir-hardware-center yes
verify_trusted_regular_file /usr/local/bin/swir-network-center yes
verify_trusted_regular_file /usr/local/bin/swir-notes yes
verify_trusted_regular_file /usr/local/bin/swir-settings yes
verify_trusted_regular_file /usr/local/bin/swir-software-center yes
verify_trusted_regular_file /usr/local/bin/swir-system-monitor yes
verify_trusted_regular_file /usr/local/bin/swir-terminal yes
verify_trusted_regular_file /usr/local/bin/swir-update-center yes
verify_trusted_regular_file /usr/local/lib/swir/core_runtime.py no
verify_trusted_regular_file /usr/local/lib/swir/hardware_center_runtime.py no
verify_trusted_regular_file /usr/local/lib/swir/hardware/hardware-service.mjs no
verify_trusted_regular_file /usr/local/lib/swir/hardware/driver-resolver.mjs no
verify_trusted_regular_file /usr/local/lib/swir/hardware/driver-center-service.mjs no
verify_trusted_regular_file /usr/local/lib/swir/hardware/driver-center-report.mjs no
verify_trusted_regular_file /usr/local/lib/swir/hardware/hardware-catalog.json no
verify_trusted_regular_file /usr/local/lib/swir/contracts/trusted-sources.json no
verify_trusted_regular_file /usr/local/lib/swir/package_status_runtime.py no
verify_trusted_regular_file /usr/local/lib/swir/package_transaction_client.py no
verify_trusted_regular_file /usr/local/lib/swir/package_mutation_flow.py no
verify_trusted_regular_file /usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs no
verify_trusted_regular_file /usr/lib/systemd/system/swir-package-transaction.service no
verify_trusted_regular_file /usr/libexec/swir/swir-peer-authorization-broker yes

[[ -L "$ROOTFS/etc/systemd/system/multi-user.target.wants/swir-package-transaction.service" ]] || {
  echo "SWIR package transaction broker service is not enabled" >&2; exit 70;
}
[[ "$(readlink "$ROOTFS/etc/systemd/system/multi-user.target.wants/swir-package-transaction.service")" == /usr/lib/systemd/system/swir-package-transaction.service ]] || {
  echo "SWIR package transaction broker service target is unexpected" >&2; exit 70;
}

printf 'SWIR graphical session staged: mode=%s theme=swir login=greetd compositor=weston native-shell=gtk4 native-apps=browser,player,photo-studio,pdf-viewer,calculator,files,hardware,network,notes,settings,software,system-monitor,terminal,updates package-broker=peer-polkit-journaled\n' "$MODE"
