#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "debian13-recovery-mode-vm-e2e.sh must run as root" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROFILE="$REPO_ROOT/system/image/system-base-debian-trixie.json"
WORK_ROOT="${SWIR_RECOVERY_VM_WORK_ROOT:-/tmp/swir-debian13-recovery-e2e}"
ARTIFACT_DIR="${SWIR_RECOVERY_VM_ARTIFACT_DIR:-$WORK_ROOT/artifacts}"
ROOTFS="$WORK_ROOT/rootfs"
DISK="$WORK_ROOT/swir-recovery-uefi.raw"
ROOT_MOUNT="$WORK_ROOT/root-mount"
ESP_MOUNT="$ROOT_MOUNT/boot/efi"
SERIAL_LOG="$ARTIFACT_DIR/recovery-serial.log"
RECOVERY_REPORT="$ARTIFACT_DIR/recovery-report.json"
RECOVERY_EVIDENCE="$ARTIFACT_DIR/recovery-mode-evidence.json"
PROVISION_EVIDENCE="$ARTIFACT_DIR/recovery-provisioning.json"
OVMF_CODE="/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_VARS_TEMPLATE="/usr/share/OVMF/OVMF_VARS_4M.fd"
OVMF_VARS="$WORK_ROOT/OVMF_VARS_4M.fd"
PACKAGE_FIXTURE_ID="recovery-e2e-package-0001"
FIRMWARE_FIXTURE_ID="recovery-e2e-firmware-0001"

case "$(readlink -m "$WORK_ROOT")" in
  /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/srv|/sys|/usr|/var)
    echo "refusing unsafe work root: $WORK_ROOT" >&2; exit 3 ;;
esac
for command in chroot mount umount node qemu-system-x86_64 mkfs.ext4 mkfs.vfat rsync timeout grep install sha256sum stat losetup parted partprobe udevadm; do
  command -v "$command" >/dev/null || { echo "missing required host command: $command" >&2; exit 4; }
done
[[ -f "$PROFILE" && ! -L "$PROFILE" ]] || { echo "selected Debian profile missing" >&2; exit 5; }
[[ -f "$OVMF_CODE" && ! -L "$OVMF_CODE" ]] || { echo "OVMF code firmware missing" >&2; exit 5; }
[[ -f "$OVMF_VARS_TEMPLATE" && ! -L "$OVMF_VARS_TEMPLATE" ]] || { echo "OVMF vars template missing" >&2; exit 5; }
[[ "$(dpkg --print-architecture)" == "amd64" ]] || { echo "recovery UEFI lane is native amd64 only" >&2; exit 6; }

rm -rf "$WORK_ROOT"
install -d -m 0700 "$WORK_ROOT" "$ARTIFACT_DIR" "$ROOTFS" "$ROOT_MOUNT"
loop_dev=""
root_mounted=0
esp_mounted=0
rootfs_mounts=0
cleanup() {
  set +e
  if [[ $rootfs_mounts -eq 1 ]]; then
    umount -R "$ROOTFS/dev" 2>/dev/null || true
    umount -R "$ROOTFS/sys" 2>/dev/null || true
    umount "$ROOTFS/proc" 2>/dev/null || true
    rootfs_mounts=0
  fi
  if [[ $esp_mounted -eq 1 ]]; then umount "$ESP_MOUNT" 2>/dev/null || true; esp_mounted=0; fi
  if [[ $root_mounted -eq 1 ]]; then umount "$ROOT_MOUNT" 2>/dev/null || true; root_mounted=0; fi
  if [[ -n "$loop_dev" ]]; then losetup -d "$loop_dev" 2>/dev/null || true; loop_dev=""; fi
}
trap cleanup EXIT

echo "[SWIR] Building Debian 13 foundation for dedicated recovery boot"
bash "$REPO_ROOT/system/image/build-debian-trixie-rootfs.sh" --rootfs "$ROOTFS" --profile "$PROFILE" --arch amd64
mount -t proc proc "$ROOTFS/proc"
mount --rbind /sys "$ROOTFS/sys"
mount --make-rslave "$ROOTFS/sys"
mount --rbind /dev "$ROOTFS/dev"
mount --make-rslave "$ROOTFS/dev"
rootfs_mounts=1
cat > "$ROOTFS/usr/sbin/policy-rc.d" <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod 0755 "$ROOTFS/usr/sbin/policy-rc.d"
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get update
chroot "$ROOTFS" /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nodejs systemd-boot-efi util-linux
chroot "$ROOTFS" /usr/bin/systemd-machine-id-setup

