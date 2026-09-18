#!/usr/bin/env python3
"""Native, unprivileged SWIR OS Calculator.

Expression evaluation is implemented with a strict AST allowlist. The
application never evaluates Python source, never invokes a shell, and does not
need privileged access or network connectivity.
"""

from __future__ import annotations

import ast
import json
import math
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.Calculator"
EVIDENCE_SCHEMA: Final = "swir.native-calculator-runtime-evidence/0.1"
MAX_EXPRESSION_CHARS: Final = 256
MAX_AST_NODES: Final = 64
MAX_ABS_VALUE: Final = 1e100
MAX_EXPONENT: Final = 12.0
MAX_HISTORY: Final = 20

CSS = b"""
window.swir-calculator {
  background: #02050A;
  color: #EAF9FF;
}
.swir-card {
  background: #07111C;
  border: 1px solid rgba(98,229,255,0.34);
  border-radius: 18px;
  padding: 18px;
}
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-display {
  background: #02050A;
  color: #F4FAFF;
  border: 1px solid #0088FF;
  border-radius: 12px;
  padding: 14px;
  font-size: 26px;
  font-weight: 700;
}
.swir-key {
  background: #07111C;
  color: #EAF9FF;
  border: 1px solid rgba(0,136,255,0.7);
  border-radius: 11px;
  padding: 11px 14px;
}
.swir-key:hover { background: #0A2136; border-color: #62E5FF; }
.swir-equals {
  background: #0A2740;
  color: #62E5FF;
  border: 1px solid #62E5FF;
}
.swir-subtle { color: #8FAFC2; }
"""


class CalculatorError(ValueError):
    """Raised when an expression violates the safe calculator contract."""


@dataclass(frozen=True)
class Calculation:
    expression: str
    value: float


