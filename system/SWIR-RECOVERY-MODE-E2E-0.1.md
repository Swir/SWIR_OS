# SWIR System Recovery Mode UEFI E2E 0.1

## Purpose

This gate turns recovery mode from a design idea into a dedicated, bootable System Edition path. It builds the selected Debian 13 SWIR root filesystem, stages the production recovery diagnostics foundation, creates a separate `systemd-boot` recovery entry, boots that entry through OVMF/QEMU, and verifies that recovery starts with the root filesystem read-only and without a guest network device.

The first recovery milestone is intentionally diagnostic and fail-closed. It does not automatically run `fsck`, reinstall packages, flash firmware, downgrade drivers, or mutate user data. Its job is to create a trustworthy environment from which later explicitly authorized recovery operations can be added.

## Boot path

```text
OVMF UEFI
   |
   v
systemd-boot
   |
   +--> swir-recovery.conf
          |
          +--> root=LABEL=SWIR_ROOT ro
          +--> systemd.unit=swir-recovery.target
          +--> mask systemd-remount-fs.service
          +--> mask APT/dpkg/fwupd/fstrim mutation-related timers
          +--> disable fstab generator during recovery boot
          |
          v
      swir-recovery.service
          |
          v
      recovery-mode-agent.mjs
          |
          +--> verify root remains read-only
          +--> resolve SWIR_ROOT block label
          +--> verify ext4 + fstab root/ESP integration
          +--> inspect canonical package transaction journals read-only
          +--> inspect canonical firmware transaction journals read-only
          +--> verify no non-loopback network device exists in the E2E guest
          +--> write diagnostics only to /run tmpfs
```

The normal System Edition fstab remains present and is inspected by the diagnostics agent. `fstab=no` is used only by the recovery boot entry so the recovery environment does not automatically mount additional persistent filesystems while it is diagnosing the machine.

The recovery entry also masks `apt-daily.timer`, `apt-daily-upgrade.timer`, `dpkg-db-backup.timer`, `fstrim.timer`, and `fwupd-refresh.timer`. The guest E2E requires every one of those units to remain inactive and runtime-masked. This prevents the recovery target from opportunistically starting package, firmware, trim, or package-database maintenance while the machine is being diagnosed.

## Canonical transaction journal integration

Recovery diagnostics use the exact production journal roots and schemas rather than test-only paths:

```text
Packages:
  /var/lib/swir/package-transactions
  schema = swir.system-package-transaction/0.1
  status field = state

Firmware:
  /var/lib/swir/transactions/firmware
  schema = swir.firmware-transaction-journal/0.1
  status field = status
```

The package scanner recognizes real package lifecycle states including `prepared`, `mutating`, `verifying`, `rolling-back`, and `failed-needs-recovery`. The firmware scanner follows the production firmware journal model and recognizes `planned`, `authorized`, `executing`, `staged-reboot-required`, and `failed-needs-recovery` as states requiring attention.

The UEFI E2E seeds one diagnostic pending record at each canonical production root before the rootfs is copied into the VM image. Recovery must find both records while the root filesystem is mounted read-only, preserve them unchanged, and report that manual recovery is required. The fixture records are test evidence only; they do not claim that an actual package or firmware mutation occurred during this recovery test.

Journal directories and files are required to be root-owned, regular/non-symlink objects and not group/world writable. Invalid JSON/schema records are counted as corrupt and cause recovery to report that operator attention is required rather than silently ignoring them.

## Production recovery foundation

`system/recovery/recovery-mode-provisioning.mjs` stages only three fixed repository-owned artifacts:

- `/opt/swir/system/recovery/recovery-mode-agent.mjs`
- `/etc/systemd/system/swir-recovery.service`
- `/etc/systemd/system/swir-recovery.target`

Production staging requires a root-owned, non-world-writable rootfs and rejects symlink destinations. Unit content is checked for required hardening and shell-string execution is forbidden.

`swir-recovery.service` runs as root because it must inspect block-device metadata and protected transaction journals, but it deliberately drops its Linux capability bounding set and enables `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `RestrictSUIDSGID`, `LockPersonality`, and native syscall architecture restriction. Its only writable application path is volatile `/run/swir/recovery`; recovery evidence is not persisted to the diagnosed root filesystem. The volatile runtime directory is owned by systemd and preserved for the lifetime of the recovery session so later recovery gates can inspect the exact diagnostics report without writing it to persistent storage.

## What the UEFI E2E proves

A successful exact-revision run proves all of the following:

1. The Debian 13 rootfs is built from the selected signed Debian base profile.
2. The recovery artifacts pass trusted production staging and tamper-resistance self-tests.
3. A GPT disk is created with `SWIR_ESP` FAT32 and `SWIR_ROOT` ext4 filesystems.
4. A separate `swir-recovery.conf` loader entry boots through OVMF and Debian's root-owned `systemd-boot` EFI binary.
5. The kernel selects `swir-recovery.target` rather than normal multi-user/graphical boot.
6. The root filesystem remains read-only because recovery requests `ro` and masks `systemd-remount-fs.service`.
7. The normal fstab still maps `/` to `LABEL=SWIR_ROOT`/ext4 and `/boot/efi` to `LABEL=SWIR_ESP`/vfat.
8. The live `SWIR_ROOT` label resolves to a real ext4 block device.
9. The disposable recovery VM has no non-loopback network interface because QEMU is launched without a NIC.
10. The recovery agent reads the production package journal root/schema/state model and detects a pending package recovery fixture.
11. The recovery agent reads the production firmware journal root/schema/status model and detects a pending firmware recovery fixture.
12. Recovery reports that manual recovery is required when either pending transaction is present.
13. APT/dpkg/fwupd/fstrim maintenance timers are masked by the recovery boot entry and verified inactive in the guest.
14. No filesystem repair, package mutation, or firmware mutation is performed automatically.
15. The guest emits a machine-readable `swir.system-recovery-mode-e2e/0.2` evidence record and a deterministic success marker before powering off.

## Safety boundary

The recovery path deliberately distinguishes **bootable recovery diagnostics** from **automatic repair**. The following remain outside this 0.1 architecture claim:

- online or offline destructive filesystem repair,
- restoring a prior filesystem snapshot,
- driver package rollback,
- firmware downgrade/rollback,
- automatic APT inverse operations,
- installer/rescue-media workflows,
- Secure Boot qualification,
- broad physical hardware qualification.

Those operations need separate authorization, recovery evidence, and hardware/filesystem-specific safety gates before they may be enabled.

## Roadmap interpretation

Once the exact final UEFI recovery gate is green, it is sufficient evidence for the scoped roadmap deliverable **filesystem integration and recovery mode**: the System Edition has a real filesystem layout plus a dedicated bootable recovery target exercised end-to-end, and that target can discover the actual package/firmware journal locations without writing to the diagnosed root filesystem.

It is **not** sufficient for **journaled driver/firmware/package transactions**, **fwupd/LVFS firmware updates where supported**, or any automatic hardware/firmware rollback claim. Those remain separate roadmap gates until their mutation/recovery behavior is implemented and verified.
