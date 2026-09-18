#!/usr/bin/env python3
"""SWIR Files and its native safe Archive Manager mode for System Edition."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import posixpath
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from typing import BinaryIO, Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import DirectoryEntry, list_directory, resolve_directory  # noqa: E402

APP_ID: Final = "dev.swir.Files"
ARCHIVE_APP_ID: Final = "dev.swir.ArchiveManager"
EVIDENCE_SCHEMA: Final = "swir.native-files-runtime-evidence/0.1"
ARCHIVE_EVIDENCE_SCHEMA: Final = "swir.native-archive-manager-runtime-evidence/0.1"
MAX_ARCHIVE_BYTES: Final = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES: Final = 5000
MAX_ARCHIVE_MEMBER_BYTES: Final = 512 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES: Final = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_PATH_BYTES: Final = 4096
ARCHIVE_CHUNK_BYTES: Final = 1024 * 1024
SUPPORTED_ARCHIVE_SUFFIXES: Final = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2")

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-path { background: #07111C; color: #F4FAFF; border: 1px solid rgba(98,229,255,0.32); border-radius: 10px; padding: 8px 12px; }
.swir-file-row { padding: 9px 12px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-file-row:hover { background: rgba(0,136,255,0.10); }
.swir-panel { background: #07111C; border: 1px solid rgba(98,229,255,0.22); border-radius: 14px; padding: 10px; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 10px; padding: 7px 12px; font-weight: 700; }
"""


def human_size(size: int | None) -> str:
    if size is None:
        return ""
    value = float(size)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return ""


class ArchivePolicyError(RuntimeError):
    """Archive input or extraction violates the fail-closed user-file policy."""


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    size: int
    is_dir: bool


def _path_has_symlink(path: pathlib.Path) -> bool:
    absolute = path if path.is_absolute() else (pathlib.Path.cwd() / path)
    current = pathlib.Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink():
            return True
    return False


def _archive_suffix(path: pathlib.Path) -> str:
    lower = path.name.lower()
    return next((suffix for suffix in SUPPORTED_ARCHIVE_SUFFIXES if lower.endswith(suffix)), "")


def _validated_archive(raw: str | pathlib.Path) -> pathlib.Path:
    text = str(raw)
    if text.startswith(("http://", "https://", "data:", "file://")):
        raise ArchivePolicyError("remote/URI archive input is not accepted")
    path = pathlib.Path(raw).expanduser().absolute()
    if len(os.fsencode(path)) > MAX_ARCHIVE_PATH_BYTES:
        raise ArchivePolicyError("archive path is too long")
    if _path_has_symlink(path):
        raise ArchivePolicyError("symbolic-link archive paths are not accepted")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArchivePolicyError(f"archive path cannot be resolved: {exc}") from exc
    if resolved != path or not resolved.is_file() or not os.access(resolved, os.R_OK):
        raise ArchivePolicyError("archive must be a canonical readable regular file")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_ARCHIVE_BYTES:
        raise ArchivePolicyError("archive file size is outside the verified bound")
    if not _archive_suffix(resolved):
        raise ArchivePolicyError("unsupported archive type")
    return resolved


