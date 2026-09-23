#!/usr/bin/env python3
"""One-shot finalizer for the verified System Edition native daily-use suite milestone."""
from pathlib import Path
import subprocess


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Canonical roadmap: the exact-head native-suite integration snapshot 2656cba4
# passed all ten relevant PR workflows, including the umbrella Daily Suite and
# the dedicated Photo Studio/Player/Browser/Task Manager/Diagnostics authorities.
replace_exact("SWIR-OS-ARCHITECTURE.md", "ROADMAP-87.7%25-2ea043", "ROADMAP-89.2%25-2ea043")
replace_exact("SWIR-OS-ARCHITECTURE.md", "DONE-57%2F65-1f6feb", "DONE-58%2F65-1f6feb")
replace_exact(
    "SWIR-OS-ARCHITECTURE.md",
    'alt="SWIR OS roadmap progress — 87.7%, 57 of 65 verified deliverables"',
    'alt="SWIR OS roadmap progress — 89.2%, 58 of 65 verified deliverables"',
)
replace_exact(
    "SWIR-OS-ARCHITECTURE.md",
    "| **57** | **8** | **65** | **87.7%** |",
    "| **58** | **7** | **65** | **89.2%** |",
)
replace_exact(
    "SWIR-OS-ARCHITECTURE.md",
    "- [ ] essential native Linux application suite for dependable daily use",
    "- [x] essential native Linux application suite for dependable daily use",
)
replace_exact(
    "SWIR-OS-ARCHITECTURE.md",
    "The first-party SWIR Photo Studio basic-editing milestone is now verified on the native GTK4/GdkPixbuf path for local regular image files, with bounded input limits, rotate/flip/resize editing, a bounded 24-state undo/redo history and explicit atomic owner-only PNG/JPEG/WebP export while preserving the source file. The dedicated Wayland gate maps the real GTK4 window and exercises edit/export behavior, and the Debian 13 target gate verifies the distro-managed GTK4/GdkPixbuf runtime. The application remains unprivileged and has no self-updater or direct package mutation. This closes only the dedicated basic Photo Studio roadmap item; the broader daily-use suite and advanced Product Baseline editing capabilities remain open.",
    "The first-party SWIR Photo Studio milestone is verified on the native GTK4/GdkPixbuf path for bounded local regular image files with rotate/flip/resize, rectangular crop, exposure/brightness/contrast/saturation controls, filters, bounded text and line annotation, a bounded 24-state undo/redo history and explicit atomic owner-only PNG/JPEG/WebP export while preserving the source file. Its dedicated Wayland gate verifies the localized EN/PL/NO runtime surface, English fallback, text direction and keyboard-focus/tool-tip accessibility, while the Debian 13 target gate verifies the distro-managed GTK4/GdkPixbuf runtime. The application remains unprivileged with no self-updater or direct package mutation; together with the suite-wide exact-head gate this contributes to the completed essential native daily-use suite milestone.",
)

# Suite evidence document: record the verified acceptance snapshot without making
# the integration verifier itself an automatic roadmap shortcut.
replace_exact(
    "system/SWIR-NATIVE-DAILY-SUITE-0.1.md",
    "Photo Studio now closes the last identified locale/accessibility surface with reviewed EN/PL/NO chrome, deterministic English fallback, applied text direction, keyboard focus/tool-tip evidence and the existing local-file/non-destructive safety boundary. The remaining umbrella completion step is the exact-head **suite-wide daily-use integration verification**; the roadmap item must stay open until that integration gate and the dedicated application gates are green on the same final branch snapshot.",
    "Photo Studio closes the last identified locale/accessibility surface with reviewed EN/PL/NO chrome, deterministic English fallback, applied text direction, keyboard focus/tool-tip evidence and the existing local-file/non-destructive safety boundary. Exact-head acceptance snapshot `2656cba4884220084a9411e424530bc9e7e45381` then passed all ten relevant PR workflows, including System Native Daily Suite plus the dedicated Browser, Player, Photo Studio, Task Manager, Diagnostics, Text Editor, Default Apps, Core Apps and System Edition contract gates. That evidence satisfies the umbrella `essential native Linux application suite for dependable daily use` roadmap deliverable; it does not imply full System Edition release readiness or physical-hardware qualification.",
)

