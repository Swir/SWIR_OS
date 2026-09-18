# SWIR Native Backup & Restore 0.1

SWIR Backup & Restore is a first-party unprivileged GTK4 System Edition application for protecting **SWIR-owned per-user state**. It is deliberately narrower than whole-home or disk imaging: the verified scope is `${XDG_CONFIG_HOME:-~/.config}/swir` and `${XDG_DATA_HOME:-~/.local/share}/swir` for the signed-in user only.

## Verified backup format

The runtime in `system/apps/backup_runtime.py` creates `swir.user-backup/0.1` ZIP archives with a JSON manifest and SHA-256 digest for every payload file. The implementation:

- accepts only regular files below the two allowlisted SWIR user roots;
- rejects symlinked directories/files and special files instead of following them;
- bounds a backup to 10,000 files, 128 MiB per file, 2 GiB expanded data and 3 GiB archive size;
- writes the archive as an owner-only `0600` file outside the live SWIR roots;
- never invokes a shell, package manager, `sudo`, `pkexec`, root helper or network service;
- does not claim cryptographic signing: SHA-256 here is an integrity check tied to the manifest, not an authenticity signature.

## Restore boundary

Restore always performs a complete verification and staging pass before replacing a live root. The runtime rejects unsupported schemas, duplicate/unmanifested members, absolute paths, `..` traversal, backslash paths, encrypted members, non-regular payload members, size mismatches and SHA-256 mismatches.

After staging, each SWIR root is swapped within its own parent filesystem. Existing roots are renamed to unique hidden `.swir-before-restore-*` recovery directories before staged data becomes live. If a later root commit fails, already committed roots are rolled back where possible. The UI requires an independently verified archive and a separate destructive-action confirmation before calling restore.

The previous roots are intentionally **preserved**, not automatically deleted. This avoids pretending that destructive recovery is reversible without retained data. Users can inspect or remove old recovery directories later after verifying the restored state.

## Explicit non-goals

This milestone does **not** back up the full home directory, arbitrary documents, system packages, bootloader state, partitions, external devices, other users, secrets outside SWIR roots or the physical-disk installer state. It is not a substitute for the System Edition installation/recovery transaction layer.

## Integration

The application is installed as `/usr/local/bin/swir-backup`, uses application ID `dev.swir.Backup`, has a desktop entry and is allowlisted in the native SWIR Shell launcher. `backup_runtime.py` is staged root-owned/read-only under `/usr/local/lib/swir/` while all user backup/restore operations remain in the unprivileged desktop process.

`.github/workflows/system-native-backup-restore.yml` verifies Python compilation, runtime self-tests, hostile-path policy, desktop integration, a real GTK4 window on Weston/Wayland, an actual create → mutate → inspect → restore cycle in disposable user roots, and the exact Debian 13 GTK4 target runtime.

## Roadmap accounting

This materially advances the still-open `essential native Linux application suite for dependable daily use` requirement by providing the required Backup/Restore entry point. It does **not** by itself close that broad roadmap item and therefore does not change the canonical progress percentage in this implementation PR.
