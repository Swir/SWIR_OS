#!/usr/bin/env bash
set -euo pipefail

ROOTFS=""
SOURCE_ROOT=""
while (($#)); do
  case "$1" in
    --rootfs) ROOTFS="${2:-}"; shift 2 ;;
    --source-root) SOURCE_ROOT="${2:-}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "installer provisioning requires root" >&2; exit 77; }
[[ -n "$ROOTFS" && "$ROOTFS" = /* && "$ROOTFS" != / && -d "$ROOTFS" && ! -L "$ROOTFS" ]] || { echo "--rootfs must be an absolute real directory" >&2; exit 64; }
ROOTFS="$(readlink -f "$ROOTFS")"
if [[ -z "$SOURCE_ROOT" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SOURCE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi
[[ "$SOURCE_ROOT" = /* && -d "$SOURCE_ROOT" && ! -L "$SOURCE_ROOT" ]] || { echo "source root invalid" >&2; exit 64; }
SOURCE_ROOT="$(readlink -f "$SOURCE_ROOT")"

safe_target() {
  local rel="$1" current part
  [[ "$rel" == /* && "$rel" != / && "$rel" != *'/../'* && "$rel" != */.. ]] || { echo "unsafe managed path: $rel" >&2; exit 73; }
  current="$ROOTFS"
  IFS='/' read -r -a parts <<< "${rel#/}"
  for part in "${parts[@]}"; do
    [[ -n "$part" && "$part" != . && "$part" != .. ]] || exit 73
    current="$current/$part"
    [[ ! -L "$current" ]] || { echo "refusing symlink traversal: $rel" >&2; exit 73; }
  done
  printf '%s\n' "$ROOTFS$rel"
}

for pkg in python3 python3-gi gir1.2-gtk-4.0 polkitd; do
  chroot "$ROOTFS" dpkg-query -W -f='${db:Status-Abbrev}' "$pkg" 2>/dev/null | grep -qx 'ii ' || {
    echo "required graphical installer package is not installed: $pkg" >&2
    exit 69
  }
done
[[ -x "$ROOTFS/usr/bin/python3" && -x "$ROOTFS/usr/bin/pkexec" ]] || { echo "python3/pkexec missing" >&2; exit 69; }

install -d -m 0755 \
  "$(safe_target /usr/local/bin)" \
  "$(safe_target /usr/local/libexec)" \
  "$(safe_target /usr/local/sbin)" \
  "$(safe_target /usr/share/applications)" \
  "$(safe_target /usr/share/polkit-1/actions)" \
  "$(safe_target /usr/share/icons/hicolor/scalable/apps)"

install -m 0755 "$SOURCE_ROOT/system/installer/swir-installer.py" "$(safe_target /usr/local/bin/swir-installer)"
install -m 0755 "$SOURCE_ROOT/system/installer/swir-installer-helper.py" "$(safe_target /usr/local/libexec/swir-installer-helper)"
install -m 0755 "$SOURCE_ROOT/system/installer/swir-install-engine.sh" "$(safe_target /usr/local/sbin/swir-install-engine)"
install -m 0644 "$SOURCE_ROOT/system/installer/swir-installer.desktop" "$(safe_target /usr/share/applications/swir-installer.desktop)"
install -m 0644 "$SOURCE_ROOT/system/installer/dev.swir.installer.policy" "$(safe_target /usr/share/polkit-1/actions/dev.swir.installer.policy)"
install -m 0644 "$SOURCE_ROOT/assets/branding/swir-os-logo.svg" "$(safe_target /usr/share/icons/hicolor/scalable/apps/swir-installer.svg)"

# Fail closed if the helper/policy was broadened into a generic root execution path.
python3 -m py_compile "$ROOTFS/usr/local/bin/swir-installer" "$ROOTFS/usr/local/libexec/swir-installer-helper"
grep -Fq '<action id="dev.swir.installer.install">' "$ROOTFS/usr/share/polkit-1/actions/dev.swir.installer.policy"
grep -Fq '<allow_any>no</allow_any>' "$ROOTFS/usr/share/polkit-1/actions/dev.swir.installer.policy"
grep -Fq '<allow_inactive>no</allow_inactive>' "$ROOTFS/usr/share/polkit-1/actions/dev.swir.installer.policy"
grep -Fq '/usr/local/libexec/swir-installer-helper' "$ROOTFS/usr/share/polkit-1/actions/dev.swir.installer.policy"
! grep -Eq '(/bin/sh|/bin/bash|shell=True|os\.system\()' "$ROOTFS/usr/local/libexec/swir-installer-helper"

chroot "$ROOTFS" /usr/bin/python3 /usr/local/bin/swir-installer --self-test
chroot "$ROOTFS" /usr/bin/python3 /usr/local/libexec/swir-installer-helper --self-test

echo "SWIR graphical installer staged: gtk4=true helper=narrow-polkit engine=guarded"
