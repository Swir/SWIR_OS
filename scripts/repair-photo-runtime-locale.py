#!/usr/bin/env python3
"""One-shot branch repair for the final native-suite integration gate."""
from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_exact(
    "system/apps/verify-native-daily-suite.py",
    '"swir.native-photo-studio-runtime-evidence/0.3",',
    '"swir.native-photo-studio-runtime-evidence/0.4",',
)

replace_exact(
    "system/SWIR-NATIVE-DAILY-SUITE-0.1.md",
    "Calculator, Notes, Network Center, Text Editor, Clock, Terminal, Screenshot Tool, Software Center, Update Center, Files, Archive Manager, Hardware & Driver Center, PDF Viewer, Backup/Restore, Settings, Browser, Player, Task Manager and Diagnostics consume the bounded per-user SWIR language preference",
    "Calculator, Notes, Network Center, Text Editor, Clock, Terminal, Screenshot Tool, Software Center, Update Center, Files, Archive Manager, Hardware & Driver Center, PDF Viewer, Backup/Restore, Settings, Browser, Player, Photo Studio, Task Manager and Diagnostics consume the bounded per-user SWIR language preference",
)

replace_exact(
    "system/SWIR-NATIVE-DAILY-SUITE-0.1.md",
    "The remaining umbrella completion gate is **suite-wide locale/accessibility depth and final daily-use integration verification across the supported first-party applications**. The verified slices above reduce that gap but do not complete it; a green inventory/evidence gate must not hide the remaining product-depth work or inflate roadmap progress. The largest remaining locale/accessibility surface is Photo Studio.",
    "Photo Studio now closes the last identified locale/accessibility surface with reviewed EN/PL/NO chrome, deterministic English fallback, applied text direction, keyboard focus/tool-tip evidence and the existing local-file/non-destructive safety boundary. The remaining umbrella completion step is the exact-head **suite-wide daily-use integration verification**; the roadmap item must stay open until that integration gate and the dedicated application gates are green on the same final branch snapshot.",
)
