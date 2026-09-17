# SWIR OS System Edition — Live USB and install foundation 0.1

## Scope

This milestone turns the existing Debian 13 UEFI image work into a media path that is exercised as a **USB mass-storage boot source**, then installs the running System Edition onto a separate blank disk and boots that disk after the source USB is detached.

It is intentionally split into two product gates:

1. **Live USB media** — a raw GPT `.img` with a FAT32 UEFI System Partition, ext4 live root, fallback `EFI/BOOT/BOOTX64.EFI`, kernel/initramfs and SHA-256 output.
2. **Installer** — a safety-first install engine is present, but the final graphical SWIR installer and its account/locale/keyboard/time-zone experience remain open work.

No ISO-hybrid, Secure Boot, legacy BIOS or physical-hardware compatibility claim is made by this 0.1 milestone.

## Live USB builder

`system/image/build-live-usb-img.sh` accepts a prepared System Edition rootfs and creates a byte-for-byte writable raw image. The image uses:

- GPT partition table;
- `SWIR_LIVE_ESP` FAT32 UEFI partition;
- `SWIR_LIVE_ROOT` ext4 root partition;
- systemd-boot fallback path for x86-64 UEFI;
- SHA-256 sidecar file.

The normal Live boot does not contain logic that automatically selects or formats an internal disk. Destructive disk mutation is isolated behind the installer engine and requires an explicit target plus target-bound confirmation token.

## Install-engine safety boundary

`system/installer/swir-install-engine.sh` has three explicit operations:

```text
preview  -> read-only target inspection + exact partition plan + confirmation token
cancel   -> read-only cancellation result; no target mutation
install  -> destructive path; requires the exact current target-bound token
```

Production target selection requires a stable `/dev/disk/by-id/...` path. The engine resolves the currently booted source disk and refuses to install onto that same disk. It also refuses a read-only disk, a mounted target, a non-whole-disk device and targets smaller than the minimum image size.

The first destructive action is not reached until all of those guards and the confirmation token have passed.

## VM E2E gate

`system/e2e/debian13-live-usb-install-vm-e2e.sh` performs the following on a disposable GitHub Actions VM:

1. builds the Debian 13 System Edition rootfs;
2. provisions the existing greetd/Wayland graphical-session foundation;
3. builds the final raw Live image;
4. attaches that image to QEMU as **USB storage**, alongside a separate empty virtio target disk;
5. boots the Live image through OVMF UEFI and verifies a graphical SWIR session;
6. hashes the target before installer interaction and proves idle, preview, cancel and wrong-confirmation paths do not alter it;
7. proves the booted source USB cannot be selected as the install target;
8. performs the confirmed install to the separate disk;
9. powers off, removes the Live USB from the second VM boot and boots only the installed target disk;
10. verifies graphical session startup and persistence data on the installed system.

The emitted evidence keeps these claims explicitly false:

```text
secureBootClaim = false
physicalHardwareQualificationClaim = false
graphicalInstallerClaim = false
```

## What is still required

Before the installer roadmap item can be completed, SWIR OS still needs a real graphical installer integrated into the Live desktop, with user-facing target selection, partition-plan review, account creation, language/keyboard/time-zone configuration and a final destructive confirmation screen. Physical USB boot and installation on dedicated test hardware must also be tracked separately from the VM gate.

The install engine cannot recover data after a confirmed disk erase unless an independent backup exists; the product UI must state that clearly.
