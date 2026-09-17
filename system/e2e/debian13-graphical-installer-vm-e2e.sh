#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "debian13-graphical-installer-vm-e2e.sh must run as root" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROFILE="$REPO_ROOT/system/image/system-base-debian-trixie.json"
WORK_ROOT="${SWIR_GRAPHICAL_INSTALL_WORK_ROOT:-/tmp/swir-graphical-installer-e2e}"
ARTIFACT_DIR="${SWIR_GRAPHICAL_INSTALL_ARTIFACT_DIR:-$WORK_ROOT/artifacts}"
ROOTFS="$WORK_ROOT/rootfs"
LIVE_IMG="$WORK_ROOT/swir-live-usb.img"
TARGET_DISK="$WORK_ROOT/swir-target.raw"
SERIAL_LIVE="$ARTIFACT_DIR/graphical-installer-live.log"
SERIAL_INSTALLED="$ARTIFACT_DIR/graphical-installer-installed.log"
EVIDENCE="$ARTIFACT_DIR/graphical-installer-e2e.json"
OVMF_CODE="/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_VARS_TEMPLATE="/usr/share/OVMF/OVMF_VARS_4M.fd"
OVMF_VARS_LIVE="$WORK_ROOT/OVMF_VARS_live.fd"
OVMF_VARS_INSTALLED="$WORK_ROOT/OVMF_VARS_installed.fd"

case "$(readlink -m "$WORK_ROOT")" in
  /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/srv|/sys|/usr|/var)
    echo "refusing unsafe work root: $WORK_ROOT" >&2
    exit 3
    ;;
esac

for cmd in chroot mount umount qemu-system-x86_64 mkfs.ext4 mkfs.vfat rsync timeout grep install \
  losetup parted partprobe udevadm sha256sum python3 truncate; do
  command -v "$cmd" >/dev/null || { echo "missing required host command: $cmd" >&2; exit 4; }
done

[[ -f "$PROFILE" && ! -L "$PROFILE" ]] || { echo "Debian profile missing" >&2; exit 5; }
[[ -f "$OVMF_CODE" && ! -L "$OVMF_CODE" ]] || { echo "OVMF code firmware missing" >&2; exit 5; }
[[ -f "$OVMF_VARS_TEMPLATE" && ! -L "$OVMF_VARS_TEMPLATE" ]] || { echo "OVMF vars template missing" >&2; exit 5; }
[[ "$(dpkg --print-architecture)" == amd64 ]] || { echo "graphical installer E2E is amd64-only in 0.1" >&2; exit 6; }

rm -rf "$WORK_ROOT"
install -d -m 0700 "$WORK_ROOT" "$ARTIFACT_DIR" "$ROOTFS"
ROOTFS_MOUNTS=0
cleanup() {
  set +e
  if [[ $ROOTFS_MOUNTS -eq 1 ]]; then
    umount -R "$ROOTFS/dev" 2>/dev/null || true
    umount -R "$ROOTFS/sys" 2>/dev/null || true
    umount "$ROOTFS/proc" 2>/dev/null || true
  fi
}
trap cleanup EXIT

bash "$REPO_ROOT/system/image/build-debian-trixie-rootfs.sh" --rootfs "$ROOTFS" --profile "$PROFILE" --arch amd64
mount -t proc proc "$ROOTFS/proc"
mount --rbind /sys "$ROOTFS/sys"; mount --make-rslave "$ROOTFS/sys"
mount --rbind /dev "$ROOTFS/dev"; mount --make-rslave "$ROOTFS/dev"
ROOTFS_MOUNTS=1

cat > "$ROOTFS/usr/sbin/policy-rc.d" <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod 0755 "$ROOTFS/usr/sbin/policy-rc.d"

chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get update
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  systemd-boot-efi greetd weston plymouth plymouth-themes wayland-utils dbus-user-session \
  python3-gi gir1.2-gtk-4.0 \
  parted dosfstools e2fsprogs rsync util-linux udev
