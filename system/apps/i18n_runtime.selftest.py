#!/usr/bin/env python3
"""Self-tests for the bounded native SWIR i18n runtime."""

from __future__ import annotations

from i18n_runtime import (
    CATALOGS,
    CatalogPolicyError,
    _placeholders,
    available_catalog_languages,
    translator_for,
)


def main() -> int:
    assert available_catalog_languages() == ("en", "pl-PL", "nb-NO")
    assert set(CATALOGS["en"]) == set(CATALOGS["pl-PL"]) == set(CATALOGS["nb-NO"])

    english = translator_for("en_US.UTF-8")
    assert english.requested_language == "en"
    assert english.catalog_language == "en"
    assert english.uses_fallback is False
    assert english("app.window_title") == "SWIR Settings"

    polish = translator_for("pl_PL.UTF-8")
    assert polish.requested_language == "pl-PL"
    assert polish.catalog_language == "pl-PL"
    assert polish.uses_fallback is False
    assert polish("app.window_title") == "Ustawienia SWIR"
    assert polish("button.save") == "Zapisz"
    assert "Firefox" in polish("status.default_changed", category="Przeglądarka internetowa", app="Firefox")

    norwegian = translator_for("no_NO.UTF-8")
    assert norwegian.requested_language == "nb-NO"
    assert norwegian.catalog_language == "nb-NO"
    assert norwegian("section.language_region") == "Språk og område"
    assert norwegian("button.save") == "Lagre"

    german = translator_for("de_DE.UTF-8")
    assert german.requested_language == "de-DE"
    assert german.catalog_language == "en"
    assert german.uses_fallback is True
    assert german("section.default_apps") == "Default Apps"

    arabic = translator_for("ar")
    assert arabic.requested_language == "ar"
    assert arabic.catalog_language == "en"
    assert arabic.text_direction == "ltr", "English fallback must not force RTL layout"

    unsupported = translator_for("xx_YY.UTF-8")
    assert unsupported.requested_language == "en"
    assert unsupported.catalog_language == "en"

    try:
        polish("missing.translation.key")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown translation keys must fail closed")

    try:
        polish("status.default_changed", category="Przeglądarka internetowa")
    except KeyError:
        pass
    else:
        raise AssertionError("missing format arguments must fail closed")

    try:
        polish("button.save", unexpected="value")
    except KeyError:
        pass
    else:
        raise AssertionError("unexpected format arguments must fail closed")

    assert _placeholders("Changed {category} to {app}.") == frozenset({"category", "app"})
    try:
        _placeholders("Unsafe {user.name}")
    except CatalogPolicyError:
        pass
    else:
        raise AssertionError("complex translation placeholders must be rejected")

    print("native i18n runtime self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