EFI_SOURCE="$ROOTFS/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
[[ -f "$EFI_SOURCE" && ! -L "$EFI_SOURCE" ]] || { echo "Debian systemd-boot EFI binary missing" >&2; exit 7; }
[[ "$(stat -c '%u' "$EFI_SOURCE")" == "0" ]] || { echo "systemd-boot EFI binary must be root-owned" >&2; exit 7; }
EFI_MODE="$(stat -c '%a' "$EFI_SOURCE")"
(( (8#$EFI_MODE & 8#022) == 0 )) || { echo "systemd-boot EFI binary must not be group/world writable" >&2; exit 7; }
EFI_SHA256="$(sha256sum "$EFI_SOURCE" | awk '{print $1}')"

NODE_BIN="$(command -v node)"
"$NODE_BIN" --input-type=module - "$REPO_ROOT" "$ROOTFS" > "$PROVISION_EVIDENCE" <<'NODE'
import path from 'node:path';
const [repoRoot, rootfs] = process.argv.slice(2);
const mod = await import(`file://${path.join(repoRoot, 'system/recovery/recovery-mode-provisioning.mjs')}`);
const report = await mod.stageRecoveryModeFoundation({ rootfs, sourceRoot: repoRoot, production: true });
process.stdout.write(`${JSON.stringify(report)}\n`);
if (!report.ready || report.recoveryBootVerified !== false || report.filesystemRepairClaim !== false || report.automaticMutationAllowed !== false) process.exit(2);
NODE

cat > "$ROOTFS/usr/local/sbin/swir-recovery-e2e-finish" <<'GUEST'
#!/bin/sh
set -eu
REPORT=/run/swir/recovery/recovery-report.json
MUTATION_TIMERS="apt-daily.timer apt-daily-upgrade.timer dpkg-db-backup.timer fstrim.timer fwupd-refresh.timer"
PACKAGE_FIXTURE_ID=recovery-e2e-package-0001
FIRMWARE_FIXTURE_ID=recovery-e2e-firmware-0001
serial() { printf '%s\n' "$*" > /dev/ttyS0; }
fail() {
  serial "SWIR_RECOVERY_VM_E2E_FAIL $1"
  journalctl -b --no-pager -n 160 -u swir-recovery.service -u swir-recovery-e2e.service > /dev/ttyS0 2>&1 || true
  sync
  systemctl --no-block poweroff
  exit 1
}
[ -s "$REPORT" ] || fail report-missing
node - "$REPORT" "$PACKAGE_FIXTURE_ID" "$FIRMWARE_FIXTURE_ID" <<'NODE' || fail report-invalid
const fs = require('fs');
const [reportPath, packageId, firmwareId] = process.argv.slice(2);
const r = JSON.parse(fs.readFileSync(reportPath));
const p = r.transactions?.packages;
const f = r.transactions?.firmware;
if (r.schema !== 'swir.recovery-mode-report/0.2' || r.bootTarget !== 'swir-recovery.target' || r.safeReadOnlyRecoveryBoot !== true) process.exit(2);
if (r.root?.readOnly !== true || r.root?.filesystem !== 'ext4' || r.root?.fstabIntegrated !== true || r.esp?.fstabIntegrated !== true) process.exit(3);
if (r.network?.nonLoopbackDevices?.length !== 0 || r.automaticFilesystemRepairPerformed !== false || r.automaticPackageMutationPerformed !== false || r.automaticFirmwareMutationPerformed !== false) process.exit(4);
if (p?.directory !== '/var/lib/swir/package-transactions' || p?.schema !== 'swir.system-package-transaction/0.1' || p?.statusField !== 'state') process.exit(5);
if (p?.journals !== 1 || p?.pending !== 1 || p?.corrupt !== 0 || !p?.pendingIds?.includes(packageId)) process.exit(6);
if (f?.directory !== '/var/lib/swir/transactions/firmware' || f?.schema !== 'swir.firmware-transaction-journal/0.1' || f?.statusField !== 'status') process.exit(7);
if (f?.journals !== 1 || f?.pending !== 1 || f?.corrupt !== 0 || !f?.pendingIds?.includes(firmwareId)) process.exit(8);
if (r.manualRecoveryRequiredForPendingTransactions !== true) process.exit(9);
NODE
for unit in $MUTATION_TIMERS; do
  state="$(systemctl is-active "$unit" 2>/dev/null || true)"
  [ "$state" != "active" ] || fail "mutation-timer-active:$unit"
  enabled="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
  case "$enabled" in
    masked|masked-runtime) ;;
    *) fail "mutation-timer-unmasked:$unit:$enabled" ;;
  esac
done
printf 'SWIR_RECOVERY_VM_E2E_REPORT ' > /dev/ttyS0
cat "$REPORT" > /dev/ttyS0
serial 'SWIR_RECOVERY_VM_E2E_PASS debian=13 uefi=systemd-boot root=readonly network=disabled timers=masked mutations=none journals=canonical'
sync
systemctl --no-block poweroff
GUEST
chmod 0755 "$ROOTFS/usr/local/sbin/swir-recovery-e2e-finish"
cat > "$ROOTFS/etc/systemd/system/swir-recovery-e2e.service" <<'UNIT'
[Unit]
Description=SWIR disposable recovery-mode UEFI E2E completion gate
Requires=swir-recovery.service
After=swir-recovery.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/swir-recovery-e2e-finish
TimeoutStartSec=45

[Install]
WantedBy=swir-recovery.target
UNIT
install -d -m 0755 "$ROOTFS/etc/systemd/system/swir-recovery.target.wants"
ln -sf ../swir-recovery-e2e.service "$ROOTFS/etc/systemd/system/swir-recovery.target.wants/swir-recovery-e2e.service"
printf 'LABEL=SWIR_ROOT / ext4 defaults 0 1\nLABEL=SWIR_ESP /boot/efi vfat umask=0077 0 2\n' > "$ROOTFS/etc/fstab"
echo swir-recovery-e2e > "$ROOTFS/etc/hostname"

# Seed minimal read-only diagnostics fixtures at the exact production journal roots.
# The recovery agent must detect both without mutating either journal.
install -d -m 0700 "$ROOTFS/var/lib/swir/package-transactions" "$ROOTFS/var/lib/swir/transactions/firmware"
cat > "$ROOTFS/var/lib/swir/package-transactions/$PACKAGE_FIXTURE_ID.json" <<JSON
{
  "schema": "swir.system-package-transaction/0.1",
  "id": "$PACKAGE_FIXTURE_ID",
  "state": "failed-needs-recovery",
  "diagnosticFixture": true
}
JSON
chmod 0600 "$ROOTFS/var/lib/swir/package-transactions/$PACKAGE_FIXTURE_ID.json"
cat > "$ROOTFS/var/lib/swir/transactions/firmware/$FIRMWARE_FIXTURE_ID.json" <<JSON
{
  "schema": "swir.firmware-transaction-journal/0.1",
  "transactionId": "$FIRMWARE_FIXTURE_ID",
  "status": "staged-reboot-required",
  "diagnosticFixture": true
}
JSON
chmod 0600 "$ROOTFS/var/lib/swir/transactions/firmware/$FIRMWARE_FIXTURE_ID.json"

rm -f "$ROOTFS/usr/sbin/policy-rc.d"
chroot "$ROOTFS" apt-get clean
cleanup
trap cleanup EXIT

KERNEL="$(find "$ROOTFS/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | sort -V | tail -n1)"
INITRD="$(find "$ROOTFS/boot" -maxdepth 1 -type f -name 'initrd.img-*' | sort -V | tail -n1)"
[[ -n "$KERNEL" && -n "$INITRD" ]] || { echo "kernel/initrd missing from recovery rootfs" >&2; exit 7; }