chroot "$ROOTFS" /usr/bin/systemd-machine-id-setup

bash "$REPO_ROOT/system/session/provision-graphical-session.sh" --rootfs "$ROOTFS" --source-root "$REPO_ROOT" --e2e
bash "$REPO_ROOT/system/installer/provision-graphical-installer.sh" --rootfs "$ROOTFS" --source-root "$REPO_ROOT"

# Test-only authorization injected into the disposable CI image. Normal Live
# media never contains this rule; it grants only the exact installer action to
# the pre-existing swir-e2e user so the real pkexec path can be exercised.
install -d -m 0755 "$ROOTFS/etc/polkit-1/rules.d"
cat > "$ROOTFS/etc/polkit-1/rules.d/00-swir-installer-e2e.rules" <<'RULE'
polkit.addRule(function(action, subject) {
    if (action.id == "dev.swir.installer.install" && subject.user == "swir-e2e") {
        return polkit.Result.YES;
    }
});
RULE
chmod 0644 "$ROOTFS/etc/polkit-1/rules.d/00-swir-installer-e2e.rules"

install -d -m 0700 "$ROOTFS/var/lib/swir/graphical-installer-e2e"
printf 'SWIR-GRAPHICAL-INSTALLER-PERSISTENCE-v1\n' > "$ROOTFS/var/lib/swir/graphical-installer-e2e/source-marker.txt"
chmod 0600 "$ROOTFS/var/lib/swir/graphical-installer-e2e/source-marker.txt"

cat > "$ROOTFS/usr/local/lib/swir/graphical-installer-e2e-run" <<'GUEST'
#!/bin/sh
set -eu
OUT=/var/lib/swir/graphical-installer-e2e
STATUS="$OUT/status.txt"
TARGET=/dev/disk/by-id/virtio-SWIR_TARGET_GUI_E2E
TEST_USER=swiruser
TEST_LOCALE=pl_PL.UTF-8
TEST_KEYBOARD=pl
TEST_TIMEZONE=Europe/Warsaw

