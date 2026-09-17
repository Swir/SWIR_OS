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
          +--> inventory pending package/firmware journals read-only
          +--> verify no non-loopback network device exists in the E2E guest
          +--> write diagnostics only to /run tmpfs
```

The normal System Edition fstab remains present and is inspected by the diagnostics agent. `fstab=no` is used only by the recovery boot entry so the recovery environment does not automatically mount additional persistent filesystems while it is diagnosing the machine.

## Production recovery foundation

`system/recovery/recovery-mode-provisioning.mjs` stages only three fixed repository-owned artifacts:

- `/opt/swir/system/recovery/recovery-mode-agent.mjs`
- `/etc/systemd/system/swir-recovery.service`
- `/etc/systemd/system/swir-recovery.target`

Production staging requires a root-owned, non-world-writable rootfs and rejects symlink destinations. Unit content is checked for required hardening and shell-string execution is forbidden.

`swir-recovery.service` runs as root because it must inspect block-device metadata and protected transaction journals, but it deliberately drops its Linux capability bounding set and enables `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `RestrictSUIDSGID`, `LockPersonality`, and native syscall architecture restriction. Its only writable application path is volatile `/run/swir/recovery`; recovery evidence is not persisted to the diagnosed root filesystem.

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
10. Package and firmware transaction directories are scanned read-only when present.
11. No filesystem repair, package mutation, or firmware mutation is performed automatically.
12. The guest emits a machine-readable recovery report and a deterministic success marker before powering off.

## Safety boundary

The recovery path deliberately distinguishes **bootable recovery diagnostics** from **automatic repair**. The following remain outside this 0.1 claim:

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

Once this exact UEFI recovery gate is green, it is sufficient evidence for the scoped roadmap deliverable **filesystem integration and recovery mode**: the System Edition has a real filesystem layout plus a dedicated bootable recovery target that is exercised end-to-end.

It is **not** sufficient for **journaled driver/firmware/package transactions** or **hardware/firmware rollback or documented manual recovery path**. Those remain separate roadmap gates until their mutation/recovery behavior is implemented and verified.
