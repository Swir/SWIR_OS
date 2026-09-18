# SWIR Native Clock 0.1

SWIR Clock is a first-party native GTK4 System Edition utility for local time, alarms and calendar basics. It is installed as `/usr/local/bin/swir-clock`, uses application ID `dev.swir.Clock`, and is exposed from the fixed SWIR shell launcher.

## Verified scope

The implementation and dedicated CI gate verify a real GTK4 window under Wayland, local timezone-aware clock/date display, GTK calendar basics, and bounded alarm creation with validated 24-hour values. Alarm labels are limited to 80 characters and the application accepts at most 32 alarms. The application has no network access, privileged command path, package mutation path or self-updater. The target runtime is Debian 13 with distribution-managed GTK4/Python packages.

## Current limitation

Alarm evaluation is process-local in this foundation. Alarms operate while SWIR Clock is running. Persistent background scheduling and broader notification/session integration remain separate work and are not claimed by this milestone.

## Roadmap accounting

This foundation advances the Product Baseline `Clock / alarms / calendar basics` area but does not by itself complete the broad `essential native Linux application suite for dependable daily use` roadmap deliverable. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist criteria are actually satisfied.
