#!/usr/bin/env python3
"""Safe SWIR Shell theme/skin package runtime for System Edition.

Theme packages are data-only JSON documents. They may select a bounded set of
visual tokens but cannot inject CSS, commands, paths, URLs, scripts, or code.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import re
import tempfile
from typing import Final

THEME_SCHEMA: Final = "swir.theme/1.0"
DEFAULT_THEME_ID: Final = "builtin.swir-dark"
MAX_THEME_BYTES: Final = 64 * 1024
MAX_THEME_NAME_CHARS: Final = 64
MAX_THEME_ID_CHARS: Final = 64

_THEME_ID_RE: Final = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_HEX_COLOR_RE: Final = re.compile(r"^#[0-9A-Fa-f]{6}$")
_COLOR_KEYS: Final = (
    "background",
    "surface",
    "primary",
    "accent",
    "text",
    "muted",
    "border",
)
_TOKEN_KEYS: Final = frozenset((*_COLOR_KEYS, "radius", "spacing", "fontScale"))
_TOP_LEVEL_KEYS: Final = frozenset({"schema", "id", "name", "tokens"})


class ThemePolicyError(ValueError):
    """Theme package violates the bounded data-only policy."""


DEFAULT_THEME: Final = {
    "schema": THEME_SCHEMA,
    "id": DEFAULT_THEME_ID,
    "name": "SWIR Dark",
    "tokens": {
        "background": "#02050A",
        "surface": "#07111C",
        "primary": "#0088FF",
        "accent": "#62E5FF",
        "text": "#F4FAFF",
        "muted": "#8FAFC2",
        "border": "#2E7899",
        "radius": 14,
        "spacing": 12,
        "fontScale": 1.0,
    },
}


def _relative_luminance(color: str) -> float:
    values = [int(color[index : index + 2], 16) / 255.0 for index in (1, 3, 5)]

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in values)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    light = max(_relative_luminance(foreground), _relative_luminance(background))
    dark = min(_relative_luminance(foreground), _relative_luminance(background))
    return (light + 0.05) / (dark + 0.05)


def validate_theme(value: object, *, allow_builtin: bool = False) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ThemePolicyError("theme must be a JSON object")
    if set(value) != _TOP_LEVEL_KEYS:
        raise ThemePolicyError("theme contains unsupported top-level fields")
    if value.get("schema") != THEME_SCHEMA:
        raise ThemePolicyError("unsupported theme schema")

    theme_id = value.get("id")
    name = value.get("name")
    tokens = value.get("tokens")
    if not isinstance(theme_id, str) or len(theme_id) > MAX_THEME_ID_CHARS or not _THEME_ID_RE.fullmatch(theme_id):
        raise ThemePolicyError("invalid theme id")
    if theme_id == DEFAULT_THEME_ID and not allow_builtin:
        raise ThemePolicyError("built-in theme id is reserved")
    if not isinstance(name, str):
        raise ThemePolicyError("theme name must be text")
    clean_name = " ".join(name.split())
    if not clean_name or len(clean_name) > MAX_THEME_NAME_CHARS:
        raise ThemePolicyError("theme name is empty or too long")
    if not isinstance(tokens, dict) or set(tokens) != _TOKEN_KEYS:
        raise ThemePolicyError("theme token set must match the allowlist exactly")

    normalized_tokens: dict[str, object] = {}
    for key in _COLOR_KEYS:
        color = tokens.get(key)
        if not isinstance(color, str) or not _HEX_COLOR_RE.fullmatch(color):
            raise ThemePolicyError(f"invalid color token: {key}")
        normalized_tokens[key] = color.upper()

    radius = tokens.get("radius")
    spacing = tokens.get("spacing")
    font_scale = tokens.get("fontScale")
    if isinstance(radius, bool) or not isinstance(radius, int) or not 0 <= radius <= 24:
        raise ThemePolicyError("radius must be an integer from 0 to 24")
    if isinstance(spacing, bool) or not isinstance(spacing, int) or not 6 <= spacing <= 24:
        raise ThemePolicyError("spacing must be an integer from 6 to 24")
    if isinstance(font_scale, bool) or not isinstance(font_scale, (int, float)):
        raise ThemePolicyError("fontScale must be numeric")
    font_scale = float(font_scale)
    if not math.isfinite(font_scale) or not 0.85 <= font_scale <= 1.35:
        raise ThemePolicyError("fontScale must be between 0.85 and 1.35")
    normalized_tokens.update(radius=radius, spacing=spacing, fontScale=font_scale)

    if contrast_ratio(str(normalized_tokens["text"]), str(normalized_tokens["background"])) < 4.5:
        raise ThemePolicyError("theme text/background contrast is below the accessibility minimum")
    if contrast_ratio(str(normalized_tokens["text"]), str(normalized_tokens["surface"])) < 4.5:
        raise ThemePolicyError("theme text/surface contrast is below the accessibility minimum")

    return {
        "schema": THEME_SCHEMA,
        "id": theme_id,
        "name": clean_name,
        "tokens": normalized_tokens,
    }


def default_theme() -> dict[str, object]:
    return validate_theme(json.loads(json.dumps(DEFAULT_THEME)), allow_builtin=True)


def theme_css(theme: object) -> bytes:
    """Compile a validated data-only theme into fixed SWIR Shell CSS selectors."""

    normalized = validate_theme(theme, allow_builtin=True)
    tokens = normalized["tokens"]
    assert isinstance(tokens, dict)
    return f"""
