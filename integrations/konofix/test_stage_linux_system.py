import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import stage_linux_system as stage_mod

DESKTOP = """[Desktop Entry]
Type=Application
Version=1.0
Name=Konofix Chat
Exec=/opt/swir/apps/konofix/konofix-chat
TryExec=/opt/swir/apps/konofix/konofix-chat
Icon=konofix-chat
Terminal=false
Categories=Network;Chat;InstantMessaging;
"""

class StageLinuxSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.binary = self.source / stage_mod.BINARY_REL
        self.icon = self.source / stage_mod.ICON_REL
        self.binary.parent.mkdir(parents=True)
        self.icon.parent.mkdir(parents=True, exist_ok=True)
        self.binary.write_bytes(b"\x7fELF" + b"x" * 64)
        self.binary.chmod(0o755)
        self.icon.write_bytes(stage_mod.PNG + b"synthetic")
        self.desktop = self.base / "konofix-chat.desktop"
        self.desktop.write_text(DESKTOP, encoding="utf-8")
        self.root = self.base / "root"

    def git_ok(self, _root, *args):
        if args == ("rev-parse", "HEAD"):
            return stage_mod.SOURCE_COMMIT
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return "\n".join(sorted(stage_mod.EXPECTED_STATUS))
        raise AssertionError(args)

    def run_stage(self):
        with patch.object(stage_mod, "git", side_effect=self.git_ok):
            return stage_mod.stage(self.source, self.root, self.desktop)

    def test_fixed_paths_and_truthful_provenance(self):
        result = self.run_stage()
        installed = self.root / stage_mod.APP_DEST
        self.assertEqual(installed.read_bytes(), self.binary.read_bytes())
        self.assertTrue(installed.stat().st_mode & stat.S_IXUSR)
        evidence = json.loads((self.root / stage_mod.PROVENANCE_DEST).read_text())
        self.assertEqual(evidence, result)
        self.assertEqual(evidence["sourceCommit"], stage_mod.SOURCE_COMMIT)
        self.assertFalse(evidence["executedDuringStage"])
        self.assertFalse(evidence["legacyChatDataImported"])

    def test_refuses_overwrite(self):
        self.run_stage()
        before = (self.root / stage_mod.APP_DEST).read_bytes()
        with self.assertRaises(stage_mod.StageError):
            self.run_stage()
        self.assertEqual((self.root / stage_mod.APP_DEST).read_bytes(), before)

    def test_refuses_wrong_source_head(self):
        def bad(_root, *args):
            return "0" * 40 if args == ("rev-parse", "HEAD") else "\n".join(sorted(stage_mod.EXPECTED_STATUS))
        with patch.object(stage_mod, "git", side_effect=bad), self.assertRaises(stage_mod.StageError):
            stage_mod.stage(self.source, self.root, self.desktop)

    def test_refuses_unreviewed_source_change(self):
        def dirty(_root, *args):
            if args == ("rev-parse", "HEAD"):
                return stage_mod.SOURCE_COMMIT
            return "\n".join(sorted(stage_mod.EXPECTED_STATUS | {"?? surprise.txt"}))
        with patch.object(stage_mod, "git", side_effect=dirty), self.assertRaises(stage_mod.StageError):
            stage_mod.stage(self.source, self.root, self.desktop)

    def test_refuses_non_elf_candidate(self):
        self.binary.write_bytes(b"MZ" + b"x" * 64)
        with patch.object(stage_mod, "git", side_effect=self.git_ok), self.assertRaises(stage_mod.StageError):
            stage_mod.stage(self.source, self.root, self.desktop)

    def test_refuses_desktop_exec_drift(self):
        self.desktop.write_text(DESKTOP.replace(
            "Exec=/opt/swir/apps/konofix/konofix-chat", "Exec=/tmp/konofix-chat"
        ), encoding="utf-8")
        with patch.object(stage_mod, "git", side_effect=self.git_ok), self.assertRaises(stage_mod.StageError):
            stage_mod.stage(self.source, self.root, self.desktop)

    def test_refuses_symlink_binary(self):
        victim = self.base / "victim"
        victim.write_bytes(self.binary.read_bytes())
        self.binary.unlink()
        try:
            self.binary.symlink_to(victim)
        except OSError:
            self.skipTest("symlink unavailable")
        with patch.object(stage_mod, "git", side_effect=self.git_ok), self.assertRaises(stage_mod.StageError):
            stage_mod.stage(self.source, self.root, self.desktop)

if __name__ == "__main__":
    unittest.main()
