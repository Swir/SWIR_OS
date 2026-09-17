#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
SWIR OS System Edition install engine

Usage:
  swir-install-engine.sh preview --target <stable-disk-path>
  swir-install-engine.sh cancel --target <stable-disk-path>
  swir-install-engine.sh install --target <stable-disk-path> --confirmation <token>

The preview and cancel commands are read-only. The install command erases the
selected target only after the exact target-bound confirmation token emitted by
preview is supplied.
USAGE
}

fail() { echo "swir-install-engine: $*" >&2; exit 2; }
command_required() { command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"; }

for cmd in findmnt lsblk readlink sha256sum python3; do command_required "$cmd"; done

MODE="${1:-}"
[[ "$MODE" == preview || "$MODE" == cancel || "$MODE" == install ]] || { usage >&2; exit 2; }
shift || true
TARGET_SPEC=""
CONFIRMATION=""
KERNEL_OPTIONS="${SWIR_INSTALLER_KERNEL_OPTIONS:-root=LABEL=SWIR_ROOT rw quiet splash}"
[[ "$KERNEL_OPTIONS" != *$'\n'* && "$KERNEL_OPTIONS" != *$'\r'* ]] || fail "kernel options contain a newline"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) [[ $# -ge 2 ]] || fail "--target requires a value"; TARGET_SPEC="$2"; shift 2 ;;
    --confirmation) [[ $# -ge 2 ]] || fail "--confirmation requires a value"; CONFIRMATION="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done
[[ -n "$TARGET_SPEC" ]] || fail "--target is required"
[[ "$TARGET_SPEC" == /dev/disk/by-id/* || "${SWIR_INSTALLER_ALLOW_UNSTABLE_TARGET:-0}" == 1 ]] || fail "target must use a stable /dev/disk/by-id/* path"
[[ -e "$TARGET_SPEC" ]] || fail "target path does not exist: $TARGET_SPEC"
TARGET="$(readlink -f "$TARGET_SPEC")"
[[ -b "$TARGET" ]] || fail "target is not a block device: $TARGET"
[[ "$(lsblk -ndo TYPE "$TARGET" | tr -d '[:space:]')" == disk ]] || fail "target must be a whole disk"
[[ "$(lsblk -ndo RO "$TARGET" | tr -d '[:space:]')" == 0 ]] || fail "target is read-only"

ROOT_SOURCE="$(findmnt -n -o SOURCE / || true)"
[[ "$ROOT_SOURCE" == /dev/* ]] || fail "cannot identify live source block device from root mount: $ROOT_SOURCE"
ROOT_SOURCE="$(readlink -f "$ROOT_SOURCE")"
SOURCE_TYPE="$(lsblk -ndo TYPE "$ROOT_SOURCE" | tr -d '[:space:]')"
SOURCE_DISK="$ROOT_SOURCE"
if [[ "$SOURCE_TYPE" == part ]]; then
  SOURCE_PARENT="$(lsblk -ndo PKNAME "$ROOT_SOURCE" | tr -d '[:space:]')"
  [[ -n "$SOURCE_PARENT" ]] || fail "cannot identify source-media parent disk"
  SOURCE_DISK="/dev/$SOURCE_PARENT"
fi
[[ "$SOURCE_DISK" != "$TARGET" ]] || fail "refusing to install onto the currently booted source media"

# Reject every active use of the target, including mounted filesystems and swap.
# MOUNTPOINTS is deliberately used instead of MOUNTPOINT so multiple consumers
# cannot be hidden by a single-field view.
if lsblk -nrpo MOUNTPOINTS "$TARGET" | grep -Eq '[^[:space:]]'; then
  fail "target disk or one of its partitions is mounted or active"
fi

# Preview/cancel are intentionally usable by the unprivileged GTK session. Read
# size from sysfs through lsblk rather than opening the block device via blockdev;
# the destructive install path is still root-only below.
SIZE_BYTES="$(lsblk -bdno SIZE "$TARGET" | tr -d '[:space:]')"
[[ "$SIZE_BYTES" =~ ^[0-9]+$ ]] || fail "cannot determine target size"
MIN_BYTES=$((6 * 1024 * 1024 * 1024))
(( SIZE_BYTES >= MIN_BYTES )) || fail "target is smaller than 6 GiB"
SERIAL="$(lsblk -ndo SERIAL "$TARGET" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
WWN="$(lsblk -ndo WWN "$TARGET" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
MODEL="$(lsblk -ndo MODEL "$TARGET" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
[[ -n "$SERIAL$WWN" || "$TARGET_SPEC" == /dev/disk/by-id/* ]] || fail "target lacks a stable identity"
IDENTITY="${SERIAL:-${WWN:-$TARGET_SPEC}}"
TOKEN_DIGEST="$(printf 'swir-install-v1\n%s\n%s\n%s\n' "$IDENTITY" "$SIZE_BYTES" "$TARGET" | sha256sum | awk '{print $1}')"
TOKEN="ERASE-SWIR-${TOKEN_DIGEST:0:12}"

emit_preview() {
  python3 - "$TARGET_SPEC" "$TARGET" "$SOURCE_DISK" "$SIZE_BYTES" "$SERIAL" "$WWN" "$MODEL" "$TOKEN" <<'PY'
import json, sys
stable, target, source, size, serial, wwn, model, token = sys.argv[1:]
print(json.dumps({
  "schema": "swir.system-install-plan/0.1",
  "mode": "preview",
  "sourceDisk": source,
  "targetStablePath": stable,
  "targetDevice": target,
  "targetSizeBytes": int(size),
  "targetSerial": serial or None,
  "targetWwn": wwn or None,
  "targetModel": model or None,
  "destructiveWritePerformed": False,
  "requiresExplicitConfirmation": True,
  "canCancelBeforeDestructiveWrite": True,
  "confirmationToken": token,
  "partitionPlan": [
    {"number": 1, "role": "esp", "filesystem": "fat32", "label": "SWIR_ESP", "sizeMiB": 512},
    {"number": 2, "role": "system", "filesystem": "ext4", "label": "SWIR_ROOT", "size": "remaining"},
  ],
}, sort_keys=True))
PY
}

if [[ "$MODE" == preview ]]; then
  emit_preview
  exit 0
fi

if [[ "$MODE" == cancel ]]; then
  python3 - "$TARGET_SPEC" "$TARGET" "$SOURCE_DISK" "$SIZE_BYTES" <<'PY'
import json, sys
stable, target, source, size = sys.argv[1:]
print(json.dumps({
  "schema": "swir.system-install-plan/0.1",
  "mode": "cancel",
  "sourceDisk": source,
  "targetStablePath": stable,
  "targetDevice": target,
  "targetSizeBytes": int(size),
  "cancelled": True,
  "destructiveWritePerformed": False,
}, sort_keys=True))
PY
  exit 0
fi

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "install requires root privileges"
[[ -n "$CONFIRMATION" ]] || fail "--confirmation is required for install"
[[ "$CONFIRMATION" == "$TOKEN" ]] || fail "confirmation token does not match the current target identity"
for cmd in parted partprobe udevadm wipefs mkfs.vfat mkfs.ext4 mount umount rsync install sync stat; do command_required "$cmd"; done

WORK_ROOT="/run/swir-installer/$$"
ROOT_MOUNT="$WORK_ROOT/root"
ESP_MOUNT="$ROOT_MOUNT/boot/efi"
mkdir -p "$ROOT_MOUNT"
ROOT_MOUNTED=0
ESP_MOUNTED=0
cleanup() {
  set +e
  if [[ $ESP_MOUNTED -eq 1 ]]; then umount "$ESP_MOUNT" 2>/dev/null || true; fi
  if [[ $ROOT_MOUNTED -eq 1 ]]; then umount "$ROOT_MOUNT" 2>/dev/null || true; fi
  rm -rf "$WORK_ROOT"
}
trap cleanup EXIT

part_path() {
  local disk="$1" number="$2"
  if [[ "$disk" =~ [0-9]$ ]]; then printf '%sp%s' "$disk" "$number"; else printf '%s%s' "$disk" "$number"; fi
}

wipefs -a "$TARGET" >/dev/null
parted -s "$TARGET" mklabel gpt
parted -s "$TARGET" mkpart ESP fat32 1MiB 513MiB
parted -s "$TARGET" set 1 esp on
parted -s "$TARGET" mkpart SWIR_ROOT ext4 513MiB 100%
partprobe "$TARGET"
udevadm settle
ESP_PART="$(part_path "$TARGET" 1)"
ROOT_PART="$(part_path "$TARGET" 2)"
[[ -b "$ESP_PART" && -b "$ROOT_PART" ]] || fail "partition nodes were not created"
mkfs.vfat -F 32 -n SWIR_ESP "$ESP_PART" >/dev/null
mkfs.ext4 -q -F -L SWIR_ROOT "$ROOT_PART"
mount "$ROOT_PART" "$ROOT_MOUNT"
ROOT_MOUNTED=1
mkdir -p "$ESP_MOUNT"
mount "$ESP_PART" "$ESP_MOUNT"
ESP_MOUNTED=1

rsync -aHAX --numeric-ids --one-file-system \
  --exclude='/boot/efi/*' --exclude='/dev/*' --exclude='/proc/*' --exclude='/sys/*' \
  --exclude='/run/*' --exclude='/tmp/*' --exclude='/mnt/*' --exclude='/media/*' \
  / "$ROOT_MOUNT/"
chown 0:0 "$ROOT_MOUNT"
chmod 0755 "$ROOT_MOUNT"

# An installed system must not retain Live-media identity. Keep explicit E2E
# persistence fixtures elsewhere, but remove the production Live marker and
# force systemd to generate a fresh machine ID on first installed boot.
rm -rf "$ROOT_MOUNT/var/lib/swir/live"
: > "$ROOT_MOUNT/etc/machine-id"
if [[ -e "$ROOT_MOUNT/var/lib/dbus/machine-id" && ! -L "$ROOT_MOUNT/var/lib/dbus/machine-id" ]]; then
  rm -f "$ROOT_MOUNT/var/lib/dbus/machine-id"
  ln -s /etc/machine-id "$ROOT_MOUNT/var/lib/dbus/machine-id"
fi

printf 'LABEL=SWIR_ROOT / ext4 defaults 0 1\nLABEL=SWIR_ESP /boot/efi vfat umask=0077 0 2\n' > "$ROOT_MOUNT/etc/fstab"
mkdir -p "$ROOT_MOUNT/var/lib/swir/install"
python3 - "$ROOT_MOUNT/var/lib/swir/install/install.json" "$IDENTITY" "$SIZE_BYTES" <<'PY'
import datetime, json, pathlib, sys
out, identity, size = sys.argv[1:]
pathlib.Path(out).write_text(json.dumps({
  "schema": "swir.system-install-result/0.1",
  "installedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "targetIdentity": identity,
  "targetSizeBytes": int(size),
  "rootFilesystemLabel": "SWIR_ROOT",
  "espFilesystemLabel": "SWIR_ESP",
  "bootloader": "systemd-boot",
}, sort_keys=True) + "\n", encoding="utf-8")
PY
chmod 0600 "$ROOT_MOUNT/var/lib/swir/install/install.json"

EFI_SOURCE="/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
[[ -f "$EFI_SOURCE" && ! -L "$EFI_SOURCE" ]] || fail "systemd-boot EFI binary is unavailable in the live environment"
KERNEL="$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' | sort -V | tail -n1)"
INITRD="$(find /boot -maxdepth 1 -type f -name 'initrd.img-*' | sort -V | tail -n1)"
[[ -n "$KERNEL" && -n "$INITRD" ]] || fail "kernel/initrd are unavailable in the live environment"
mkdir -p "$ESP_MOUNT/EFI/BOOT" "$ESP_MOUNT/EFI/systemd" "$ESP_MOUNT/EFI/Linux" "$ESP_MOUNT/loader/entries"
install -m 0644 "$EFI_SOURCE" "$ESP_MOUNT/EFI/BOOT/BOOTX64.EFI"
install -m 0644 "$EFI_SOURCE" "$ESP_MOUNT/EFI/systemd/systemd-bootx64.efi"
install -m 0644 "$KERNEL" "$ESP_MOUNT/EFI/Linux/swir-vmlinuz"
install -m 0644 "$INITRD" "$ESP_MOUNT/EFI/Linux/swir-initrd.img"
cat > "$ESP_MOUNT/loader/loader.conf" <<'LOADER'
default swir-system.conf
timeout 2
console-mode keep
editor no
LOADER
cat > "$ESP_MOUNT/loader/entries/swir-system.conf" <<'ENTRY'
title SWIR OS System Edition
linux /EFI/Linux/swir-vmlinuz
initrd /EFI/Linux/swir-initrd.img
ENTRY
printf 'options %s\n' "$KERNEL_OPTIONS" >> "$ESP_MOUNT/loader/entries/swir-system.conf"
sync

python3 - "$TARGET_SPEC" "$TARGET" "$IDENTITY" "$SIZE_BYTES" <<'PY'
import json, sys
stable, target, identity, size = sys.argv[1:]
print(json.dumps({
  "schema": "swir.system-install-result/0.1",
  "status": "installed",
  "targetStablePath": stable,
  "targetDevice": target,
  "targetIdentity": identity,
  "targetSizeBytes": int(size),
  "sourceMediaProtected": True,
  "explicitConfirmationVerified": True,
  "rootFilesystemLabel": "SWIR_ROOT",
  "espFilesystemLabel": "SWIR_ESP",
  "bootloader": "systemd-boot",
}, sort_keys=True))
PY
