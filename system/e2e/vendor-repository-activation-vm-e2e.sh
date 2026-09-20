#!/usr/bin/env bash
set -euo pipefail

WORK_ROOT="${SWIR_VENDOR_VM_WORK_ROOT:-/tmp/swir-vendor-repository-vm}"
ARTIFACT_DIR="${SWIR_VENDOR_VM_ARTIFACT_DIR:-${WORK_ROOT}/artifacts}"
ROOTFS="${WORK_ROOT}/rootfs"
DISK="${WORK_ROOT}/vendor-e2e-rootfs.img"
MOUNT_DIR="${WORK_ROOT}/mnt"
SERIAL_LOG="${ARTIFACT_DIR}/serial.log"
EVIDENCE_OUT="${ARTIFACT_DIR}/vendor-repository-activation-vm-evidence.json"
POLICY_SOURCE="system/hardware/vendor-repositories.debian13.json"
GUEST_SCRIPT="system/e2e/vendor-repository-activation-vm-guest.mjs"

fail() {
  echo "vendor repository disposable VM E2E: $*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "root privileges are required to build and inspect the disposable VM disk"
[[ -f "$POLICY_SOURCE" && ! -L "$POLICY_SOURCE" ]] || fail "reviewed vendor repository policy is missing or symlinked"
[[ -f "$GUEST_SCRIPT" && ! -L "$GUEST_SCRIPT" ]] || fail "VM guest E2E script is missing or symlinked"
for command in mmdebstrap qemu-system-x86_64 mkfs.ext4 mount umount rsync timeout node; do
  command -v "$command" >/dev/null || fail "required tool is missing: $command"
done

rm -rf "$WORK_ROOT"
install -d -m 0700 "$WORK_ROOT" "$ROOTFS" "$MOUNT_DIR" "$ARTIFACT_DIR"

# This is intentionally a disposable Debian 13 VM proof for the vendor-repository
# transaction only. It is not Live USB, installer, Secure Boot, or physical-hardware evidence.
mmdebstrap \
  --variant=minbase \
  --architectures=amd64 \
  --components='main' \
  --include='linux-image-amd64,systemd-sysv,nodejs,ca-certificates,gnupg,gpgv,apt' \
  trixie "$ROOTFS" https://deb.debian.org/debian

install -d -m 0755 \
  "$ROOTFS/opt/swir" \
  "$ROOTFS/etc/swir/hardware" \
  "$ROOTFS/etc/systemd/network" \
  "$ROOTFS/etc/systemd/system" \
  "$ROOTFS/var/lib/swir/e2e" \
  "$ROOTFS/var/lib/swir/transactions/vendor-repositories"
cp -a system "$ROOTFS/opt/swir/system"
install -o root -g root -m 0644 "$POLICY_SOURCE" "$ROOTFS/etc/swir/hardware/vendor-repositories.json"
chmod 0700 "$ROOTFS/var/lib/swir/e2e" "$ROOTFS/var/lib/swir/transactions/vendor-repositories"

cat > "$ROOTFS/etc/systemd/network/20-swir-vm.network" <<'EOF'
[Match]
Name=eth0

[Network]
DHCP=yes
DNS=10.0.2.3
EOF
chmod 0644 "$ROOTFS/etc/systemd/network/20-swir-vm.network"
cat > "$ROOTFS/etc/resolv.conf" <<'EOF'
nameserver 10.0.2.3
options timeout:2 attempts:3
EOF
cat > "$ROOTFS/etc/hostname" <<'EOF'
swir-vendor-e2e
EOF
cat > "$ROOTFS/etc/fstab" <<'EOF'
/dev/vda / ext4 defaults 0 1
EOF

cat > "$ROOTFS/etc/systemd/system/swir-vendor-repository-e2e.service" <<'EOF'
[Unit]
Description=SWIR disposable VM vendor repository E2E
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/node /opt/swir/system/e2e/vendor-repository-activation-vm-guest.mjs
TimeoutStartSec=12min

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$ROOTFS/etc/systemd/system/swir-vendor-repository-e2e.service"
chroot "$ROOTFS" systemctl enable systemd-networkd.service >/dev/null
chroot "$ROOTFS" systemctl enable swir-vendor-repository-e2e.service >/dev/null

KERNEL="$(find "$ROOTFS/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | sort -V | tail -n1)"
INITRD="$(find "$ROOTFS/boot" -maxdepth 1 -type f -name 'initrd.img-*' | sort -V | tail -n1)"
[[ -n "$KERNEL" && -f "$KERNEL" ]] || fail "Debian kernel was not installed"
[[ -n "$INITRD" && -f "$INITRD" ]] || fail "Debian initrd was not installed"

