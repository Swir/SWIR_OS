#!/usr/bin/env python3
"""Deterministic tests for the read-only native package status runtime."""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from package_status_runtime import (  # noqa: E402
    MAX_PACKAGE_ROWS,
    MAX_SEARCH_CHARS,
    normalize_search_term,
    parse_simulated_upgrade,
)


def expect_raises(callable_, expected: type[Exception]) -> None:
    try:
        callable_()
    except expected:
        return
    raise AssertionError(f"expected {expected.__name__}")


def main() -> int:
    assert normalize_search_term("  firefox   esr ") == "firefox esr"
    expect_raises(lambda: normalize_search_term(""), ValueError)
    expect_raises(lambda: normalize_search_term("x" * (MAX_SEARCH_CHARS + 1)), ValueError)
    expect_raises(lambda: normalize_search_term("bad\x00term"), ValueError)

    fixture = "\n".join(
        (
            "NOTE: This is only a simulation!",
            "Inst linux-image-amd64 [6.12.38-1] (6.12.43-1 Debian:13.1/stable [amd64])",
            "Inst curl [8.14.1-1] (8.14.1-2 Debian-Security:13/stable-security [amd64])",
            "Conf curl (8.14.1-2 Debian-Security:13/stable-security [amd64])",
        )
    )
    rows, truncated = parse_simulated_upgrade(fixture)
    assert not truncated
    assert len(rows) == 2
    assert rows[0].name == "linux-image-amd64"
    assert rows[0].current_version == "6.12.38-1"
    assert rows[0].candidate_version == "6.12.43-1"
    assert rows[1].name == "curl"

    huge = "\n".join(f"Inst p{i} [1] (2 repo [amd64])" for i in range(MAX_PACKAGE_ROWS + 50))
    bounded, truncated = parse_simulated_upgrade(huge, 7)
    assert len(bounded) == 7
    assert truncated

    no_current, truncated = parse_simulated_upgrade("Inst new-package (1.0 repo [amd64])")
    assert not truncated
    assert no_current[0].current_version == "unknown"

    print("package status runtime selftest: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