truncate -s 8G "$DISK"
loop_dev="$(losetup --find --show --partscan "$DISK")"
parted -s "$loop_dev" mklabel gpt
parted -s "$loop_dev" mkpart ESP fat32 1MiB 513MiB
parted -s "$loop_dev" set 1 esp on
parted -s "$loop_dev" mkpart SWIR_ROOT ext4 513MiB 100%
partprobe "$loop_dev"
udevadm settle
ESP_PART="${loop_dev}p1"
ROOT_PART="${loop_dev}p2"
[[ -b "$ESP_PART" && -b "$ROOT_PART" ]] || { echo "recovery partition devices were not created" >&2; exit 8; }
mkfs.vfat -F 32 -n SWIR_ESP "$ESP_PART" >/dev/null
mkfs.ext4 -q -F -L SWIR_ROOT "$ROOT_PART"
mount "$ROOT_PART" "$ROOT_MOUNT"
root_mounted=1
install -d -m 0755 "$ESP_MOUNT"
mount "$ESP_PART" "$ESP_MOUNT"
esp_mounted=1
rsync -aHAX --numeric-ids --exclude='/boot/efi/*' "$ROOTFS/" "$ROOT_MOUNT/"
chown 0:0 "$ROOT_MOUNT"
chmod 0755 "$ROOT_MOUNT"