# README follows the same verified roadmap snapshot and removes stale claims that
# the native suite / Photo Studio Product Baseline depth are still open.
replace_exact("README.md", "ROADMAP-87.7%25-02050A", "ROADMAP-89.2%25-02050A")
replace_exact("README.md", "DONE-57%2F65-02050A", "DONE-58%2F65-02050A")
replace_exact(
    "README.md",
    'alt="SWIR OS roadmap progress — 87.7%, 57 of 65 verified deliverables"',
    'alt="SWIR OS roadmap progress — 89.2%, 58 of 65 verified deliverables"',
)
replace_exact(
    "README.md",
    "**Measured scope:** full Web → Desktop → System `Version roadmap`. **Project progress:** 57/65 = **87.7%**. **Release readiness:** not ready; physical Live USB qualification, the complete native application suite and other release gates remain open.",
    "**Measured scope:** full Web → Desktop → System `Version roadmap`. **Project progress:** 58/65 = **89.2%**. **Release readiness:** not ready; physical Live USB qualification, supported-device fwupd/LVFS validation, Desktop signing/update-feed work and other release gates remain open.",
)
replace_exact(
    "README.md",
    "**57 of 65 measurable roadmap deliverables are complete.**",
    "**58 of 65 measurable roadmap deliverables are complete.**",
)
replace_exact(
    "README.md",
    "| 🖼️ **Native Photo Studio** | SWIR Photo Studio now runs natively on GTK4/GdkPixbuf for bounded local image files with rotate/flip/resize editing, 24-state undo/redo and explicit atomic owner-only PNG/JPEG/WebP export while preserving the source file. Its Wayland and Debian 13 gates are verified; advanced Product Baseline editing remains open. |",
    "| 🖼️ **Native Photo Studio** | SWIR Photo Studio now runs natively on GTK4/GdkPixbuf for bounded local image files with rotate/flip/resize, rectangular crop, exposure/brightness/contrast/saturation, filters, bounded text and line annotation, 24-state undo/redo and explicit atomic owner-only PNG/JPEG/WebP export while preserving the source file. Its Wayland/Debian 13 gates and EN/PL/NO locale/accessibility runtime evidence are verified. |",
)
replace_exact(
    "README.md",
    "1. build the mandatory native application suite on top of the verified SWIR desktop shell,\n2. harden the Desktop host/update/signing lifecycle,\n3. verify fwupd/LVFS mutation on supported hardware while keeping the verified official-vendor repository path fail-closed,\n4. qualify physical Live USB boot/install and recovery on dedicated hardware,\n5. finish full-system i18n, reliability and accessibility without inflating VM evidence into hardware claims.",
    "1. harden the Desktop host signing and signed stable/preview update-feed lifecycle,\n2. verify fwupd/LVFS mutation on supported hardware while keeping the verified official-vendor repository path fail-closed,\n3. qualify physical Live USB boot/install and recovery on dedicated hardware,\n4. expand full-system i18n, reliability and accessibility beyond the verified EN/PL/NO native-suite gate without inflating VM evidence into hardware claims.",
)
replace_exact(
    "README.md",
    "- The native GTK4 SWIR shell and installable accessibility-safe shell theme/skin framework are verified, but the full daily-use native application suite is not complete.\n- SWIR Photo Studio currently verifies the dedicated basic-editing milestone; advanced Product Baseline editing such as crop, exposure/color/filter, annotation/drawing and broader workflow depth remains open.",
    "- The essential native daily-use application suite is now verified through its suite-wide integration gate and dedicated runtime authorities; this does not complete the remaining System Edition hardware/release gates.\n- SWIR Photo Studio now verifies the Product Baseline editing depth used by the suite gate, including crop, exposure/color controls, filters, bounded text/drawing annotation, undo/redo and common-format export.",
)
replace_exact(
    "README.md",
    "- Full localization of every native System Edition application screen is not complete.",
    "- The supported first-party native daily-use suite has verified EN/PL/NO locale/accessibility coverage with English fallback; broader 15-locale full-surface parity remains future work.",
)

subprocess.run(["node", "scripts/generate-readme-progress.mjs"], check=True)
subprocess.run(["node", "scripts/generate-readme-progress.mjs", "--check"], check=True)
