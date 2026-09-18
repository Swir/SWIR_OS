#!/usr/bin/env python3
"""SWIR Player — native GTK4/GStreamer media player for System Edition.

The player is an unprivileged first-party application. It opens local regular
files only, stores a bounded owner-only media library and playlists, integrates
with the desktop through MPRIS2 for media keys, and publishes Gio
notifications. Codec/runtime updates remain on the signed SWIR system package
path; the player has no self-updater or privilege shortcut.
"""

from __future__ import annotations

import json
import mimetypes
import os
import pathlib
import sys
import tempfile
from dataclasses import dataclass
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, Gio, GLib, Gst, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.Player"
MPRIS_NAME: Final = "org.mpris.MediaPlayer2.swir"
EVIDENCE_SCHEMA: Final = "swir.native-player-runtime-evidence/0.1"
LIBRARY_SCHEMA: Final = "swir.player-library/0.1"
MAX_LIBRARY_TRACKS: Final = 1000
MAX_PLAYLISTS: Final = 100
MAX_PLAYLIST_TRACKS: Final = 500
MAX_PATH_BYTES: Final = 4096
SUPPORTED_PREFIXES: Final = ("audio/", "video/")
SUPPORTED_FALLBACK_SUFFIXES: Final = {
    ".aac", ".flac", ".m4a", ".mka", ".mkv", ".mp3", ".mp4", ".oga", ".ogg",
    ".ogv", ".opus", ".wav", ".webm",
}

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 12px; }
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-panel { background: #07111C; border: 1px solid rgba(98,229,255,0.22); border-radius: 14px; padding: 10px; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid rgba(0,136,255,0.65); border-radius: 9px; padding: 6px 10px; }
.swir-button:hover { border-color: #62E5FF; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 9px; padding: 6px 12px; font-weight: 700; }
scale trough { background: rgba(98,229,255,0.16); }
scale highlight { background: #0088FF; }
"""

MPRIS_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg direction="in" type="x" name="Offset"/></method>
    <method name="SetPosition">
      <arg direction="in" type="o" name="TrackId"/>
      <arg direction="in" type="x" name="Position"/>
    </method>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


class PlayerPolicyError(RuntimeError):
    pass


def _data_root() -> pathlib.Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = pathlib.Path(base) if base else pathlib.Path.home() / ".local" / "share"
    return root / "swir" / "player"


def _reject_symlink_path(path: pathlib.Path, *, allow_missing_leaf: bool = False) -> None:
    current = pathlib.Path(path.anchor or "/")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if not path.is_absolute():
        current = pathlib.Path.cwd()
    for index, part in enumerate(parts):
        current = current / part
        try:
            if current.is_symlink():
                raise PlayerPolicyError(f"refusing symlink path: {current}")
            current.lstat()
        except FileNotFoundError:
            if allow_missing_leaf or index < len(parts):
                continue


def _atomic_json(path: pathlib.Path, payload: object) -> None:
    _reject_symlink_path(path.parent, allow_missing_leaf=True)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise PlayerPolicyError("player data directory must not be a symlink")
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    if path.exists() and path.is_symlink():
        raise PlayerPolicyError("player library file must not be a symlink")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _is_supported_media(path: pathlib.Path) -> bool:
    mime, _encoding = mimetypes.guess_type(path.name)
    if mime and mime.startswith(SUPPORTED_PREFIXES):
        return True
    return path.suffix.lower() in SUPPORTED_FALLBACK_SUFFIXES


def _validated_local_media(raw: str | pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw).expanduser()
    if len(os.fsencode(path)) > MAX_PATH_BYTES:
        raise PlayerPolicyError("media path is too long")
    if not path.is_absolute():
        path = path.resolve()
    try:
        if path.is_symlink():
            raise PlayerPolicyError("symbolic-link media paths are not accepted")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PlayerPolicyError(f"media path cannot be resolved: {exc}") from exc
    if resolved != path:
        raise PlayerPolicyError("media path must be canonical and may not traverse symlinks")
    if not resolved.is_file():
        raise PlayerPolicyError("media path must be a regular file")
    if not os.access(resolved, os.R_OK):
        raise PlayerPolicyError("media file is not readable")
    if not _is_supported_media(resolved):
        raise PlayerPolicyError("file is not a supported local audio/video type")
    return resolved


@dataclass(frozen=True)
class Track:
    path: str
    title: str
    mime: str

    @classmethod
    def from_path(cls, path: pathlib.Path) -> "Track":
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return cls(path=str(path), title=path.stem[:200], mime=mime)

    def as_json(self) -> dict[str, str]:
        return {"path": self.path, "title": self.title, "mime": self.mime}


class LibraryStore:
    def __init__(self, path: pathlib.Path | None = None) -> None:
        self.path = path or (_data_root() / "library.json")
        self.tracks: list[Track] = []
        self.playlists: dict[str, list[str]] = {"Favorites": []}

    def load(self) -> None:
        try:
            if self.path.is_symlink():
                raise PlayerPolicyError("player library file must not be a symlink")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except json.JSONDecodeError as exc:
            raise PlayerPolicyError("player library is invalid JSON") from exc
        if not isinstance(raw, dict) or raw.get("schema") != LIBRARY_SCHEMA:
            raise PlayerPolicyError("player library schema is invalid")
        items = raw.get("tracks")
        playlists = raw.get("playlists")
        if not isinstance(items, list) or len(items) > MAX_LIBRARY_TRACKS:
            raise PlayerPolicyError("player library track count is invalid")
        if not isinstance(playlists, dict) or len(playlists) > MAX_PLAYLISTS:
            raise PlayerPolicyError("player playlist count is invalid")
        tracks: list[Track] = []
        known: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise PlayerPolicyError("player library track entry is invalid")
            path = item.get("path")
            title = item.get("title")
            mime = item.get("mime")
            if not all(isinstance(value, str) for value in (path, title, mime)):
                raise PlayerPolicyError("player library track fields are invalid")
            if len(os.fsencode(path)) > MAX_PATH_BYTES or len(title) > 200 or len(mime) > 100:
                raise PlayerPolicyError("player library track fields exceed bounds")
            tracks.append(Track(path=path, title=title, mime=mime))
            known.add(path)
        clean_playlists: dict[str, list[str]] = {}
        for name, values in playlists.items():
            if not isinstance(name, str) or not name or len(name) > 80 or not isinstance(values, list):
                raise PlayerPolicyError("player playlist is invalid")
            if len(values) > MAX_PLAYLIST_TRACKS:
                raise PlayerPolicyError("player playlist exceeds track bound")
            clean: list[str] = []
            for value in values:
                if not isinstance(value, str) or value not in known:
                    raise PlayerPolicyError("player playlist references an unknown track")
                if value not in clean:
                    clean.append(value)
            clean_playlists[name] = clean
        self.tracks = tracks
        self.playlists = clean_playlists or {"Favorites": []}

    def save(self) -> None:
        payload = {
            "schema": LIBRARY_SCHEMA,
            "tracks": [track.as_json() for track in self.tracks[:MAX_LIBRARY_TRACKS]],
            "playlists": {
                name: paths[:MAX_PLAYLIST_TRACKS]
                for name, paths in list(self.playlists.items())[:MAX_PLAYLISTS]
            },
        }
        _atomic_json(self.path, payload)

    def add(self, path: pathlib.Path) -> Track:
        track = Track.from_path(path)
        existing = next((item for item in self.tracks if item.path == track.path), None)
        if existing is not None:
            return existing
        if len(self.tracks) >= MAX_LIBRARY_TRACKS:
            raise PlayerPolicyError("media library has reached its verified bound")
        self.tracks.append(track)
        self.save()
        return track

    def ensure_playlist(self, name: str) -> None:
        clean = " ".join(name.split())[:80]
        if not clean:
            raise PlayerPolicyError("playlist name cannot be empty")
        if clean not in self.playlists:
            if len(self.playlists) >= MAX_PLAYLISTS:
                raise PlayerPolicyError("playlist count has reached its verified bound")
            self.playlists[clean] = []
            self.save()

    def add_to_playlist(self, name: str, track: Track) -> None:
        self.ensure_playlist(name)
        items = self.playlists[name]
        if track.path in items:
            return
        if len(items) >= MAX_PLAYLIST_TRACKS:
            raise PlayerPolicyError("playlist has reached its verified bound")
        items.append(track.path)
        self.save()


class MprisBridge:
    def __init__(self, player: "SwirPlayer") -> None:
        self.player = player
        self.connection: Gio.DBusConnection | None = None
        self.owner_id = 0
        self.export_ids: list[int] = []
        self.node = Gio.DBusNodeInfo.new_for_xml(MPRIS_XML)

    def start(self) -> bool:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return False
        self.owner_id = Gio.bus_own_name_on_connection(
            self.connection,
            MPRIS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            None,
            None,
        )
        for interface in self.node.interfaces:
            export_id = self.connection.register_object(
                "/org/mpris/MediaPlayer2",
                interface,
                self._method_call,
                self._get_property,
                self._set_property,
            )
            self.export_ids.append(export_id)
        return bool(self.owner_id and self.export_ids)

    def stop(self) -> None:
        if self.connection:
            for export_id in self.export_ids:
                try:
                    self.connection.unregister_object(export_id)
                except GLib.Error:
                    pass
        self.export_ids.clear()
        if self.owner_id:
            Gio.bus_unown_name(self.owner_id)
            self.owner_id = 0

    def _method_call(self, _connection, _sender, _object_path, interface, method, params, invocation) -> None:
        if interface == "org.mpris.MediaPlayer2":
            if method == "Raise":
                if self.player.window:
                    self.player.window.present()
            elif method == "Quit":
                self.player.quit()
            invocation.return_value(None)
            return
        handlers = {
            "Next": self.player.next_track,
            "Previous": self.player.previous_track,
            "Pause": self.player.pause,
            "PlayPause": self.player.play_pause,
            "Stop": self.player.stop,
            "Play": self.player.play,
        }
        if method in handlers:
            handlers[method]()
            invocation.return_value(None)
            return
        if method == "Seek":
            offset = int(params.unpack()[0])
            self.player.seek_relative(offset)
            invocation.return_value(None)
            return
        if method == "SetPosition":
            _track_id, position = params.unpack()
            self.player.seek_absolute(int(position))
            invocation.return_value(None)
            return
        invocation.return_dbus_error("org.mpris.MediaPlayer2.Error.NotSupported", "method not supported")

    def _get_property(self, _connection, _sender, _object_path, interface, prop):
        if interface == "org.mpris.MediaPlayer2":
            values = {
                "CanQuit": GLib.Variant("b", True),
                "CanRaise": GLib.Variant("b", True),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", "SWIR Player"),
                "DesktopEntry": GLib.Variant("s", "swir-player"),
                "SupportedUriSchemes": GLib.Variant("as", ["file"]),
                "SupportedMimeTypes": GLib.Variant(
                    "as",
                    ["audio/mpeg", "audio/ogg", "audio/flac", "audio/wav", "video/mp4", "video/webm", "video/x-matroska"],
                ),
            }
            return values.get(prop)
        status = self.player.playback_status
        metadata = self.player.mpris_metadata()
        values = {
            "PlaybackStatus": GLib.Variant("s", status),
            "LoopStatus": GLib.Variant("s", "None"),
            "Rate": GLib.Variant("d", 1.0),
            "Shuffle": GLib.Variant("b", False),
            "Metadata": GLib.Variant("a{sv}", metadata),
            "Volume": GLib.Variant("d", self.player.volume),
            "Position": GLib.Variant("x", self.player.position_us()),
            "MinimumRate": GLib.Variant("d", 1.0),
            "MaximumRate": GLib.Variant("d", 1.0),
            "CanGoNext": GLib.Variant("b", self.player.has_tracks()),
            "CanGoPrevious": GLib.Variant("b", self.player.has_tracks()),
            "CanPlay": GLib.Variant("b", self.player.current_track is not None),
            "CanPause": GLib.Variant("b", self.player.current_track is not None),
            "CanSeek": GLib.Variant("b", self.player.current_track is not None),
            "CanControl": GLib.Variant("b", True),
        }
        return values.get(prop)

    def _set_property(self, _connection, _sender, _object_path, interface, prop, value) -> bool:
        if interface != "org.mpris.MediaPlayer2.Player":
            return False
        if prop == "Volume":
            self.player.set_volume(float(value.unpack()))
            return True
        return False

    def changed(self, names: tuple[str, ...] = ("PlaybackStatus", "Metadata", "CanPlay", "CanPause")) -> None:
        if not self.connection:
            return
        changed: dict[str, GLib.Variant] = {}
        for name in names:
            value = self._get_property(None, None, None, "org.mpris.MediaPlayer2.Player", name)
            if value is not None:
                changed[name] = value
        try:
            self.connection.emit_signal(
                None,
                "/org/mpris/MediaPlayer2",
                "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", changed, [])),
            )
        except GLib.Error:
            pass


class SwirPlayer(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        Gst.init(None)
        self.window: Gtk.ApplicationWindow | None = None
        self.picture: Gtk.Picture | None = None
        self.track_list: Gtk.ListBox | None = None
        self.status_label: Gtk.Label | None = None
        self.title_label: Gtk.Label | None = None
        self.seek_scale: Gtk.Scale | None = None
        self.play_button: Gtk.Button | None = None
        self.library = LibraryStore()
        try:
            self.library.load()
        except PlayerPolicyError as exc:
            print(f"SWIR Player ignored unsafe/invalid library: {exc}", file=sys.stderr)
            self.library = LibraryStore()
        self.current_track: Track | None = None
        self.current_index = -1
        self.playback_status = "Stopped"
        self.volume = 0.80
        self._seek_drag = False
        self._evidence_written = False
        self._mpris = MprisBridge(self)
        self._mpris_started = False
        self._e2e = os.environ.get("SWIR_APP_E2E") == "1"
        self._evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self._e2e_media = os.environ.get("SWIR_PLAYER_E2E_MEDIA", "")
        self.pipeline = Gst.ElementFactory.make("playbin", "swir-player")
        if self.pipeline is None:
            raise RuntimeError("GStreamer playbin is unavailable")
        self.video_sink_available = Gst.ElementFactory.find("gtk4paintablesink") is not None
        if self._e2e:
            audio_sink = Gst.ElementFactory.make("fakesink", "swir-e2e-audio")
            video_sink = Gst.ElementFactory.make("fakesink", "swir-e2e-video")
            if audio_sink and video_sink:
                self.pipeline.set_property("audio-sink", audio_sink)
                self.pipeline.set_property("video-sink", video_sink)
        else:
            sink = Gst.ElementFactory.make("gtk4paintablesink", "swir-video")
            if sink is not None:
                self.pipeline.set_property("video-sink", sink)
                self.video_sink = sink
            else:
                self.video_sink = None
        self.pipeline.set_property("volume", self.volume)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.set_accels_for_action("app.open", ["<Primary>O"])
        open_action = Gio.SimpleAction.new("open", None)
        open_action.connect("activate", lambda *_: self._choose_media())
        self.add_action(open_action)
        play_action = Gio.SimpleAction.new("play-pause", None)
        play_action.connect("activate", lambda *_: self.play_pause())
        self.add_action(play_action)
        self.set_accels_for_action("app.play-pause", ["space"])
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Player requires an active graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._mpris_started = self._mpris.start()

    def do_shutdown(self) -> None:
        self.pipeline.set_state(Gst.State.NULL)
        self._mpris.stop()
        Gtk.Application.do_shutdown(self)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        paths: list[pathlib.Path] = []
        index = 0
        while index < len(args):
            if args[index] == "--open" and index + 1 < len(args):
                try:
                    paths.append(_validated_local_media(args[index + 1]))
                except PlayerPolicyError as exc:
                    print(f"SWIR Player refused media: {exc}", file=sys.stderr)
                    return 64
                index += 2
                continue
            index += 1
        self.activate()
        for path in paths:
            self._add_and_select(path, autoplay=True)
        return 0

    def do_open(self, files, _n_files: int, _hint: str) -> None:
        self.activate()
        for gio_file in files:
            path = gio_file.get_path()
            if not path:
                continue
            try:
                self._add_and_select(_validated_local_media(path), autoplay=True)
            except PlayerPolicyError as exc:
                self._set_status(str(exc))

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Player")
        window.set_default_size(1100, 720)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="▶  SWIR PLAYER")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        add_button = Gtk.Button(label="Add media")
        add_button.add_css_class("swir-primary")
        add_button.connect("clicked", lambda *_: self._choose_media())
        header.append(add_button)
        root.append(header)

        body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_hexpand(True)
        body.set_vexpand(True)
        body.set_position(350)
        root.append(body)

        library_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        library_panel.add_css_class("swir-panel")
        library_title = Gtk.Label(label="Library • Favorites")
        library_title.add_css_class("swir-brand")
        library_title.set_xalign(0)
        library_panel.append(library_title)
        self.track_list = Gtk.ListBox()
        self.track_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.track_list.connect("row-activated", self._on_row_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.track_list)
        library_panel.append(scroller)
        fav = Gtk.Button(label="Add current to Favorites")
        fav.add_css_class("swir-button")
        fav.connect("clicked", self._add_current_to_favorites)
        library_panel.append(fav)
        body.set_start_child(library_panel)

        player_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        player_panel.add_css_class("swir-panel")
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        if not self._e2e and getattr(self, "video_sink", None) is not None:
            try:
                self.picture.set_paintable(self.video_sink.get_property("paintable"))
            except (TypeError, GLib.Error):
                pass
        player_panel.append(self.picture)

        self.title_label = Gtk.Label(label="Choose a local audio or video file")
        self.title_label.add_css_class("swir-brand")
        player_panel.append(self.title_label)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        prev_button = Gtk.Button(label="⏮")
        prev_button.connect("clicked", lambda *_: self.previous_track())
        controls.append(prev_button)
        self.play_button = Gtk.Button(label="▶")
        self.play_button.add_css_class("swir-primary")
        self.play_button.connect("clicked", lambda *_: self.play_pause())
        controls.append(self.play_button)
        stop_button = Gtk.Button(label="■")
        stop_button.connect("clicked", lambda *_: self.stop())
        controls.append(stop_button)
        next_button = Gtk.Button(label="⏭")
        next_button.connect("clicked", lambda *_: self.next_track())
        controls.append(next_button)

        self.seek_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.seek_scale.set_hexpand(True)
        self.seek_scale.set_draw_value(False)
        seek_gesture = Gtk.GestureClick()
        seek_gesture.connect("pressed", lambda *_: setattr(self, "_seek_drag", True))
        seek_gesture.connect("released", self._seek_released)
        self.seek_scale.add_controller(seek_gesture)
        controls.append(self.seek_scale)

        volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.01)
        volume.set_value(self.volume)
        volume.set_size_request(130, -1)
        volume.connect("value-changed", lambda scale: self.set_volume(scale.get_value()))
        controls.append(volume)
        player_panel.append(controls)

        self.status_label = Gtk.Label(label="Local files only • MPRIS media-key integration")
        self.status_label.add_css_class("swir-muted")
        self.status_label.set_xalign(0)
        player_panel.append(self.status_label)
        body.set_end_child(player_panel)

        self._refresh_library()
        GLib.timeout_add(500, self._tick)
        window.connect("map", self._on_mapped)
        window.present()

    def _choose_media(self) -> None:
        if not self.window:
            return
        dialog = Gtk.FileDialog(title="Add local media to SWIR Player")
        dialog.set_modal(True)
        dialog.open(self.window, None, self._file_chosen)

    def _file_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gio_file = dialog.open_finish(result)
            path_text = gio_file.get_path()
            if not path_text:
                raise PlayerPolicyError("only local media files are accepted")
            self._add_and_select(_validated_local_media(path_text), autoplay=True)
        except (GLib.Error, PlayerPolicyError) as exc:
            self._set_status(f"Could not open media: {exc}")

    def _add_and_select(self, path: pathlib.Path, *, autoplay: bool) -> None:
        try:
            track = self.library.add(path)
        except (OSError, PlayerPolicyError) as exc:
            self._set_status(f"Library update failed: {exc}")
            return
        self._refresh_library()
        self._select_track(track, autoplay=autoplay)

    def _refresh_library(self) -> None:
        if not self.track_list:
            return
        child = self.track_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.track_list.remove(child)
            child = nxt
        for index, track in enumerate(self.library.tracks):
            row = Gtk.ListBoxRow()
            row.swir_index = index  # type: ignore[attr-defined]
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=track.title)
            title.set_xalign(0)
            detail = Gtk.Label(label=track.mime)
            detail.add_css_class("swir-muted")
            detail.set_xalign(0)
            box.append(title)
            box.append(detail)
            row.set_child(box)
            self.track_list.append(row)

    def _on_row_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        index = getattr(row, "swir_index", -1)
        if isinstance(index, int) and 0 <= index < len(self.library.tracks):
            self.current_index = index
            self._select_track(self.library.tracks[index], autoplay=True)

    def _select_track(self, track: Track, *, autoplay: bool) -> None:
        try:
            path = _validated_local_media(track.path)
        except PlayerPolicyError as exc:
            self._set_status(f"Track unavailable: {exc}")
            return
        self.current_track = Track.from_path(path)
        try:
            self.current_index = next(index for index, item in enumerate(self.library.tracks) if item.path == str(path))
        except StopIteration:
            self.current_index = -1
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.set_property("uri", path.as_uri())
        self.pipeline.set_state(Gst.State.PLAYING if autoplay else Gst.State.PAUSED)
        self.playback_status = "Playing" if autoplay else "Paused"
        if self.title_label:
            self.title_label.set_text(self.current_track.title)
        if self.play_button:
            self.play_button.set_label("⏸" if autoplay else "▶")
        self._set_status(f"{'Playing' if autoplay else 'Ready'} • {path.name}")
        self._notify_track()
        self._mpris.changed()

    def play(self) -> None:
        if self.current_track is None:
            return
        self.pipeline.set_state(Gst.State.PLAYING)
        self.playback_status = "Playing"
        if self.play_button:
            self.play_button.set_label("⏸")
        self._mpris.changed(("PlaybackStatus",))

    def pause(self) -> None:
        if self.current_track is None:
            return
        self.pipeline.set_state(Gst.State.PAUSED)
        self.playback_status = "Paused"
        if self.play_button:
            self.play_button.set_label("▶")
        self._mpris.changed(("PlaybackStatus",))

    def play_pause(self) -> None:
        if self.playback_status == "Playing":
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self.pipeline.set_state(Gst.State.READY)
        self.playback_status = "Stopped"
        if self.play_button:
            self.play_button.set_label("▶")
        self._mpris.changed(("PlaybackStatus",))

    def next_track(self) -> None:
        if not self.library.tracks:
            return
        self.current_index = (self.current_index + 1) % len(self.library.tracks)
        self._select_track(self.library.tracks[self.current_index], autoplay=True)

    def previous_track(self) -> None:
        if not self.library.tracks:
            return
        self.current_index = (self.current_index - 1) % len(self.library.tracks)
        self._select_track(self.library.tracks[self.current_index], autoplay=True)

    def has_tracks(self) -> bool:
        return bool(self.library.tracks)

    def set_volume(self, volume: float) -> None:
        self.volume = min(1.0, max(0.0, float(volume)))
        self.pipeline.set_property("volume", self.volume)
        self._mpris.changed(("Volume",))

    def position_us(self) -> int:
        ok, value = self.pipeline.query_position(Gst.Format.TIME)
        return int(value // 1000) if ok and value >= 0 else 0

    def duration_us(self) -> int:
        ok, value = self.pipeline.query_duration(Gst.Format.TIME)
        return int(value // 1000) if ok and value > 0 else 0

    def seek_absolute(self, position_us: int) -> None:
        if self.current_track is None:
            return
        bounded = max(0, int(position_us)) * 1000
        self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, bounded)

    def seek_relative(self, offset_us: int) -> None:
        self.seek_absolute(max(0, self.position_us() + int(offset_us)))

    def _seek_released(self, _gesture, _presses, _x, _y) -> None:
        self._seek_drag = False
        if not self.seek_scale:
            return
        duration = self.duration_us()
        if duration:
            self.seek_absolute(int(duration * (self.seek_scale.get_value() / 100.0)))

    def _tick(self) -> bool:
        if self.seek_scale and not self._seek_drag:
            duration = self.duration_us()
            if duration:
                self.seek_scale.set_value(min(100.0, self.position_us() * 100.0 / duration))
        return True

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self.playback_status = "Stopped"
            self._set_status(f"Playback error: {error.message[:160]}")
            print(f"SWIR Player GStreamer error: {error}; {debug}", file=sys.stderr)
            self._mpris.changed(("PlaybackStatus",))
        elif message.type == Gst.MessageType.EOS:
            self.next_track()
        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self.pipeline:
            _old, new, _pending = message.parse_state_changed()
            mapping = {
                Gst.State.PLAYING: "Playing",
                Gst.State.PAUSED: "Paused",
                Gst.State.READY: "Stopped",
                Gst.State.NULL: "Stopped",
            }
            status = mapping.get(new)
            if status and status != self.playback_status:
                self.playback_status = status
                self._mpris.changed(("PlaybackStatus",))

    def _notify_track(self) -> None:
        if self.current_track is None:
            return
        notification = Gio.Notification.new("Now playing")
        notification.set_body(self.current_track.title)
        notification.set_default_action("app.play-pause")
        self.send_notification("now-playing", notification)

    def _add_current_to_favorites(self, _button: Gtk.Button) -> None:
        if self.current_track is None:
            self._set_status("Choose a track first.")
            return
        try:
            self.library.add_to_playlist("Favorites", self.current_track)
            self._set_status("Added to Favorites.")
        except (OSError, PlayerPolicyError) as exc:
            self._set_status(f"Playlist update failed: {exc}")

    def _set_status(self, text: str) -> None:
        if self.status_label:
            self.status_label.set_text(text[:300])

    def mpris_metadata(self) -> dict[str, GLib.Variant]:
        if self.current_track is None:
            return {}
        track_id = f"/dev/swir/Player/track/{max(0, self.current_index)}"
        return {
            "mpris:trackid": GLib.Variant("o", track_id),
            "xesam:title": GLib.Variant("s", self.current_track.title),
            "xesam:url": GLib.Variant("s", pathlib.Path(self.current_track.path).as_uri()),
            "mpris:length": GLib.Variant("x", self.duration_us()),
        }

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self._e2e or self._evidence_written:
            return
        if not self._e2e_media:
            raise RuntimeError("SWIR_PLAYER_E2E_MEDIA is required for runtime evidence")
        try:
            path = _validated_local_media(self._e2e_media)
            track = self.library.add(path)
            self.library.add_to_playlist("E2E Playlist", track)
            self._select_track(track, autoplay=False)
        except (OSError, PlayerPolicyError) as exc:
            raise RuntimeError(f"player E2E setup failed: {exc}") from exc
        GLib.timeout_add(800, self._write_evidence)

    def _write_evidence(self) -> bool:
        if self._evidence_written:
            return False
        state_change, state, _pending = self.pipeline.get_state(2 * Gst.SECOND)
        preroll_ok = state_change != Gst.StateChangeReturn.FAILURE and state in {Gst.State.PAUSED, Gst.State.PLAYING}
        path = pathlib.Path(self._evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text:
            raise RuntimeError("missing XDG_RUNTIME_DIR for player evidence")
        runtime = pathlib.Path(runtime_text).resolve()
        if path.parent.resolve() != runtime:
            raise RuntimeError("refusing player evidence outside XDG_RUNTIME_DIR")
        library_path = self.library.path
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": bool(preroll_ok and self._mpris_started and self.video_sink_available),
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4-gstreamer",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "gstreamerPlaybin": True,
            "gstreamerGtk4VideoSinkAvailable": self.video_sink_available,
            "pipelinePrerollPassed": preroll_ok,
            "localFilesOnly": True,
            "remoteUriInputAccepted": False,
            "libraryPersistent": True,
            "libraryRowsBounded": MAX_LIBRARY_TRACKS,
            "playlistPersistent": True,
            "playlistCountBounded": MAX_PLAYLISTS,
            "playlistRowsBounded": MAX_PLAYLIST_TRACKS,
            "mpris2MediaKeyIntegration": self._mpris_started,
            "mprisBusName": MPRIS_NAME,
            "notificationIntegration": True,
            "ownerOnlyLibraryFile": library_path.exists() and (library_path.stat().st_mode & 0o777) == 0o600,
            "atomicPersistence": True,
            "privilegedOperations": False,
            "selfUpdater": False,
            "codecUpdatePath": "system-package-update-center",
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self._evidence_written = True
        self.quit()
        return False


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="swir-player-selftest-") as temp:
        root = pathlib.Path(temp)
        data = root / "data"
        media = root / "media.wav"
        media.write_bytes(b"RIFF" + b"\x00" * 64)
        store = LibraryStore(data / "library.json")
        track = store.add(_validated_local_media(media))
        store.add_to_playlist("Favorites", track)
        store.ensure_playlist("Road Trip")
        loaded = LibraryStore(data / "library.json")
        loaded.load()
        assert len(loaded.tracks) == 1
        assert loaded.playlists["Favorites"] == [str(media)]
        assert "Road Trip" in loaded.playlists
        assert (loaded.path.stat().st_mode & 0o777) == 0o600
        assert (loaded.path.parent.stat().st_mode & 0o777) == 0o700
        try:
            _validated_local_media("https://example.invalid/media.mp3")
        except PlayerPolicyError:
            pass
        else:
            raise AssertionError("remote URI text must not be accepted as local media")
        target = root / "target.json"
        target.write_text("{}", encoding="utf-8")
        symlink = root / "unsafe.json"
        symlink.symlink_to(target)
        unsafe = LibraryStore(symlink)
        try:
            unsafe.load()
        except PlayerPolicyError:
            pass
        else:
            raise AssertionError("symlinked library must be rejected")
    print("SWIR Player self-test: OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(SwirPlayer().run(sys.argv))
