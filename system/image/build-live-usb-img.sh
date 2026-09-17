#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: build-live-usb-img.sh --rootfs <dir> --output <img> [--size <bytes>]" >&2
}
fail() { echo "build-live-usb-img: $*" >&2; exit 2; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "must run as root"
ROOTFS=""; OUTPUT=""; SIZE_BYTES=$((8 * 1024 * 1024 * 1024)); KERNEL_OPTIONS="root=LABEL=SWIR_LIVE_ROOT rw quiet splash"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rootfs) ROOTFS="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --size) SIZE_BYTES="$2"; shift 2 ;;
    --kernel-options) KERNEL_OPTIONS="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done
[[ -n "$ROOTFS" && -d "$ROOTFS" ]] || fail "valid --rootfs is required"
[[ -n "$OUTPUT" ]] || fail "--output is required"
[[ "$SIZE_BYTES" =~ ^[0-9]+$ ]] || fail "--size must be an integer byte count"
[[ "$KERNEL_OPTIONS" != *$'\n'* && "$KERNEL_OPTIONS" != *$'\r'* ]] || fail "kernel options contain a newline"
(( SIZE_BYTES >= 6 * 1024 * 1024 * 1024 )) || fail "image must be at least 6 GiB"
for cmd in truncate losetup parted partprobe udevadm mkfs.vfat mkfs.ext4 mount umount rsync install find sort sha256sum stat; do
  command -v "$cmd" >/dev/null || fail "missing required command: $cmd"
done
EFI_SOURCE="$ROOTFS/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
[[ -f "$EFI_SOURCE" && ! -L "$EFI_SOURCE" ]] || fail "rootfs lacks systemd-bootx64.efi"
KERNEL="$(find "$ROOTFS/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | sort -V | tail -n1)"
INITRD="$(find "$ROOTFS/boot" -maxdepth 1 -type f -name 'initrd.img-*' | sort -V | tail -n1)"
[[ -n "$KERNEL" && -n "$INITRD" ]] || fail "rootfs lacks kernel/initrd"
mkdir -p "$(dirname "$OUTPUT")"
rm -f "$OUTPUT" "$OUTPUT.sha256"
truncate -s "$SIZE_BYTES" "$OUTPUT"
LOOP=""; ROOT_MOUNT="$(mktemp -d)"; ROOT_MOUNTED=0; ESP_MOUNTED=0
cleanup() {
  set +e
  [[ $ESP_MOUNTED -eq 1 ]] && umount "$ROOT_MOUNT/boot/efi" 2>/dev/null || true
  [[ $ROOT_MOUNTED -eq 1 ]] && umount "$ROOT_MOUNT" 2>/dev/null || true
  [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null || true
  rmdir "$ROOT_MOUNT" 2>/dev/null || true
}
trap cleanup EXIT
LOOP="$(losetup --find --show --partscan "$OUTPUT")"
parted -s "$LOOP" mklabel gpt
parted -s "$LOOP" mkpart ESP fat32 1MiB 513MiB
parted -s "$LOOP" set 1 esp on
parted -s "$LOOP" mkpart SWIR_LIVE_ROOT ext4 513MiB 100%
partprobe "$LOOP"; udevadm settle
ESP_PART="${LOOP}p1"; ROOT_PART="${LOOP}p2"
[[ -b "$ESP_PART" && -b "$ROOT_PART" ]] || fail "partition nodes were not created"
# FAT volume labels are limited to 11 characters. Keep this distinct from the
# installed-system ESP while remaining valid on firmware and dosfstools.
mkfs.vfat -F 32 -n SWIRLIVEESP "$ESP_PART" >/dev/null
mkfs.ext4 -q -F -L SWIR_LIVE_ROOT "$ROOT_PART"
mount "$ROOT_PART" "$ROOT_MOUNT"; ROOT_MOUNTED=1
mkdir -p "$ROOT_MOUNT/boot/efi"
mount "$ESP_PART" "$ROOT_MOUNT/boot/efi"; ESP_MOUNTED=1
rsync -aHAX --numeric-ids --exclude='/boot/efi/*' "$ROOTFS/" "$ROOT_MOUNT/"
chown 0:0 "$ROOT_MOUNT"; chmod 0755 "$ROOT_MOUNT"
printf 'LABEL=SWIR_LIVE_ROOT / ext4 defaults 0 1\nLABEL=SWIRLIVEESP /boot/efi vfat umask=0077 0 2\n' > "$ROOT_MOUNT/etc/fstab"
mkdir -p "$ROOT_MOUNT/var/lib/swir/live"
printf '%s\n' 'swir-live-media/0.1' > "$ROOT_MOUNT/var/lib/swir/live/media-version"
cat > "$ROOT_MOUNT/var/lib/swir/live/live.json" <<'JSON'
{
  "schema": "swir.live-media/0.1",
  "mode": "live",
  "installerAllowed": true,
  "readOnlyFirst": true
}
JSON
chown -R 0:0 "$ROOT_MOUNT/var/lib/swir/live"
chmod 0755 "$ROOT_MOUNT/var/lib/swir/live"
chmod 0644 "$ROOT_MOUNT/var/lib/swir/live/media-version" "$ROOT_MOUNT/var/lib/swir/live/live.json"
ESP="$ROOT_MOUNT/boot/efi"
mkdir -p "$ESP/EFI/BOOT" "$ESP/EFI/systemd" "$ESP/EFI/Linux" "$ESP/loader/entries"
install -m 0644 "$EFI_SOURCE" "$ESP/EFI/BOOT/BOOTX64.EFI"
install -m 0644 "$EFI_SOURCE" "$ESP/EFI/systemd/systemd-bootx64.efi"
install -m 0644 "$KERNEL" "$ESP/EFI/Linux/swir-vmlinuz"
install -m 0644 "$INITRD" "$ESP/EFI/Linux/swir-initrd.img"
cat > "$ESP/loader/loader.conf" <<'LOADER'
default swir-live.conf
timeout 3
console-mode keep
editor no
LOADER
cat > "$ESP/loader/entries/swir-live.conf" <<'ENTRY'
title SWIR OS System Edition — Live USB
linux /EFI/Linux/swir-vmlinuz
initrd /EFI/Linux/swir-initrd.img
ENTRY
printf 'options %s\n' "$KERNEL_OPTIONS" >> "$ESP/loader/entries/swir-live.conf"
sync
umount "$ESP"; ESP_MOUNTED=0
umount "$ROOT_MOUNT"; ROOT_MOUNTED=0
losetup -d "$LOOP"; LOOP=""
sha256sum "$OUTPUT" > "$OUTPUT.sha256"
printf 'SWIR Live USB IMG: %s\nSHA-256: %s\n' "$OUTPUT" "$(awk '{print $1}' "$OUTPUT.sha256")"