serial() { printf '%s\n' "$*" > /dev/ttyS0; }
fail() {
  printf 'FAIL:%s\n' "$1" > "$STATUS"
  serial "SWIR_GRAPHICAL_INSTALLER_E2E_FAIL $1"
  systemctl --no-pager --full status greetd.service polkit.service > /dev/ttyS0 2>&1 || true
  journalctl -b --no-pager -n 220 -u greetd.service -u polkit.service -u swir-graphical-installer-e2e.service > /dev/ttyS0 2>&1 || true
  sync
  systemctl --no-block poweroff
  exit 1
}
wait_session() {
  i=0
  while [ "$i" -lt 120 ]; do
    for candidate in /run/user/*/swir-graphical-session-evidence.json; do
      [ -s "$candidate" ] && { cp "$candidate" "$OUT/session-$1.json"; chmod 0600 "$OUT/session-$1.json"; return 0; }
    done
    i=$((i + 1)); sleep 1
  done
  return 1
}
verify_user_config_root() {
  root="$1"
  python3 - "$root/var/lib/swir/install/user-config.json" "$TEST_USER" "$TEST_LOCALE" "$TEST_KEYBOARD" "$TEST_TIMEZONE" <<'PY'
import json, pathlib, sys
path, username, locale, keyboard, timezone = sys.argv[1:]
d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
assert d["schema"] == "swir.system-install-user-config/0.1"
assert d["username"] == username
assert d["locale"] == locale
assert d["keyboard"] == keyboard
assert d["timezone"] == timezone
assert d["passwordStoredInEvidence"] is False
assert "password" not in d
PY
  chroot "$root" /usr/bin/id -u "$TEST_USER" >/dev/null || return 1
  [ -d "$root/home/$TEST_USER" ] || return 1
  grep -Fxq "LANG=$TEST_LOCALE" "$root/etc/locale.conf" || return 1
  grep -Fq "XKBLAYOUT=\"$TEST_KEYBOARD\"" "$root/etc/default/keyboard" || return 1
  grep -Fxq "$TEST_TIMEZONE" "$root/etc/timezone" || return 1
  [ "$(readlink "$root/etc/localtime")" = "/usr/share/zoneinfo/$TEST_TIMEZONE" ] || return 1
}
rootdev="$(findmnt -n -o SOURCE /)"
rootlabel="$(lsblk -ndo LABEL "$rootdev" | tr -d '[:space:]')"
mkdir -p "$OUT"

if [ "$rootlabel" = SWIR_LIVE_ROOT ]; then
  serial 'SWIR_GRAPHICAL_INSTALLER_LIVE booted=true transport=usb-storage'
  systemctl is-active --quiet greetd.service || fail live-greetd-inactive
  systemctl is-active --quiet polkit.service || fail live-polkit-inactive
  wait_session live || fail live-graphical-session-timeout

  i=0
  while [ "$i" -lt 60 ] && [ ! -e "$TARGET" ]; do i=$((i + 1)); sleep 1; done
  [ -b "$TARGET" ] || fail target-by-id-missing
  target_real="$(readlink -f "$TARGET")"
  head_before="$(dd if="$target_real" bs=1M count=4 status=none | sha256sum | awk '{print $1}')"
  sleep 2
  head_idle="$(dd if="$target_real" bs=1M count=4 status=none | sha256sum | awk '{print $1}')"
  [ "$head_before" = "$head_idle" ] || fail target-mutated-before-ui

  preview="$(/usr/local/sbin/swir-install-engine preview --target "$TARGET")" || fail engine-preview
  printf '%s\n' "$preview" > "$OUT/engine-preview.json"
  head_preview="$(dd if="$target_real" bs=1M count=4 status=none | sha256sum | awk '{print $1}')"
  [ "$head_before" = "$head_preview" ] || fail engine-preview-mutated-target

  cancel="$(/usr/local/sbin/swir-install-engine cancel --target "$TARGET")" || fail engine-cancel
  printf '%s\n' "$cancel" > "$OUT/engine-cancel.json"
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["cancelled"] is True and d["destructiveWritePerformed"] is False' <<EOF_CANCEL || fail cancel-evidence
$cancel
EOF_CANCEL
  head_cancel="$(dd if="$target_real" bs=1M count=4 status=none | sha256sum | awk '{print $1}')"
  [ "$head_before" = "$head_cancel" ] || fail engine-cancel-mutated-target

  source_part="$(findmnt -n -o SOURCE /)"
  source_parent="$(lsblk -ndo PKNAME "$source_part" | tr -d '[:space:]')"
  [ -n "$source_parent" ] || fail source-parent
  if SWIR_INSTALLER_ALLOW_UNSTABLE_TARGET=1 /usr/local/sbin/swir-install-engine preview --target "/dev/$source_parent" >/dev/null 2>&1; then
    fail source-media-not-rejected
  fi

  uid="$(id -u swir-e2e)"
  runtime="/run/user/$uid"
  socket="$runtime/wayland-swir"
  i=0
  while [ "$i" -lt 60 ] && [ ! -S "$socket" ]; do i=$((i + 1)); sleep 1; done
  [ -S "$socket" ] || fail wayland-socket-missing

  install -d -m 0755 /run/swir
  : > /run/swir/installer-e2e-enabled
  chown root:root /run/swir/installer-e2e-enabled
  chmod 0400 /run/swir/installer-e2e-enabled
  cat > /run/swir/installer-e2e-config.json <<EOF_CFG
{"targetStablePath":"$TARGET","username":"$TEST_USER","locale":"$TEST_LOCALE","keyboard":"$TEST_KEYBOARD","timezone":"$TEST_TIMEZONE"}
EOF_CFG
  chown root:root /run/swir/installer-e2e-config.json
  chmod 0444 /run/swir/installer-e2e-config.json
  rm -f "$runtime/swir-installer-e2e-evidence.json"

  runuser -u swir-e2e -- env \
    XDG_RUNTIME_DIR="$runtime" WAYLAND_DISPLAY=wayland-swir GDK_BACKEND=wayland \
    SWIR_INSTALLER_E2E_PASSWORD='Swir-E2E-Password-2026!' \
    /usr/local/bin/swir-installer \
      --e2e-config /run/swir/installer-e2e-config.json \
      --evidence "$runtime/swir-installer-e2e-evidence.json" || fail gui-process

  [ -s "$runtime/swir-installer-e2e-evidence.json" ] || fail gui-evidence-missing
  cp "$runtime/swir-installer-e2e-evidence.json" "$OUT/gui-evidence.json"
  chmod 0600 "$OUT/gui-evidence.json"
  ui_diag="$(python3 - "$OUT/gui-evidence.json" <<'PY_DIAG'
import json, pathlib, sys
try:
    d = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception as exc:
    print(json.dumps({"status": "invalid-evidence", "message": type(exc).__name__}, sort_keys=True))
else:
    if d.get("status") != "installed":
        safe = {
            "schema": d.get("schema"),
            "status": d.get("status"),
            "message": str(d.get("message") or "")[:300],
            "passwordStoredInEvidence": d.get("passwordStoredInEvidence"),
        }
        print(json.dumps(safe, sort_keys=True))
PY_DIAG
)"
  [ -z "$ui_diag" ] || serial "SWIR_GRAPHICAL_INSTALLER_UI_EVIDENCE $ui_diag"
  python3 - "$OUT/gui-evidence.json" "$TARGET" "$TEST_USER" "$TEST_LOCALE" "$TEST_KEYBOARD" "$TEST_TIMEZONE" <<'PY' || fail gui-evidence
import json, pathlib, sys
path, target, username, locale, keyboard, timezone = sys.argv[1:]
d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
assert d["schema"] == "swir.graphical-installer-ui-e2e/0.1"
assert d["status"] == "installed"
assert d["gtkWindowCreated"] is True
assert d["uiPreviewPassed"] is True
assert d["uiWrongTokenBlocked"] is True
assert d["uiIdentityReviewPassed"] is True
assert d["uiTriggeredPrivilegedInstall"] is True
assert d["targetStablePath"] == target
assert d["username"] == username
assert d["locale"] == locale
assert d["keyboard"] == keyboard
assert d["timezone"] == timezone
assert d["sourceMediaProtected"] is True
assert d["explicitConfirmationVerified"] is True
assert d["passwordStoredInEvidence"] is False
assert "password" not in d
PY

  head_after="$(dd if="$target_real" bs=1M count=4 status=none | sha256sum | awk '{print $1}')"
  [ "$head_before" != "$head_after" ] || fail gui-install-did-not-mutate-target

  mkdir -p /mnt/swir-target
  target_root="$(lsblk -lnpo PATH,LABEL "$target_real" | awk '$2 == "SWIR_ROOT" {print $1; exit}')"
  [ -b "$target_root" ] || fail target-root-partition
  mount "$target_root" /mnt/swir-target || fail target-root-mount
  [ -s /mnt/swir-target/var/lib/swir/install/install.json ] || fail install-manifest-missing
  grep -Fxq 'SWIR-GRAPHICAL-INSTALLER-PERSISTENCE-v1' /mnt/swir-target/var/lib/swir/graphical-installer-e2e/source-marker.txt || fail persistence-copy
  verify_user_config_root /mnt/swir-target || fail installed-user-config-on-disk
  umount /mnt/swir-target

  printf 'PHASE1_PASS\n' > "$STATUS"
  serial 'SWIR_GRAPHICAL_INSTALLER_PHASE1_PASS ui-driven=true wrong-token-ui-blocked=true account=true locale=true keyboard=true timezone=true source-protected=true'
  sync
  systemctl --no-block poweroff
  exit 0
fi

if [ "$rootlabel" = SWIR_ROOT ]; then
  [ -s /var/lib/swir/install/install.json ] || fail installed-manifest
  grep -Fxq 'SWIR-GRAPHICAL-INSTALLER-PERSISTENCE-v1' "$OUT/source-marker.txt" || fail installed-persistence
  verify_user_config_root / || fail installed-user-config-after-boot
  systemctl is-active --quiet greetd.service || fail installed-greetd-inactive
  wait_session installed || fail installed-graphical-session-timeout
  ! lsblk -dn -o SERIAL | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | grep -Fxq 'SWIR_LIVE_GUI_E2E' || fail live-usb-still-attached
  printf 'INSTALLED-USER-DATA-v1\n' > "/home/$TEST_USER/.swir-installer-e2e"
  chown "$TEST_USER:$TEST_USER" "/home/$TEST_USER/.swir-installer-e2e"
  sync
  printf 'PHASE2_PASS\n' > "$STATUS"
  serial 'SWIR_GRAPHICAL_INSTALLER_PHASE2_PASS detached-boot=true graphical=true user-config=true persistence=true live-usb-detached=true'
  systemctl --no-block poweroff
  exit 0
fi

fail unexpected-root-label
GUEST
chmod 0755 "$ROOTFS/usr/local/lib/swir/graphical-installer-e2e-run"

cat > "$ROOTFS/etc/systemd/system/swir-graphical-installer-e2e.service" <<'UNIT'
[Unit]
Description=SWIR GTK graphical installer full-path E2E gate
After=greetd.service polkit.service
Wants=greetd.service polkit.service

[Service]
Type=oneshot
ExecStart=/usr/local/lib/swir/graphical-installer-e2e-run
TimeoutStartSec=300

[Install]
WantedBy=graphical.target
UNIT
install -d -m 0755 "$ROOTFS/etc/systemd/system/graphical.target.wants"
ln -sfn ../swir-graphical-installer-e2e.service "$ROOTFS/etc/systemd/system/graphical.target.wants/swir-graphical-installer-e2e.service"

rm -f "$ROOTFS/usr/sbin/policy-rc.d"
chroot "$ROOTFS" apt-get clean
cleanup
ROOTFS_MOUNTS=0
trap cleanup EXIT

bash "$REPO_ROOT/system/image/build-live-usb-img.sh" \
  --rootfs "$ROOTFS" --output "$LIVE_IMG" \
  --kernel-options 'root=LABEL=SWIR_LIVE_ROOT rw quiet splash console=ttyS0,115200n8'

truncate -s 8G "$TARGET_DISK"
cp "$OVMF_VARS_TEMPLATE" "$OVMF_VARS_LIVE"
cp "$OVMF_VARS_TEMPLATE" "$OVMF_VARS_INSTALLED"
chmod 0600 "$OVMF_VARS_LIVE" "$OVMF_VARS_INSTALLED"

set +e
timeout --signal=TERM --kill-after=15s 420s qemu-system-x86_64 \
  -machine q35,accel=tcg -cpu max -smp 2 -m 2048 -no-reboot -nodefaults \
  -device virtio-vga -display none -monitor none \
  -serial stdio \
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
  -drive "if=pflash,format=raw,file=$OVMF_VARS_LIVE" \
  -device qemu-xhci,id=xhci \
  -drive "if=none,id=liveusb,format=raw,file=$LIVE_IMG,cache=unsafe" \
  -device "usb-storage,drive=liveusb,bootindex=1,serial=SWIR_LIVE_GUI_E2E" \
  -drive "if=none,id=targetdisk,format=raw,file=$TARGET_DISK,cache=unsafe" \
  -device "virtio-blk-pci,drive=targetdisk,serial=SWIR_TARGET_GUI_E2E,bootindex=2" \
  2>&1 | tee "$SERIAL_LIVE"
qemu_live=${PIPESTATUS[0]}
set -e
[[ $qemu_live -eq 0 || $qemu_live -eq 124 ]] || { echo "live QEMU failed: $qemu_live" >&2; exit 10; }
grep -F 'SWIR_GRAPHICAL_INSTALLER_PHASE1_PASS ui-driven=true wrong-token-ui-blocked=true account=true locale=true keyboard=true timezone=true source-protected=true' "$SERIAL_LIVE" >/dev/null || {
  tail -n 320 "$SERIAL_LIVE" >&2 || true
  exit 11
}

set +e
timeout --signal=TERM --kill-after=15s 300s qemu-system-x86_64 \
  -machine q35,accel=tcg -cpu max -smp 2 -m 2048 -no-reboot -nodefaults \
  -device virtio-vga -display none -monitor none \
  -serial stdio \
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
  -drive "if=pflash,format=raw,file=$OVMF_VARS_INSTALLED" \
  -drive "if=none,id=targetdisk,format=raw,file=$TARGET_DISK,cache=unsafe" \
  -device "virtio-blk-pci,drive=targetdisk,serial=SWIR_TARGET_GUI_E2E,bootindex=1" \
  2>&1 | tee "$SERIAL_INSTALLED"
qemu_installed=${PIPESTATUS[0]}
set -e
[[ $qemu_installed -eq 0 || $qemu_installed -eq 124 ]] || { echo "installed QEMU failed: $qemu_installed" >&2; exit 12; }
grep -F 'SWIR_GRAPHICAL_INSTALLER_PHASE2_PASS detached-boot=true graphical=true user-config=true persistence=true live-usb-detached=true' "$SERIAL_INSTALLED" >/dev/null || {
  tail -n 320 "$SERIAL_INSTALLED" >&2 || true
  exit 13
}

LIVE_SHA="$(sha256sum "$LIVE_IMG" | awk '{print $1}')"
TARGET_SHA="$(sha256sum "$TARGET_DISK" | awk '{print $1}')"
python3 - "$EVIDENCE" "$LIVE_SHA" "$TARGET_SHA" <<'PY'
import datetime, json, pathlib, sys
out, live_sha, target_sha = sys.argv[1:]
report = {
  "schema": "swir.graphical-installer-full-e2e/0.1",
  "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "distribution": "debian-13-trixie",
  "architecture": "amd64",
  "firmware": "uefi-ovmf",
  "liveUsbTransport": "qemu-usb-storage",
  "liveImageSha256": live_sha,
  "installedDiskSha256": target_sha,
  "gtkWindowCreated": True,
  "uiSelectedStableTarget": True,
  "uiPreviewReadOnly": True,
  "uiWrongTokenBlocked": True,
  "uiIdentityReviewPassed": True,
  "uiTriggeredPrivilegedInstall": True,
  "sourceMediaTargetRejected": True,
  "installedUserCreated": True,
  "installedLocaleVerified": True,
  "installedKeyboardVerified": True,
  "installedTimezoneVerified": True,
  "passwordStoredInEvidence": False,
  "sourceUsbDetachedBeforeInstalledBoot": True,
  "installedDiskBooted": True,
  "installedGraphicalSessionPassed": True,
  "installedPersistencePassed": True,
  "physicalHardwareQualificationClaim": False,
  "secureBootClaim": False
}
pathlib.Path(out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

sha256sum "$LIVE_IMG" > "$ARTIFACT_DIR/live-usb.img.sha256"
python3 -m json.tool "$EVIDENCE" >/dev/null
rm -f "$LIVE_IMG" "$TARGET_DISK" "$OVMF_VARS_LIVE" "$OVMF_VARS_INSTALLED"
echo "SWIR GTK graphical installer full-path E2E passed"
