# SWIR Native Task Manager 0.1

Status: implemented System Edition process-control foundation inside the native **SWIR System Monitor**.

## Purpose

The Processes tab provides a bounded native view of current Linux processes plus a deliberately narrow way for the signed-in user to request graceful termination of one of their own processes. It is not a root process manager and it does not expose arbitrary signals, process groups or privilege escalation.

## Process identity and safety contract

- Process inventory is read from `/proc` and capped at 200 visible source rows, sorted by resident memory.
- The UI provides an 80-character name/PID filter without shell execution or external commands.
- A termination target carries PID, real UID, process name and `/proc/PID/stat` start time.
- Immediately before signaling, SWIR re-reads the target and rejects ownership, start-time or name changes so a recycled PID is not silently targeted.
- Only a process whose real UID equals `os.getuid()` can be ended.
- PID 1, the System Monitor itself and its discovered ancestor/session chain are protected.
- The only signal exposed by this surface is `SIGTERM`; there is no `SIGKILL`, process-group kill or arbitrary signal selector.
- Linux pidfd signaling is preferred where the runtime supports `os.pidfd_open` and `signal.pidfd_send_signal`; the bounded fallback is a single-PID `os.kill(..., SIGTERM)` after identity revalidation.
- The GUI requires an explicit confirmation dialog and warns that unsaved work in the target application may be lost.
- No `sudo`, `su`, `pkexec`, Polkit request, shell command or privileged helper is used by process termination.

## Diagnostics boundary

The separate Diagnostics tab remains read-only. Its fixed `systemctl` and `journalctl` queries do not gain service-management or log-mutation privileges from this Task Manager work.

## Verification

`.github/workflows/system-native-task-manager.yml` verifies syntax and the pure policy self-test, rejects forbidden escalation/SIGKILL/process-group paths, exercises a real SIGTERM against a disposable child owned by the CI user, maps the real GTK4 application on headless Wayland and checks bounded runtime evidence. A Debian 13 container gate verifies the target Python/GTK4 runtime and pidfd support. The existing diagnostics and native-core workflows continue to run when the shared System Monitor changes.

## Roadmap accounting

This materially improves the Task Manager / System Monitor part of the native daily-use suite, but it does **not** by itself close the umbrella `essential native Linux application suite for dependable daily use` roadmap item. Canonical roadmap progress must remain unchanged until that existing deliverable is actually complete and verified.
