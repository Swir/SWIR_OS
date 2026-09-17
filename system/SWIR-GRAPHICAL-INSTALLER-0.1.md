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

The existing Live USB E2E remains the authoritative destructive-path VM gate. The graphical installer roadmap item must remain open until the GTK application is provisioned into that final Live image and the complete UI-driven path is exercised there.

## Current limitations

- This 0.1 UI does not claim physical-hardware qualification.
- Secure Boot and legacy BIOS are not claimed.
- The current locale/keyboard/time-zone pick lists are intentionally small and must expand through the shared i18n architecture.
- The current Polkit policy requires administrator authentication for the destructive action. The final Live-account authorization UX must be qualified before public release.
- No promise is made that erased/formatted data can be recovered. A separate backup is required before destructive installation.
- The final roadmap gate also requires integration into the final Live image and an end-to-end UI-driven install on disposable media before it can be checked complete.