truncate -s 6G "$DISK"
mkfs.ext4 -q -F -L swir-vendor-e2e "$DISK"
mount -o loop "$DISK" "$MOUNT_DIR"
cleanup_mount() {
  mountpoint -q "$MOUNT_DIR" && umount "$MOUNT_DIR" || true
}
trap cleanup_mount EXIT
rsync -aHAX --numeric-ids "$ROOTFS/" "$MOUNT_DIR/"
sync
umount "$MOUNT_DIR"
trap - EXIT

set +e
timeout --signal=TERM --kill-after=30 900 \
  qemu-system-x86_64 \
    -machine q35,accel=tcg \
    -cpu max \
    -m 1536 \
    -smp 2 \
    -nographic \
    -no-reboot \
    -kernel "$KERNEL" \
    -initrd "$INITRD" \
    -append 'root=/dev/vda rw console=ttyS0,115200n8 systemd.show_status=1 net.ifnames=0' \
    -drive "file=${DISK},format=raw,if=virtio,cache=unsafe" \
    -netdev user,id=swirnet \
    -device virtio-net-pci,netdev=swirnet \
  >"$SERIAL_LOG" 2>&1
QEMU_STATUS=$?
set -e
if [[ "$QEMU_STATUS" -eq 124 || "$QEMU_STATUS" -eq 137 ]]; then
  tail -n 200 "$SERIAL_LOG" >&2 || true
  fail "disposable VM did not finish within the verified timeout"
fi
if [[ "$QEMU_STATUS" -ne 0 ]]; then
  tail -n 200 "$SERIAL_LOG" >&2 || true
  fail "qemu exited with status $QEMU_STATUS"
fi

mount -o loop,ro "$DISK" "$MOUNT_DIR"
trap cleanup_mount EXIT
[[ -f "$MOUNT_DIR/var/lib/swir/e2e/vendor-repository-activation-vm-evidence.json" ]] || {
  tail -n 200 "$SERIAL_LOG" >&2 || true
  fail "guest did not emit vendor repository evidence"
}
cp "$MOUNT_DIR/var/lib/swir/e2e/vendor-repository-activation-vm-evidence.json" "$EVIDENCE_OUT"
[[ ! -e "$MOUNT_DIR/etc/apt/sources.list.d/swir-vendor-nvidia-cuda-debian13-x86_64.sources" ]] || fail "vendor repository source remained enabled after guest recovery/deactivation"
umount "$MOUNT_DIR"
trap - EXIT

node - "$EVIDENCE_OUT" <<'NODE'
const fs = require('node:fs');
const e = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ok = (condition, message) => { if (!condition) throw new Error(message); };
ok(e.schema === 'swir.vendor-repository-activation-vm-e2e/0.1' && e.passed === true, 'guest evidence did not pass');
ok(typeof e.environment?.virtualization === 'string' && e.environment.virtualization !== 'none', 'evidence is not from a VM');
ok(e.environment.physicalHardwareClaim === false && e.environment.liveUsbClaim === false, 'VM evidence overclaimed physical/Live USB scope');
ok(e.policy?.rootOwned === true && e.policy?.groupWorldWritable === false && e.policy?.automaticEnable === false, 'root-owned policy boundary failed');
ok(e.policy?.repositoryId === 'nvidia-cuda-debian13-x86_64', 'unexpected vendor repository id');
ok(e.trust?.fingerprint === '02182E60104FCDC26EAE1B8597A5D4CB8793F200' && e.trust?.evidenceFresh === true, 'vendor trust evidence failed');
ok(e.driverCenter?.vendorSourceVerified === true && e.driverCenter?.package === 'nvidia-open', 'Driver Center did not bind the verified vendor source');
ok(e.activation?.state === 'committed' && e.activation?.metadataRefreshExitCode === 0 && e.activation?.packageVisible === true, 'real signed metadata activation/package visibility failed');
ok(e.activation?.explicitDeactivationState === 'rolled-back' && e.activation?.sourceRestoredAfterDeactivation === true, 'explicit source deactivation failed');
ok(e.interruptionRecovery?.mode === 'fault-injected-rollback-interruption', 'unexpected interruption proof mode');
ok(e.interruptionRecovery?.interruptedState === 'failed-needs-recovery' && e.interruptionRecovery?.operatorAssessmentObserved === true, 'interrupted transaction was not durably recoverable');
ok(e.interruptionRecovery?.recoveredState === 'rolled-back' && e.interruptionRecovery?.sourceRestored === true, 'operator-authorized source recovery failed');
ok(e.safety?.packageInstalled === false && e.safety?.automaticRepositoryEnablement === false && e.safety?.directPkexecPath === false, 'E2E crossed a forbidden mutation boundary');
console.log(`vendor repository disposable VM E2E passed virt=${e.environment.virtualization} repository=${e.policy.repositoryId} binding=${e.driverCenter.bindingDigest}`);
NODE

echo "SWIR vendor repository disposable VM E2E completed successfully"
