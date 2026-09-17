# SWIR Graphical Session UEFI E2E 0.1

## Purpose

This lane moves System Edition beyond a console-only boot proof and an empty compositor surface. It builds a disposable Debian 13 image from the controlled foundation, installs graphical components from Debian's signed repositories, boots the image through OVMF and `systemd-boot`, verifies that the SWIR Plymouth theme is actually active during boot, authenticates a disposable user through the real `greetd` + PAM path, starts the SWIR Wayland session, and requires the native GTK4 SWIR shell to map its real fullscreen desktop window.

The shell is part of the authenticated local user session. It is not a browser/PWA surface and it does not perform privileged mutations itself.

## Production composition

The production graphical path uses distro-managed components plus the repository-owned native shell:

```text
Debian 13 signed repositories
        |
        +--> plymouth + plymouth-themes
        +--> greetd + distro PAM policy
        +--> weston + wayland-utils
        +--> dbus-user-session
        +--> GTK4 + PyGObject
        |
        v
SWIR graphical image provisioner
        |
        +--> SWIR Plymouth theme in initramfs
        +--> greetd display-manager service
        +--> authenticated agreety login
        +--> /usr/local/bin/swir-session
        +--> Weston Wayland compositor
        +--> /usr/local/bin/swir-shell
        +--> native GTK4 SWIR desktop surface
```

Production configuration deliberately keeps `agreety` as the minimal authenticated greeter while a branded graphical SWIR login UI remains future work. There is no `initial_session` auto-login block. PAM remains the authentication authority; a successful greeter interaction is not treated as an identity proof outside the resulting logind session.

## Native shell scope

`system/session/swir-shell.py` is the first real System Edition desktop shell. The verified 0.1 surface provides:

- a native GTK4 fullscreen Wayland window with SWIR dark/electric-cyan presentation;
- SWIR OS/System Edition identity, clock and status surface;
- a fixed, allowlisted launcher model for Files, Terminal, Settings and the SWIR installer;
- explicit unavailable-app feedback rather than fake placeholder launches;
- fixed argv subprocess execution with no `shell=True` path;
- no privileged system mutation inside the shell process;
- supervision by `swir-session`, so a shell crash returns the authenticated session to the greeter rather than silently leaving an empty compositor.

This closes the measured `SWIR desktop shell` foundation. It does **not** close the separate essential native application-suite milestone: File Manager, Settings, Store/Updater, Driver Center UI, browser, media, diagnostics and the remaining daily-use applications still require their own native implementations/integration and verification.

## Disposable CI authentication

Automated E2E cannot type into an interactive TTY reliably, so the disposable test image installs `greetd-e2e-greeter.py`. This small CI-only client speaks greetd's Unix-socket IPC protocol and answers the real PAM conversation for a dedicated unprivileged account named `swir-e2e`.

Important boundaries:

- the E2E credential exists only in the disposable VM composition;
- the production provisioning path never installs the E2E greeter and explicitly checks that the test credential is absent from production `greetd` configuration;
- no greetd `initial_session` auto-login is used;
- the final session must be attributed by `systemd-logind` to the authenticated UID and `Service=greetd`;
- the session must be local (`Remote=no`).

## Boot-splash proof

The image contains a custom script-based Plymouth theme at `/usr/share/plymouth/themes/swir`. Provisioning selects it through the distro `plymouth-set-default-theme` tool and regenerates every installed initramfs. Before boot, the host verifies that the theme descriptor is embedded in the actual initramfs copied to the EFI System Partition.

During guest boot a dedicated early proof service requires:

- selected theme `swir`;
- kernel command line containing `quiet splash`;
- a responsive Plymouth daemon through `plymouth --ping` before the normal Plymouth quit phase.

This is stronger evidence than merely checking that theme files exist on disk.

## Wayland + shell proof

After PAM authentication, greetd starts `/usr/local/bin/swir-session`. In E2E mode the launcher starts Weston with the headless backend, waits for its real Wayland socket, starts `/usr/local/bin/swir-shell`, and accepts shell evidence only after GTK emits the window `map` event. The shell evidence must identify `dev.swir.Shell`, GTK4 and Wayland, prove the fullscreen desktop window mapped, list the fixed launcher entries, confirm the unprivileged launcher subprocess path executed successfully, and state that privileged operations are absent from the shell.

The session launcher separately runs `wayland-info` against the same compositor socket and ties the session back to the authenticated UID in logind. The final host-side evidence accepts `desktopShellClaim=true` only when all of those runtime checks pass.

The headless backend is intentional for GitHub-hosted QEMU. The image still boots with a virtual VGA device, but this gate verifies session composition, Wayland protocol readiness and native shell startup rather than claiming physical GPU/DRM qualification.

## Fail-closed claims

A successful `swir.system-graphical-session-e2e/0.1` report now proves the scoped shell foundation:

- UEFI/systemd-boot reaches graphical target;
- SWIR Plymouth theme is active during boot;
- greetd and distro PAM perform a real authentication exchange;
- no auto-login path is used;
- systemd-logind observes a local greetd user session;
- Weston exposes a live Wayland socket that a client can use;
- the native GTK4 SWIR shell starts in that authenticated session and maps its fullscreen Wayland window;
- the shell's fixed launcher subprocess path is exercised without a shell-mode command interpreter;
- privileged system mutation remains outside the shell.

The report intentionally keeps these claims false:

```text
secureBootClaim = false
hardwareQualificationClaim = false
```

It does not qualify Secure Boot, physical GPU acceleration, multi-seat, suspend/resume, physical display hardware, a branded graphical login UI, the complete native application suite or physical Live USB/install hardware support.

## Roadmap rule

`SWIR boot splash and login/session manager` remains complete from the earlier authenticated graphical gate. `SWIR desktop shell` may be marked complete only because the exact shell implementation revision passed the UEFI graphical E2E with a real mapped GTK4 Wayland desktop and exercised launcher path. Application-suite, theme-framework and hardware-qualification deliverables remain independent roadmap gates.
