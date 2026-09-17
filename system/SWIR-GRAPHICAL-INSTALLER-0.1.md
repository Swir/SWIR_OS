# SWIR OS System Edition — Graphical Installer 0.1

## Purpose

This milestone adds the first **native GTK4 installer UI** for SWIR OS Live media. It sits on top of the already verified safety-first install engine rather than reimplementing partitioning in the GUI.

The graphical installer is deliberately split into three privilege layers:

```text
GTK4 UI (unprivileged active session)
        |
        | JSON request over stdin
        v
pkexec + dev.swir.installer.install
        |
        v
narrow root helper
        |
        +--> re-run read-only target preview
        +--> verify exact target-bound erase token
        +--> guarded swir-install-engine
        +--> configure installed user/locale/keyboard/time-zone
```

The UI never executes arbitrary shell text, never receives a generic root command channel and does not perform partition writes itself.

## User flow

1. Start `Install SWIR OS` from the Live environment.
2. Select an eligible whole disk exposed through a stable `/dev/disk/by-id/...` identity.
3. Read the exact target model, size and partition plan returned by the existing read-only install-engine preview.
4. Configure the first installed account, locale, keyboard layout and time zone.
5. Review the destructive operation.
6. Type the exact `ERASE-SWIR-xxxxxxxxxxxx` token bound to the current target identity.
7. Authorize the narrow privileged helper through Polkit.
8. The helper repeats preview immediately before mutation. A stale/mismatched token fails closed.
9. The guarded engine partitions and copies the system.
10. The helper mounts only the new `SWIR_ROOT` partition and writes the requested account/region configuration.
11. Shut down, remove the Live USB and boot the installed disk.

Passwords are passed to the privileged helper over stdin and are not written to installer result/evidence JSON.

## Live-only boundary

The privileged helper refuses to operate unless `/var/lib/swir/live/live.json` exists as a regular file. The install engine independently rejects the currently booted source disk and requires a stable target identity. Keeping the helper/policy in the cloned installed filesystem therefore does not make installation available from the installed system: the Live marker is removed by the install engine before first installed boot.

## Native UI verification

`.github/workflows/system-graphical-installer-contract.yml` performs:

- Python compile checks;
- UI and privileged-helper self-tests;
- Polkit XML validation and fail-closed policy checks;
- a real GTK4 window launch against a headless Weston Wayland compositor;
- evidence proving the smoke launch performed no disk mutation;
- canonical roadmap validation.

The final Live USB image gate also provisions the GTK application and smoke-launches its real window before the existing guarded engine path installs to a disposable target disk and verifies detached boot.

### Full GTK-driven disposable VM gate

`.github/workflows/system-graphical-installer-e2e.yml` adds the stronger qualification lane required before the graphical-installer roadmap item may be checked complete. It boots the final raw Live image as USB mass storage under OVMF, starts the real GTK4 installer in the real Live Wayland session and drives the same production page callbacks used by an interactive user.

The gate must prove all of the following before the milestone can close:

- the GUI selects the exact stable `/dev/disk/by-id/...` target from the visible target list;
- preview remains read-only and source-media targeting is rejected;
- an intentionally wrong confirmation token is blocked by the final GTK review before installation begins;
- account, locale, keyboard and time-zone values pass through the real UI widgets and normal validation path;
- the correct target-bound token starts the normal `pkexec` + narrow-helper path rather than a separate test installer;
- the installed root contains the requested account and regional configuration without storing password material in evidence;
- the source USB is removed from the second VM boot;
- the installed disk boots graphically and preserves installed data.

The deterministic UI driver is deliberately unavailable on normal Live media. The disposable E2E image must create a root-owned `/run/swir/installer-e2e-enabled` marker and a root-owned `/run/swir/installer-e2e-*` configuration file. The test password is supplied only to the disposable VM process and must never appear in committed files or generated evidence. A test-only Polkit authorization rule is injected into the disposable CI rootfs so the real `pkexec` helper can be exercised non-interactively; that rule is not part of normal Live media provisioning.

Machine-readable evidence is validated against `system/contracts/system-graphical-installer-e2e.schema.json` and `system/image/validate-graphical-installer-e2e.mjs`.

The roadmap item remains open until this full GTK-driven gate succeeds on the final branch head. Physical USB/hardware qualification remains a separate later gate even after the VM workflow passes.

## Current limitations

- This 0.1 UI does not claim physical-hardware qualification.
- Secure Boot and legacy BIOS are not claimed.
- The current locale/keyboard/time-zone pick lists are intentionally small and must expand through the shared i18n architecture.
- The normal Live Polkit policy requires administrator authentication for the destructive action. The final Live-account authorization UX must be qualified before public release.
- No promise is made that erased/formatted data can be recovered. A separate backup is required before destructive installation.
- The graphical-installer roadmap item cannot be checked complete merely because the window renders; its full disposable-media UI-driven install and detached-boot evidence must be green.