window.swir-shell {{
  background: {tokens['background']};
  color: {tokens['text']};
  font-size: {float(tokens['fontScale']):.2f}em;
}}
.swir-topbar, .swir-dock {{
  background: {tokens['surface']};
  border-color: {tokens['border']};
  padding: {int(tokens['spacing'])}px 18px;
}}
.swir-brand {{ color: {tokens['accent']}; }}
.swir-subtle {{ color: {tokens['muted']}; }}
.swir-card {{
  background: {tokens['surface']};
  border-color: {tokens['border']};
  border-radius: {int(tokens['radius']) + 4}px;
}}
.swir-launcher {{
  background: {tokens['surface']};
  color: {tokens['text']};
  border-color: {tokens['primary']};
  border-radius: {int(tokens['radius'])}px;
}}
.swir-launcher:hover {{ border-color: {tokens['accent']}; }}
""".encode("ascii")


class ThemeStore:
    """Owner-only storage for validated local theme packages."""

    def __init__(self, data_home: pathlib.Path | None = None) -> None:
        if data_home is None:
            raw = os.environ.get("XDG_DATA_HOME")
            data_home = pathlib.Path(raw).expanduser() if raw else pathlib.Path.home() / ".local" / "share"
        self.data_home = data_home.resolve(strict=False)
        self.directory = self.data_home / "swir" / "themes"

    def _prepare_directory(self) -> None:
        parent = self.directory.parent
        if parent.is_symlink() or self.directory.is_symlink():
            raise RuntimeError("refusing symlinked SWIR theme directory")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise RuntimeError("invalid SWIR theme directory")
        os.chmod(self.directory, 0o700)

    @staticmethod
    def _read_package(path: pathlib.Path) -> dict[str, object]:
        if path.is_symlink():
            raise ThemePolicyError("symbolic-link theme packages are not accepted")
        try:
            info = path.stat()
        except OSError as exc:
            raise ThemePolicyError(f"cannot inspect theme package: {exc}") from exc
        if not path.is_file():
            raise ThemePolicyError("theme package must be a regular file")
        if info.st_size <= 0 or info.st_size > MAX_THEME_BYTES:
            raise ThemePolicyError("theme package size is outside the verified bound")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ThemePolicyError(f"invalid theme JSON: {exc}") from exc
        return validate_theme(payload)

    def install(self, source: str | os.PathLike[str]) -> dict[str, object]:
        raw = pathlib.Path(source).expanduser()
        if not raw.is_absolute():
            raw = pathlib.Path.cwd() / raw
        if raw.is_symlink():
            raise ThemePolicyError("symbolic-link theme packages are not accepted")
        try:
            path = raw.resolve(strict=True)
        except OSError as exc:
            raise ThemePolicyError(f"theme package cannot be resolved: {exc}") from exc
        theme = self._read_package(path)
        self._prepare_directory()
        theme_id = str(theme["id"])
        target = self.directory / f"{theme_id}.swirtheme"
        if target.is_symlink():
            raise RuntimeError("refusing symlinked installed theme")
        encoded = (json.dumps(theme, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=".theme-", suffix=".tmp", dir=self.directory)
        tmp = pathlib.Path(temporary)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
            os.chmod(target, 0o600)
            dir_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if tmp.exists():
                tmp.unlink()
        return theme

    def list_themes(self) -> list[dict[str, object]]:
        result = [default_theme()]
        if not self.directory.exists():
            return result
        if self.directory.is_symlink() or not self.directory.is_dir():
            return result
        for path in sorted(self.directory.glob("*.swirtheme"), key=lambda item: item.name.casefold()):
            try:
                result.append(self._read_package(path))
            except ThemePolicyError:
                continue
        return result

    def load(self, theme_id: object) -> tuple[dict[str, object], bool]:
        if theme_id == DEFAULT_THEME_ID:
            return default_theme(), False
        if not isinstance(theme_id, str) or len(theme_id) > MAX_THEME_ID_CHARS or not _THEME_ID_RE.fullmatch(theme_id):
            return default_theme(), True
        if not self.directory.exists() or self.directory.is_symlink():
            return default_theme(), True
        target = self.directory / f"{theme_id}.swirtheme"
        try:
            return self._read_package(target), False
        except ThemePolicyError:
            return default_theme(), True


def _self_test() -> int:
    base = default_theme()
    assert base["id"] == DEFAULT_THEME_ID
    assert contrast_ratio("#F4FAFF", "#02050A") > 4.5
    assert b"window.swir-shell" in theme_css(base)

    custom = {
        "schema": THEME_SCHEMA,
        "id": "swir.midnight",
        "name": "Midnight",
        "tokens": {
            "background": "#000000",
            "surface": "#101820",
            "primary": "#0088FF",
            "accent": "#62E5FF",
            "text": "#FFFFFF",
            "muted": "#A7C2D2",
            "border": "#31566A",
            "radius": 10,
            "spacing": 12,
            "fontScale": 1.05,
        },
    }
    validated = validate_theme(custom)
    assert validated["id"] == "swir.midnight"

    for mutation in (
        {**custom, "script": "rm -rf /"},
        {**custom, "id": "../escape"},
        {**custom, "tokens": {**custom["tokens"], "text": "url(https://example.invalid)"}},
        {**custom, "tokens": {**custom["tokens"], "text": "#111111"}},
    ):
        try:
            validate_theme(mutation)
        except ThemePolicyError:
            pass
        else:
            raise AssertionError(f"unsafe theme accepted: {mutation}")

    with tempfile.TemporaryDirectory(prefix="swir-theme-selftest-") as temp:
        root = pathlib.Path(temp)
        source = root / "midnight.swirtheme"
        source.write_text(json.dumps(custom), encoding="utf-8")
        store = ThemeStore(root / "data")
        installed = store.install(source)
        assert installed["id"] == "swir.midnight"
        loaded, fallback = store.load("swir.midnight")
        assert loaded["id"] == "swir.midnight" and fallback is False
        fallback_theme, fallback = store.load("missing.theme")
        assert fallback_theme["id"] == DEFAULT_THEME_ID and fallback is True
        target = store.directory / "swir.midnight.swirtheme"
        assert (target.stat().st_mode & 0o777) == 0o600
        assert (store.directory.stat().st_mode & 0o777) == 0o700
    print("SWIR theme runtime self-test: OK")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_self_test() if "--self-test" in sys.argv else 0)