def _safe_member_parts(name: str) -> tuple[str, ...]:
    if not name or "\x00" in name or "\\" in name:
        raise ArchivePolicyError("archive contains an invalid member path")
    if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
        raise ArchivePolicyError("archive contains an absolute member path")
    normalized = posixpath.normpath(name)
    parts = tuple(part for part in normalized.split("/") if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        raise ArchivePolicyError("archive member escapes the extraction root")
    if len(os.fsencode("/".join(parts))) > MAX_ARCHIVE_PATH_BYTES:
        raise ArchivePolicyError("archive member path is too long")
    return parts


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


def _scan_zip(path: pathlib.Path) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    total = 0
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ArchivePolicyError("archive contains too many entries")
            for info in infos:
                _safe_member_parts(info.filename.rstrip("/") or info.filename)
                if info.flag_bits & 0x1:
                    raise ArchivePolicyError("encrypted ZIP members are not supported")
                if _zip_member_is_symlink(info):
                    raise ArchivePolicyError("symbolic links in archives are not accepted")
                is_dir = info.is_dir()
                size = 0 if is_dir else int(info.file_size)
                if size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ArchivePolicyError("archive member exceeds the verified size bound")
                total += size
                if total > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ArchivePolicyError("expanded archive exceeds the verified total-size bound")
                entries.append(ArchiveEntry(info.filename.rstrip("/"), size, is_dir))
    except zipfile.BadZipFile as exc:
        raise ArchivePolicyError(f"ZIP archive cannot be read: {exc}") from exc
    return entries


def _scan_tar(path: pathlib.Path) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    total = 0
    try:
        with tarfile.open(path, "r:*") as archive:
            members = archive.getmembers()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise ArchivePolicyError("archive contains too many entries")
            for member in members:
                _safe_member_parts(member.name.rstrip("/") or member.name)
                if not (member.isdir() or member.isfile()):
                    raise ArchivePolicyError("links, devices and special archive members are not accepted")
                size = 0 if member.isdir() else int(member.size)
                if size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ArchivePolicyError("archive member exceeds the verified size bound")
                total += size
                if total > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ArchivePolicyError("expanded archive exceeds the verified total-size bound")
                entries.append(ArchiveEntry(member.name.rstrip("/"), size, member.isdir()))
    except tarfile.TarError as exc:
        raise ArchivePolicyError(f"TAR archive cannot be read: {exc}") from exc
    return entries


def _scan_archive(path: pathlib.Path) -> list[ArchiveEntry]:
    return _scan_zip(path) if path.name.lower().endswith(".zip") else _scan_tar(path)


def _validated_destination_parent(raw: str | pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw).expanduser().absolute()
    if len(os.fsencode(path)) > MAX_ARCHIVE_PATH_BYTES:
        raise ArchivePolicyError("destination path is too long")
    if _path_has_symlink(path):
        raise ArchivePolicyError("destination path may not traverse symbolic links")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArchivePolicyError(f"destination path cannot be resolved: {exc}") from exc
    if resolved != path or not resolved.is_dir() or not os.access(resolved, os.W_OK):
        raise ArchivePolicyError("destination must be a canonical writable directory")
    return resolved


def _open_child_dir(parent_fd: int, name: str, *, create: bool) -> int:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ArchivePolicyError(f"unsafe extraction directory component: {name}") from exc
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise ArchivePolicyError("extraction directory component is not a directory")
    return fd


def _ensure_directory(root_fd: int, parts: tuple[str, ...]) -> None:
    current = os.dup(root_fd)
    try:
        for part in parts:
            child = _open_child_dir(current, part, create=True)
            os.close(current)
            current = child
    finally:
        os.close(current)


def _write_regular(root_fd: int, parts: tuple[str, ...], source: BinaryIO, expected_size: int) -> str:
    if len(parts) > 1:
        _ensure_directory(root_fd, parts[:-1])
    parent = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = _open_child_dir(parent, part, create=False)
            os.close(parent)
            parent = child
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(parts[-1], flags, 0o600, dir_fd=parent)
        except OSError as exc:
            raise ArchivePolicyError(f"refusing existing or unsafe extraction target: {'/'.join(parts)}") from exc
        digest = hashlib.sha256()
        written = 0
        try:
            while True:
                chunk = source.read(ARCHIVE_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > expected_size or written > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ArchivePolicyError("archive member expanded beyond its declared bound")
                view = memoryview(chunk)
                while view:
                    consumed = os.write(fd, view)
                    view = view[consumed:]
                digest.update(chunk)
            if written != expected_size:
                raise ArchivePolicyError("archive member size changed during extraction")
            os.fsync(fd)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        return digest.hexdigest()
    finally:
        os.close(parent)


def _extraction_root_name(path: pathlib.Path) -> str:
    base = path.name
    for suffix in sorted(SUPPORTED_ARCHIVE_SUFFIXES, key=len, reverse=True):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in base).strip(".") or "archive"


def _extract_archive(path: pathlib.Path, destination_parent: pathlib.Path) -> tuple[pathlib.Path, list[str]]:
    path = _validated_archive(path)
    entries = _scan_archive(path)
    parent = _validated_destination_parent(destination_parent)
    root = parent / f"{_extraction_root_name(path)}-extracted"
    try:
        root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ArchivePolicyError("extraction target already exists; choose another destination or rename it") from exc
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    digests: list[str] = []
    try:
        if path.name.lower().endswith(".zip"):
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                for entry, info in zip(entries, infos, strict=True):
                    parts = _safe_member_parts(entry.name)
                    if entry.is_dir:
                        _ensure_directory(root_fd, parts)
                    else:
                        with archive.open(info, "r") as source:
                            digests.append(_write_regular(root_fd, parts, source, entry.size))
        else:
            with tarfile.open(path, "r:*") as archive:
                members = archive.getmembers()
                for entry, member in zip(entries, members, strict=True):
                    parts = _safe_member_parts(entry.name)
                    if entry.is_dir:
                        _ensure_directory(root_fd, parts)
                    else:
                        source = archive.extractfile(member)
                        if source is None:
                            raise ArchivePolicyError("archive member could not be opened")
                        with source:
                            digests.append(_write_regular(root_fd, parts, source, entry.size))
    finally:
        os.close(root_fd)
    os.chmod(root, 0o700)
    return root, digests


def archive_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="swir-archive-selftest-") as temp_text:
        temp = pathlib.Path(temp_text)
        safe_zip = temp / "safe.zip"
        with zipfile.ZipFile(safe_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("docs/readme.txt", b"SWIR archive manager\n")
            archive.writestr("empty/", b"")
        entries = _scan_archive(_validated_archive(safe_zip))
        assert len(entries) == 2 and entries[0].name == "docs/readme.txt"
        output, digests = _extract_archive(safe_zip, temp)
        payload = output / "docs" / "readme.txt"
        assert payload.read_bytes() == b"SWIR archive manager\n"
        assert stat.S_IMODE(payload.stat().st_mode) == 0o600
        assert len(digests) == 1

        evil_zip = temp / "evil.zip"
        with zipfile.ZipFile(evil_zip, "w") as archive:
            archive.writestr("../escape.txt", b"no")
        try:
            _scan_archive(_validated_archive(evil_zip))
        except ArchivePolicyError:
            pass
        else:
            raise AssertionError("path traversal archive was accepted")

        link_tar = temp / "links.tar"
        with tarfile.open(link_tar, "w") as archive:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        try:
            _scan_archive(_validated_archive(link_tar))
        except ArchivePolicyError:
            pass
        else:
            raise AssertionError("symlink archive member was accepted")
    print("SWIR Archive Manager self-test: OK")
    return 0


class SwirFiles(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.listbox: Gtk.ListBox | None = None
        self.path_label: Gtk.Label | None = None
        self.status: Gtk.Label | None = None
        self.include_hidden = False
        self.history: list[pathlib.Path] = []
        self.current = resolve_directory(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None)
        self.row_paths: dict[Gtk.ListBoxRow, pathlib.Path] = {}
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Files requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Files")
        window.set_default_size(980, 680)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Files")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        for label, callback in (("Back", self._go_back), ("Up", self._go_up), ("Home", self._go_home), ("Refresh", self._refresh_clicked)):
            button = Gtk.Button(label=label)
            button.add_css_class("swir-button")
            button.connect("clicked", callback)
            header.append(button)
        archive_button = Gtk.Button(label="Archive Manager")
        archive_button.add_css_class("swir-button")
        archive_button.connect("clicked", self._open_archive_manager)
        header.append(archive_button)
        hidden = Gtk.CheckButton(label="Hidden")
        hidden.connect("toggled", self._toggle_hidden)
        header.append(hidden)
        root.append(header)

        self.path_label = Gtk.Label()
        self.path_label.add_css_class("swir-path")
        self.path_label.set_xalign(0)
        self.path_label.set_selectable(True)
        root.append(self.path_label)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._activate_row)
        scroller.set_child(self.listbox)
        root.append(scroller)

        self.status = Gtk.Label()
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        root.append(self.status)

        self._render_directory()
        window.connect("map", self._on_mapped)
        window.present()

    def _clear_rows(self) -> None:
        assert self.listbox is not None
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child
        self.row_paths.clear()

    def _make_row(self, entry: DirectoryEntry) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("swir-file-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon = {"directory": "▣", "file": "◇", "symlink": "↗", "unavailable": "!"}.get(entry.kind, "·")
        glyph = Gtk.Label(label=icon)
        glyph.add_css_class("swir-brand" if entry.kind == "directory" else "swir-muted")
        box.append(glyph)
        name = Gtk.Label(label=entry.name)
        name.set_xalign(0)
        name.set_hexpand(True)
        box.append(name)
        kind = Gtk.Label(label=entry.kind)
        kind.add_css_class("swir-muted")
        kind.set_width_chars(12)
        box.append(kind)
        size = Gtk.Label(label=human_size(entry.size))
        size.add_css_class("swir-muted")
        size.set_width_chars(12)
        size.set_xalign(1)
        box.append(size)
        row.set_child(box)
        self.row_paths[row] = self.current / entry.name
        return row

    def _render_directory(self) -> None:
        assert self.listbox is not None and self.path_label is not None and self.status is not None
        self._clear_rows()
        try:
            entries = list_directory(self.current, include_hidden=self.include_hidden)
        except (OSError, ValueError) as exc:
            self.status.set_text(f"Could not read folder: {exc}")
            return
        self.path_label.set_text(str(self.current))
        for entry in entries:
            self.listbox.append(self._make_row(entry))
        self.status.set_text(f"{len(entries)} items • read-only browsing foundation")

    def _navigate(self, target: pathlib.Path, *, record: bool = True) -> None:
        try:
            destination = resolve_directory(target)
        except (OSError, ValueError) as exc:
            if self.status is not None:
                self.status.set_text(f"Cannot open folder: {exc}")
            return
        if record and destination != self.current:
            self.history.append(self.current)
        self.current = destination
        self._render_directory()

    def _activate_row(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        target = self.row_paths.get(row)
        if target is None:
            return
        try:
            if target.is_dir():
                self._navigate(target)
            elif _archive_suffix(target):
                self._launch_archive_mode(target)
            elif self.status is not None:
                self.status.set_text("File opening is intentionally limited until broader Default Apps integration is native.")
        except OSError as exc:
            if self.status is not None:
                self.status.set_text(f"Cannot inspect item: {exc}")

    def _launch_archive_mode(self, archive: pathlib.Path | None = None) -> None:
        argv = [sys.executable, str(pathlib.Path(__file__).resolve()), "--archive-manager"]
        if archive is not None:
            argv.extend(("--archive-open", str(archive)))
        try:
            import subprocess
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            if self.status is not None:
                self.status.set_text("Opened Archive Manager")
        except OSError as exc:
            if self.status is not None:
                self.status.set_text(f"Could not open Archive Manager: {exc}")

    def _open_archive_manager(self, _button: Gtk.Button) -> None:
        self._launch_archive_mode()

    def _go_back(self, _button: Gtk.Button) -> None:
        if self.history:
            self._navigate(self.history.pop(), record=False)

    def _go_up(self, _button: Gtk.Button) -> None:
        if self.current.parent != self.current:
            self._navigate(self.current.parent)

    def _go_home(self, _button: Gtk.Button) -> None:
        self._navigate(pathlib.Path.home())

    def _refresh_clicked(self, _button: Gtk.Button) -> None:
        self._render_directory()

    def _toggle_hidden(self, button: Gtk.CheckButton) -> None:
        self.include_hidden = button.get_active()
        self._render_directory()

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Files evidence path outside XDG_RUNTIME_DIR")
        rows = list_directory(self.current, include_hidden=False)
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "currentDirectoryReadable": True,
            "visibleEntryCount": len(rows),
            "fileOpenDelegationEnabled": False,
            "archiveManagerAvailable": True,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


class SwirArchiveManager(Gtk.Application):
    """Separate GTK4 application mode shipped inside the trusted swir-files executable."""

    def __init__(self, initial_archive: str | None = None) -> None:
        super().__init__(application_id=ARCHIVE_APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.list_box: Gtk.ListBox | None = None
        self.status: Gtk.Label | None = None
        self.archive_path: pathlib.Path | None = None
        self.entries: list[ArchiveEntry] = []
        self.initial_archive = initial_archive
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.e2e_archive = os.environ.get("SWIR_ARCHIVE_E2E_INPUT", "")
        self.e2e_destination = os.environ.get("SWIR_ARCHIVE_E2E_DESTINATION", "")
        self.evidence_written = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Archive Manager requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Archive Manager")
        window.set_default_size(980, 700)
        window.add_css_class("swir-app")
        self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Archive Manager")
        brand.add_css_class("swir-brand")
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        open_button = Gtk.Button(label="Open archive")
        open_button.add_css_class("swir-button")
        open_button.connect("clicked", self._choose_open)
        header.append(open_button)
        extract_button = Gtk.Button(label="Extract safely")
        extract_button.add_css_class("swir-primary")
        extract_button.connect("clicked", self._choose_destination)
        header.append(extract_button)
        root.append(header)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("swir-panel")
        panel.set_hexpand(True)
        panel.set_vexpand(True)
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self.list_box)
        panel.append(scroller)
        root.append(panel)

        self.status = Gtk.Label(label="Open a local ZIP or TAR archive. Links and traversal entries fail closed.")
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        root.append(self.status)
        window.connect("map", self._on_mapped)
        window.present()
        if self.initial_archive:
            try:
                self._open_path(_validated_archive(self.initial_archive))
            except ArchivePolicyError as exc:
                self._set_status(str(exc))

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _clear_rows(self) -> None:
        if self.list_box is None:
            return
        child = self.list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child

    def _open_path(self, path: pathlib.Path) -> None:
        entries = _scan_archive(path)
        self.archive_path = path
        self.entries = entries
        self._clear_rows()
        if self.list_box is not None:
            for entry in entries:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                name = Gtk.Label(label=("DIR  " if entry.is_dir else "FILE  ") + entry.name)
                name.set_xalign(0)
                name.set_hexpand(True)
                row.append(name)
                size = Gtk.Label(label="" if entry.is_dir else human_size(entry.size))
                size.add_css_class("swir-muted")
                row.append(size)
                self.list_box.append(row)
        total = sum(entry.size for entry in entries)
        self._set_status(f"{path.name} • {len(entries)} entries • {human_size(total)} expanded data • validated before extraction")

    def _choose_open(self, *_args) -> None:
        if self.window is None:
            return
        chooser = Gtk.FileChooserNative.new("Open archive", self.window, Gtk.FileChooserAction.OPEN, "Open", "Cancel")
        chooser.connect("response", self._open_response)
        chooser.show()

    def _open_response(self, chooser: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = chooser.get_file()
            path = file.get_path() if file else None
            if path:
                try:
                    self._open_path(_validated_archive(path))
                except ArchivePolicyError as exc:
                    self._set_status(str(exc))
        chooser.destroy()

    def _choose_destination(self, *_args) -> None:
        if self.window is None or self.archive_path is None:
            self._set_status("Open and validate an archive first.")
            return
        chooser = Gtk.FileChooserNative.new("Choose extraction parent", self.window, Gtk.FileChooserAction.SELECT_FOLDER, "Extract here", "Cancel")
        chooser.connect("response", self._destination_response)
        chooser.show()

    def _destination_response(self, chooser: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT and self.archive_path is not None:
            file = chooser.get_file()
            path = file.get_path() if file else None
            if path:
                try:
                    output, _ = _extract_archive(self.archive_path, pathlib.Path(path))
                    self._set_status(f"Extracted safely to {output}")
                except (ArchivePolicyError, OSError) as exc:
                    self._set_status(f"Extraction refused: {exc}")
        chooser.destroy()

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if self.evidence_written or not self.e2e or not self.evidence_path:
            return
        evidence_path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or evidence_path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing Archive Manager evidence path outside XDG_RUNTIME_DIR")
        if not self.e2e_archive or not self.e2e_destination:
            raise RuntimeError("missing Archive Manager E2E input/destination")
        archive = _validated_archive(self.e2e_archive)
        self._open_path(archive)
        output, digests = _extract_archive(archive, _validated_destination_parent(self.e2e_destination))
        payload = {
            "schema": ARCHIVE_EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": ARCHIVE_APP_ID,
            "nativeToolkit": "gtk4-python-stdlib-archive",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "archiveName": archive.name,
            "entryCount": len(self.entries),
            "expandedBytes": sum(entry.size for entry in self.entries),
            "extractionRoot": str(output),
            "regularFileDigests": digests,
            "pathTraversalAccepted": False,
            "symlinkMembersAccepted": False,
            "specialMembersAccepted": False,
            "exclusiveNoFollowWrites": True,
            "privilegedOperations": False,
            "selfUpdater": False,
        }
        evidence_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        evidence_path.chmod(0o600)
        self.evidence_written = True
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


def _archive_arg(argv: list[str]) -> str | None:
    try:
        index = argv.index("--archive-open")
    except ValueError:
        return None
    return argv[index + 1] if index + 1 < len(argv) else None


if __name__ == "__main__":
    if "--archive-self-test" in sys.argv:
        raise SystemExit(archive_self_test())
    if "--archive-manager" in sys.argv:
        raise SystemExit(SwirArchiveManager(_archive_arg(sys.argv)).run([sys.argv[0]]))
    raise SystemExit(SwirFiles().run(sys.argv))