install -d -m 0755 "$ESP_MOUNT/EFI/BOOT" "$ESP_MOUNT/EFI/systemd" "$ESP_MOUNT/EFI/Linux" "$ESP_MOUNT/loader/entries"
install -m 0644 "$EFI_SOURCE" "$ESP_MOUNT/EFI/BOOT/BOOTX64.EFI"
install -m 0644 "$EFI_SOURCE" "$ESP_MOUNT/EFI/systemd/systemd-bootx64.efi"
install -m 0644 "$KERNEL" "$ESP_MOUNT/EFI/Linux/swir-vmlinuz"
install -m 0644 "$INITRD" "$ESP_MOUNT/EFI/Linux/swir-initrd.img"
cat > "$ESP_MOUNT/loader/loader.conf" <<'LOADER'
default swir-recovery.conf
timeout 0
console-mode keep
editor no
LOADER
cat > "$ESP_MOUNT/loader/entries/swir-recovery.conf" <<'ENTRY'
title SWIR OS Recovery Mode E2E
linux /EFI/Linux/swir-vmlinuz
initrd /EFI/Linux/swir-initrd.img
options root=LABEL=SWIR_ROOT ro console=ttyS0,115200n8 systemd.unit=swir-recovery.target systemd.mask=systemd-remount-fs.service systemd.mask=apt-daily.timer systemd.mask=apt-daily-upgrade.timer systemd.mask=dpkg-db-backup.timer systemd.mask=fstrim.timer systemd.mask=fwupd-refresh.timer fstab=no net.ifnames=0
ENTRY
sync
umount "$ESP_MOUNT"
esp_mounted=0
umount "$ROOT_MOUNT"
root_mounted=0
losetup -d "$loop_dev"
loop_dev=""

cp "$OVMF_VARS_TEMPLATE" "$OVMF_VARS"
chmod 0600 "$OVMF_VARS"
set +e
timeout --signal=TERM --kill-after=15s 240s qemu-system-x86_64 \
  -machine q35,accel=tcg -cpu max -smp 2 -m 2048 \
  -nographic -no-reboot -nodefaults \
  -serial stdio \
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
  -drive "if=pflash,format=raw,file=$OVMF_VARS" \
  -drive "file=$DISK,format=raw,if=virtio,cache=unsafe" \
  2>&1 | tee "$SERIAL_LOG"
qemu_status=${PIPESTATUS[0]}
set -e
if [[ $qemu_status -ne 0 && $qemu_status -ne 124 ]]; then
  echo "recovery QEMU exited unexpectedly: $qemu_status" >&2
  exit 9
fi
grep -F 'SWIR_RECOVERY_VM_E2E_PASS debian=13 uefi=systemd-boot root=readonly network=disabled timers=masked mutations=none journals=canonical' "$SERIAL_LOG" >/dev/null || {
  echo "guest did not emit SWIR_RECOVERY_VM_E2E_PASS" >&2
  tail -n 260 "$SERIAL_LOG" >&2 || true
  exit 10
}
REPORT_LINE="$(grep -F 'SWIR_RECOVERY_VM_E2E_REPORT ' "$SERIAL_LOG" | tail -n1)"
[[ -n "$REPORT_LINE" ]] || { echo "recovery report marker missing from serial output" >&2; exit 10; }
printf '%s\n' "${REPORT_LINE#*SWIR_RECOVERY_VM_E2E_REPORT }" > "$RECOVERY_REPORT"

