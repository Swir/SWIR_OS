# Konofix replacement integration

User decision, 2026-09-24: **Konofix replaces the legacy SWIR Chat**, rather than
introducing a second competing messenger. Tracking: [issue #96](https://github.com/Swir/SWIR_OS/issues/96).
All OS integration and verification belongs to `Swir/SWIR_OS`; Konofix remains
its existing upstream project. The portfolio repository is not an integration,
package or update authority.

## Current implementation boundary

`integrations/konofix/prepare.py` prepares the reviewed **Konofix Chat 0.5.1
Stable Windows x64 installer** from a pinned release URL, size and SHA-256.
It is functional download/verification code, **not a completed chat integration**:
it does not install or launch Konofix, replace a menu entry, port its GUI to Linux,
connect to peers, import chat data, publish an OS release or satisfy production
SWIR package-signing gates. The old client/backend and user data remain untouched
until the replacement works and its integration tests pass.

The upstream source is pinned to
`31298cc732c97ff90230c3743cd1c3be17f40b6c` at
[`Swir/Konofix` tag `v0.5.1`](https://github.com/Swir/Konofix/tree/31298cc732c97ff90230c3743cd1c3be17f40b6c).
The reviewed release is [Konofix Chat 0.5.1 Stable](https://github.com/Swir/Konofix/releases/tag/v0.5.1),
release ID `394657665`, installer asset ID `583769724`.
These are upstream references, not SWIR OS releases. Mutable release assets or
tags must never silently refresh the pin: changed bytes fail verification.

The Windows GUI build currently places Tauri and its file-dialog dependencies
under `cfg(windows)` in upstream Cargo.toml. A working Linux **headless Node** is
not evidence of a Linux desktop GUI. System Edition qualification and any
managed Windows compatibility qualification remain outstanding. Do not rewrite
Konofix's peer protocol or rename the old PHP chat and call it Konofix.

## Preparation

Requires Python 3.10+ and a TLS connection to the official GitHub release/CDN.
Python is a developer/preparation requirement, **not a new end-user runtime
requirement for the final OS**. Paths are explicit; nothing runs on import or on
a timer. From the SWIR OS checkout:

```sh
python integrations/konofix/prepare.py --output /path/to/new/konofix-stage
python integrations/konofix/prepare.py --verify /path/to/new/konofix-stage/Konofix-Chat-0.5.1-x64-Setup.exe
python -m unittest discover -s integrations/konofix -p 'test_*.py' -v
```

The output contains `status: verified-download-only`, `installed: false` and
`executed: false`. Verification is available offline. A verified existing output
is an idempotent no-op; a mismatching file is not overwritten. Downloads use an
exclusive temporary file, bounded transfer, SHA-256 verification and atomic
no-overwrite publication. Filesystems without hard-link support fail closed.
This helper never formats disks, changes permissions/firewalls, invokes a shell,
changes update policy or requests elevation. Failed downloads remove only their
own temporary file. Redirects are HTTPS-only and restricted to the expected
GitHub URL and `release-assets.githubusercontent.com`; no credentials or arbitrary
URLs are accepted by the CLI. Signed CDN query strings are not logged on errors.

The reviewed SHA-256 pin proves byte integrity relative to this source-controlled
pin. **It is not a commercial publisher signature**, a trusted `.swirapp`
signature, or proof that the installer is safe on every host. This downloader is
unprivileged and does not claim to defeat a malicious same-user process changing
the filesystem. The final installation/launch broker must revalidate the exact
payload immediately before any explicitly authorized execution and preserve all
existing OS trust and permission boundaries.

## Replacement acceptance boundary

The integration task requires the real existing Konofix client and branding,
not another messenger mockup. Desktop needs authorized launch/install ownership,
missing-client handling, focus and restart behavior. System needs its own usable,
qualified client path, without treating the Node daemon as a chat window.
Web Edition must state its actual capability instead of embedding a Tauri
frontend that cannot access its native runtime.

Acceptance must exercise real peers: public/private rooms, private messages,
nickname collision, approved/refused/cancelled file transfers, reconnect,
notifications, mute/ignore, supported locales with English fallback and keyboard
accessibility. Unfinished audio/video must not be advertised as available.
Konofix identity/storage stays distinct: no silent transfer of SWIR credentials,
legacy server credentials, conversation history or files. Retiring the old default
entry must not delete legacy data or historical evidence.

This preparatory draft does not change any completed roadmap checkbox. The
explicitly requested replacement is now recorded as an **unchecked** deliverable
in the canonical Version roadmap in `SWIR-OS-ARCHITECTURE.md`; the authoritative
SVG/math therefore includes unfinished Konofix work in its denominator. This
document and issue #96 define acceptance details, not a second source of progress
percentages.
No website synchronization or OS release is justified by a download-only helper.

## Verification scope

The offline tests use inert synthetic bytes and test pin validation, exact-size
and digest rejection, disallowed redirects, interrupted/oversized downloads,
publication races, symlinks, preservation of existing files and idempotence.
The dedicated CI additionally downloads and re-reads the real pinned release
asset without executing it, then runs the unchanged canonical roadmap/SVG checks.
Neither test path is a Konofix GUI launch, a peer interoperability test, an OS
installation test or a claim that the old chat has already been replaced.