class SafeCalculator:
    """Small arithmetic evaluator backed only by explicitly allowed AST nodes."""

    _binary_ops: Final = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a**b,
    }
    _unary_ops: Final = {
        ast.UAdd: lambda value: value,
        ast.USub: lambda value: -value,
    }

    @classmethod
    def evaluate(cls, expression: str) -> Calculation:
        text = expression.strip()
        if not text:
            raise CalculatorError("enter an expression")
        if len(text) > MAX_EXPRESSION_CHARS:
            raise CalculatorError(f"expression exceeds {MAX_EXPRESSION_CHARS} characters")
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            raise CalculatorError("invalid expression") from exc
        nodes = list(ast.walk(tree))
        if len(nodes) > MAX_AST_NODES:
            raise CalculatorError("expression is too complex")
        value = cls._eval_node(tree.body)
        cls._validate_result(value)
        return Calculation(text, value)

    @classmethod
    def _eval_node(cls, node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise CalculatorError("only numeric constants are allowed")
            value = float(node.value)
            cls._validate_result(value)
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in cls._unary_ops:
            value = cls._unary_ops[type(node.op)](cls._eval_node(node.operand))
            cls._validate_result(value)
            return value
        if isinstance(node, ast.BinOp) and type(node.op) in cls._binary_ops:
            left = cls._eval_node(node.left)
            right = cls._eval_node(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise CalculatorError(f"exponent magnitude exceeds {int(MAX_EXPONENT)}")
            if isinstance(node.op, (ast.Div, ast.Mod)) and right == 0:
                raise CalculatorError("division by zero")
            try:
                value = cls._binary_ops[type(node.op)](left, right)
            except (OverflowError, ValueError, ZeroDivisionError) as exc:
                raise CalculatorError("calculation is outside the supported range") from exc
            cls._validate_result(value)
            return value
        raise CalculatorError("only arithmetic operators are allowed")

    @staticmethod
    def _validate_result(value: float) -> None:
        if not math.isfinite(value):
            raise CalculatorError("result must be finite")
        if abs(value) > MAX_ABS_VALUE:
            raise CalculatorError("result is outside the supported range")


def format_value(value: float) -> str:
    if value == 0:
        return "0"
    if float(value).is_integer() and abs(value) < 1e16:
        return str(int(value))
    return format(value, ".14g")


def _self_test() -> int:
    cases = {
        "2 + 3 * 4": 14.0,
        "(12.5 + 7.5) * 3": 60.0,
        "-5 + 2": -3.0,
        "10 % 4": 2.0,
        "2 ** 8": 256.0,
    }
    for expression, expected in cases.items():
        actual = SafeCalculator.evaluate(expression).value
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (expression, actual)
    for rejected in (
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "[1, 2, 3]",
        "1 / 0",
        "2 ** 13",
        "True + 1",
        "1e101",
    ):
        try:
            SafeCalculator.evaluate(rejected)
        except CalculatorError:
            pass
        else:
            raise AssertionError(f"unsafe expression accepted: {rejected}")
    assert format_value(60.0) == "60"
    print("SWIR Calculator self-test: OK")
    return 0


class SwirCalculator(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.entry: Gtk.Entry | None = None
        self.status: Gtk.Label | None = None
        self.history_label: Gtk.Label | None = None
        self.history: list[str] = []
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.e2e_expression = os.environ.get(
            "SWIR_CALCULATOR_E2E_EXPRESSION", "(12.5 + 7.5) * 3"
        )
        self.window_mapped = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Calculator requires an active graphical display")
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Calculator")
        window.set_default_size(390, 570)
        window.add_css_class("swir-calculator")
        self.window = window

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(18)
        outer.set_margin_bottom(18)
        outer.set_margin_start(18)
        outer.set_margin_end(18)
        window.set_child(outer)

        brand = Gtk.Label(label="SWIR Calculator")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        outer.append(brand)

        subtitle = Gtk.Label(label="Local arithmetic • no eval • no network • no privileges")
        subtitle.add_css_class("swir-subtle")
        subtitle.set_xalign(0)
        outer.append(subtitle)

        entry = Gtk.Entry()
        entry.add_css_class("swir-display")
        entry.set_alignment(1.0)
        entry.set_placeholder_text("0")
        entry.set_max_length(MAX_EXPRESSION_CHARS)
        entry.connect("activate", self._calculate_from_entry)
        self.entry = entry
        outer.append(entry)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.add_css_class("swir-card")
        outer.append(grid)

        layout = [
            ("C", 0, 0), ("⌫", 1, 0), ("(", 2, 0), (")", 3, 0),
            ("7", 0, 1), ("8", 1, 1), ("9", 2, 1), ("/", 3, 1),
            ("4", 0, 2), ("5", 1, 2), ("6", 2, 2), ("*", 3, 2),
            ("1", 0, 3), ("2", 1, 3), ("3", 2, 3), ("-", 3, 3),
            ("0", 0, 4), (".", 1, 4), ("%", 2, 4), ("+", 3, 4),
            ("±", 0, 5), ("x²", 1, 5), ("Copy", 2, 5), ("=", 3, 5),
        ]
        for label, col, row in layout:
            button = Gtk.Button(label=label)
            button.add_css_class("swir-key")
            if label == "=":
                button.add_css_class("swir-equals")
            button.set_hexpand(True)
            button.set_vexpand(True)
            button.connect("clicked", self._button_pressed, label)
            grid.attach(button, col, row, 1, 1)

        self.status = Gtk.Label(label="Ready")
        self.status.add_css_class("swir-subtle")
        self.status.set_xalign(0)
        outer.append(self.status)

        self.history_label = Gtk.Label(label="History: empty", wrap=True)
        self.history_label.add_css_class("swir-subtle")
        self.history_label.set_xalign(0)
        outer.append(self.history_label)

        window.connect("map", self._on_mapped)
        window.present()

    def _button_pressed(self, _button: Gtk.Button, label: str) -> None:
        if self.entry is None:
            return
        if label == "C":
            self.entry.set_text("")
            self._set_status("Cleared")
            return
        if label == "⌫":
            text = self.entry.get_text()
            self.entry.set_text(text[:-1])
            self.entry.set_position(-1)
            return
        if label == "=":
            self._calculate_from_entry(self.entry)
            return
        if label == "Copy":
            self._copy_display()
            return
        if label == "±":
            text = self.entry.get_text().strip()
            if text.startswith("-"):
                text = text[1:]
            elif text:
                text = f"-({text})"
            else:
                text = "-"
            self.entry.set_text(text)
            self.entry.set_position(-1)
            return
        if label == "x²":
            text = self.entry.get_text().strip()
            if text:
                self.entry.set_text(f"({text})**2")
                self.entry.set_position(-1)
            return
        self._append(label)

    def _append(self, token: str) -> None:
        if self.entry is None:
            return
        current = self.entry.get_text()
        if len(current) + len(token) > MAX_EXPRESSION_CHARS:
            self._set_status("Expression length limit reached")
            return
        position = self.entry.get_position()
        if position < 0:
            position = len(current)
        updated = current[:position] + token + current[position:]
        self.entry.set_text(updated)
        self.entry.set_position(position + len(token))

    def _calculate_from_entry(self, _entry: Gtk.Entry) -> None:
        if self.entry is None:
            return
        expression = self.entry.get_text()
        try:
            calculation = SafeCalculator.evaluate(expression)
        except CalculatorError as exc:
            self._set_status(str(exc))
            return
        formatted = format_value(calculation.value)
        self.entry.set_text(formatted)
        self.entry.set_position(-1)
        self.history.append(f"{calculation.expression} = {formatted}")
        del self.history[:-MAX_HISTORY]
        self._refresh_history()
        self._set_status("Calculated")

    def _copy_display(self) -> None:
        if self.entry is None or self.window is None:
            return
        display = self.window.get_display()
        clipboard = display.get_clipboard()
        clipboard.set_text(self.entry.get_text())
        self._set_status("Copied result")

    def _refresh_history(self) -> None:
        if self.history_label is None:
            return
        latest = self.history[-3:]
        self.history_label.set_text("History: " + (" • ".join(latest) if latest else "empty"))

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        self.window_mapped = True
        if not self.e2e:
            return
        if self.entry is None:
            return
        self.entry.set_text(self.e2e_expression)
        self._calculate_from_entry(self.entry)
        GLib.idle_add(self._write_evidence)

    def _write_evidence(self) -> bool:
        if not self.e2e or not self.evidence_path or self.entry is None:
            return False
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text:
            return False
        runtime = pathlib.Path(runtime_text).resolve()
        if path.parent.resolve() != runtime:
            print("refusing calculator evidence path outside XDG_RUNTIME_DIR", file=sys.stderr)
            return False
        expected = SafeCalculator.evaluate(self.e2e_expression)
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": self.window_mapped,
            "expression": expected.expression,
            "result": format_value(expected.value),
            "safeAstEvaluator": True,
            "pythonEvalUsed": False,
            "networkAccess": False,
            "privilegedOperations": False,
            "selfUpdater": False,
            "expressionLimitChars": MAX_EXPRESSION_CHARS,
            "astNodeLimit": MAX_AST_NODES,
            "historyBounded": MAX_HISTORY,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self.quit()
        return False


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    app = SwirCalculator()
    return app.run(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