IMAGE_SHA256="$(sha256sum "$DISK" | awk '{print $1}')"
OVMF_SHA256="$(sha256sum "$OVMF_CODE" | awk '{print $1}')"
"$NODE_BIN" - "$RECOVERY_REPORT" "$RECOVERY_EVIDENCE" "$EFI_SHA256" "$IMAGE_SHA256" "$OVMF_SHA256" "$PACKAGE_FIXTURE_ID" "$FIRMWARE_FIXTURE_ID" <<'NODE'
const fs = require('fs');
const [reportPath, outputPath, bootloaderSha256, imageSha256, ovmfSha256, packageId, firmwareId] = process.argv.slice(2);
const r = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const p = r?.transactions?.packages;
const f = r?.transactions?.firmware;
if (r?.schema !== 'swir.recovery-mode-report/0.2' || r.bootTarget !== 'swir-recovery.target' || r.safeReadOnlyRecoveryBoot !== true) process.exit(2);
if (r.root?.readOnly !== true || r.root?.filesystem !== 'ext4' || r.root?.fstabIntegrated !== true || r.esp?.fstabIntegrated !== true) process.exit(3);
if (r.kernelPolicy?.rootRequestedReadOnly !== true || r.kernelPolicy?.remountServiceMasked !== true || r.kernelPolicy?.fstabGeneratorDisabled !== true) process.exit(4);
if (r.network?.nonLoopbackDevices?.length !== 0 || r.network?.networkActivationRequested !== false) process.exit(5);
if (r.automaticFilesystemRepairPerformed !== false || r.automaticPackageMutationPerformed !== false || r.automaticFirmwareMutationPerformed !== false) process.exit(6);
const packageJournalPathIntegrated = p?.directory === '/var/lib/swir/package-transactions' && p?.schema === 'swir.system-package-transaction/0.1' && p?.statusField === 'state';
const firmwareJournalPathIntegrated = f?.directory === '/var/lib/swir/transactions/firmware' && f?.schema === 'swir.firmware-transaction-journal/0.1' && f?.statusField === 'status';
const pendingPackageTransactionDetected = p?.journals === 1 && p?.pending === 1 && p?.corrupt === 0 && p?.pendingIds?.includes(packageId);
const pendingFirmwareTransactionDetected = f?.journals === 1 && f?.pending === 1 && f?.corrupt === 0 && f?.pendingIds?.includes(firmwareId);
if (!packageJournalPathIntegrated || !firmwareJournalPathIntegrated || !pendingPackageTransactionDetected || !pendingFirmwareTransactionDetected) process.exit(7);
if (r.manualRecoveryRequiredForPendingTransactions !== true) process.exit(8);
const evidence = {
  schema: 'swir.system-recovery-mode-e2e/0.2',
  generatedAt: new Date().toISOString(),
  distribution: 'debian-13-trixie',
  architecture: 'amd64',
  bootPath: 'uefi-systemd-boot-recovery',
  bootTarget: r.bootTarget,
  dedicatedBootEntry: 'swir-recovery.conf',
  partitionTable: 'gpt',
  rootFilesystem: r.root.filesystem,
  rootFilesystemLabel: 'SWIR_ROOT',
  espFilesystem: 'fat32',
  espFilesystemLabel: 'SWIR_ESP',
  rootReadOnly: r.root.readOnly,
  rootFstabIntegrated: r.root.fstabIntegrated,
  espFstabIntegrated: r.esp.fstabIntegrated,
  remountServiceMasked: r.kernelPolicy.remountServiceMasked,
  fstabGeneratorDisabledDuringRecovery: r.kernelPolicy.fstabGeneratorDisabled,
  guestNetworkDisabled: r.network.nonLoopbackDevices.length === 0,
  mutationTimersMasked: true,
  diagnosticsAgentPassed: true,
  transactionJournalScanPassed: packageJournalPathIntegrated && firmwareJournalPathIntegrated && pendingPackageTransactionDetected && pendingFirmwareTransactionDetected,
  packageJournalPathIntegrated,
  firmwareJournalPathIntegrated,
  pendingPackageTransactionDetected,
  pendingFirmwareTransactionDetected,
  manualRecoveryRequired: r.manualRecoveryRequiredForPendingTransactions,
  packageJournalSchema: p.schema,
  firmwareJournalSchema: f.schema,
  automaticFilesystemRepairPerformed: r.automaticFilesystemRepairPerformed,
  automaticPackageMutationPerformed: r.automaticPackageMutationPerformed,
  automaticFirmwareMutationPerformed: r.automaticFirmwareMutationPerformed,
  bootloaderSha256,
  imageSha256,
  ovmfSha256,
  recoveryModeClaim: true,
  filesystemIntegrationClaim: true,
  filesystemRepairClaim: false,
  hardwareQualificationClaim: false,
  installerClaim: false,
  passed: true
};
fs.writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`);
NODE
sha256sum "$DISK" > "$ARTIFACT_DIR/recovery-image.sha256"
rm -f "$DISK" "$OVMF_VARS"
echo "SWIR Debian 13 UEFI recovery-mode E2E passed"
