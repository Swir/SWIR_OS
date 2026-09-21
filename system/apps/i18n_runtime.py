#!/usr/bin/env python3
"""Bounded translation runtime for first-party native SWIR System Edition apps.

The catalog is intentionally data-only and embedded with the runtime so the
installed image never executes translator-provided code or depends on writable
catalog locations. English is the authoritative fallback. Initial real catalogs
cover Polish and Norwegian Bokmål; unsupported languages continue to use the
safe English surface until a reviewed catalog is added.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

from core_runtime import normalize_language_tag

CATALOG_SCHEMA: Final = "swir.native-i18n/0.1"
DEFAULT_CATALOG_LANGUAGE: Final = "en"
MAX_TRANSLATION_KEY_CHARS: Final = 96
MAX_TRANSLATION_VALUE_CHARS: Final = 2048


class CatalogPolicyError(ValueError):
    """A built-in translation catalog violates the bounded catalog contract."""


_ENGLISH: Final = {
    "app.window_title": "SWIR Settings",
    "app.scope": "USER SETTINGS",
    "section.language_region": "Language & Region",
    "row.interface_language": "Interface language preference",
    "row.clock24h": "Use 24-hour clock",
    "section.appearance": "Appearance & Shell Themes",
    "option.follow_system": "Follow system preference",
    "row.color_preference": "Color preference",
    "row.shell_theme": "Shell theme / skin",
    "button.import_theme": "Import .swirtheme",
    "button.reset_theme": "Reset to SWIR Default",
    "theme.policy_note": "Theme packages are local data-only JSON: only allowlisted colors, spacing, radius and font scale are accepted. Scripts, CSS injection, URLs and privileged code are rejected. Low-contrast themes fail validation and the shell always falls back to SWIR Default.",
    "section.default_apps": "Default Apps",
    "default_apps.note": "Choose per-user handlers from installed applications that advertise every canonical type for the category. Changes use the desktop application registry only; no root access, package mutation or application removal is performed.",
    "category.browser": "Web browser",
    "category.media": "Media player",
    "category.image": "Image viewer / editor",
    "category.pdf": "PDF viewer",
    "category.text": "Text / code editor",
    "category.archive": "Archive manager",
    "button.apply": "Apply",
    "status.user_scope": "Per-user settings only — privileged system changes are not exposed here.",
    "button.save": "Save",
    "dialog.import_theme_title": "Import SWIR Theme",
    "dialog.import": "Import",
    "dialog.cancel": "Cancel",
    "dialog.theme_filter": "SWIR Theme packages",
    "status.default_changed": "Default {category} app changed to {app}.",
    "status.default_failed": "Could not update every {category} handler; no system privilege was used.",
    "status.default_missing": "No compatible {category} handler is available.",
    "status.theme_imported": "Imported {name}. Save to activate it on the next shell start.",
    "status.theme_rejected": "Theme import rejected: {reason}",
    "status.theme_reset": "SWIR Default selected. Save to activate it.",
    "status.saved": "Saved securely to your SWIR user profile. Theme changes apply on the next shell start.",
}

_POLISH: Final = {
    "app.window_title": "Ustawienia SWIR",
    "app.scope": "USTAWIENIA UŻYTKOWNIKA",
    "section.language_region": "Język i region",
    "row.interface_language": "Preferowany język interfejsu",
    "row.clock24h": "Używaj zegara 24-godzinnego",
    "section.appearance": "Wygląd i motywy powłoki",
    "option.follow_system": "Użyj ustawień systemu",
    "row.color_preference": "Preferencje kolorów",
    "row.shell_theme": "Motyw / skórka powłoki",
    "button.import_theme": "Importuj .swirtheme",
    "button.reset_theme": "Przywróć domyślny motyw SWIR",
    "theme.policy_note": "Pakiety motywów są lokalnym formatem JSON zawierającym wyłącznie dane: akceptowane są tylko dozwolone kolory, odstępy, promień zaokrągleń i skala czcionki. Skrypty, wstrzykiwanie CSS, adresy URL i kod uprzywilejowany są odrzucane. Motywy o zbyt niskim kontraście nie przechodzą walidacji, a powłoka zawsze może wrócić do domyślnego motywu SWIR.",
    "section.default_apps": "Aplikacje domyślne",
    "default_apps.note": "Wybierz dla użytkownika obsługę spośród zainstalowanych aplikacji, które deklarują wszystkie wymagane typy dla danej kategorii. Zmiany korzystają wyłącznie z rejestru aplikacji pulpitu; bez dostępu root, modyfikacji pakietów ani usuwania aplikacji.",
    "category.browser": "Przeglądarka internetowa",
    "category.media": "Odtwarzacz multimediów",
    "category.image": "Przeglądarka / edytor obrazów",
    "category.pdf": "Przeglądarka PDF",
    "category.text": "Edytor tekstu / kodu",
    "category.archive": "Menedżer archiwów",
    "button.apply": "Zastosuj",
    "status.user_scope": "Tylko ustawienia użytkownika — uprzywilejowane zmiany systemowe nie są tutaj dostępne.",
    "button.save": "Zapisz",
    "dialog.import_theme_title": "Importuj motyw SWIR",
    "dialog.import": "Importuj",
    "dialog.cancel": "Anuluj",
    "dialog.theme_filter": "Pakiety motywów SWIR",
    "status.default_changed": "Domyślna aplikacja dla kategorii {category} została zmieniona na {app}.",
    "status.default_failed": "Nie udało się zaktualizować wszystkich skojarzeń kategorii {category}; nie użyto uprawnień systemowych.",
    "status.default_missing": "Brak zgodnej aplikacji obsługującej kategorię {category}.",
    "status.theme_imported": "Zaimportowano {name}. Zapisz ustawienia, aby aktywować motyw przy następnym uruchomieniu powłoki.",
    "status.theme_rejected": "Import motywu odrzucony: {reason}",
    "status.theme_reset": "Wybrano domyślny motyw SWIR. Zapisz ustawienia, aby go aktywować.",
    "status.saved": "Bezpiecznie zapisano ustawienia w profilu użytkownika SWIR. Zmiany motywu zostaną zastosowane przy następnym uruchomieniu powłoki.",
}

_NORWEGIAN_BOKMAL: Final = {
    "app.window_title": "SWIR-innstillinger",
    "app.scope": "BRUKERINNSTILLINGER",
    "section.language_region": "Språk og område",
    "row.interface_language": "Språk for grensesnitt",
    "row.clock24h": "Bruk 24-timers klokke",
    "section.appearance": "Utseende og skalltemaer",
    "option.follow_system": "Følg systeminnstillingen",
    "row.color_preference": "Fargevalg",
    "row.shell_theme": "Skalltema / utseende",
    "button.import_theme": "Importer .swirtheme",
    "button.reset_theme": "Tilbakestill til SWIR-standard",
    "theme.policy_note": "Temapakker er lokal JSON som bare inneholder data: kun godkjente farger, avstand, hjørneradius og skriftstørrelse godtas. Skript, CSS-injeksjon, URL-er og privilegert kode avvises. Temaer med for lav kontrast blir avvist, og skallet kan alltid gå tilbake til SWIR-standard.",
    "section.default_apps": "Standardapper",
    "default_apps.note": "Velg brukerens standardbehandlere blant installerte apper som annonserer alle nødvendige typer for kategorien. Endringene bruker bare skrivebordets appregister; ingen root-tilgang, pakkemutasjon eller fjerning av apper utføres.",
    "category.browser": "Nettleser",
    "category.media": "Mediespiller",
    "category.image": "Bildeviser / redigerer",
    "category.pdf": "PDF-viser",
    "category.text": "Tekst- / kodeeditor",
    "category.archive": "Arkivbehandler",
    "button.apply": "Bruk",
    "status.user_scope": "Kun brukerinnstillinger — privilegerte systemendringer er ikke tilgjengelige her.",
    "button.save": "Lagre",
    "dialog.import_theme_title": "Importer SWIR-tema",
    "dialog.import": "Importer",
    "dialog.cancel": "Avbryt",
    "dialog.theme_filter": "SWIR-temapakker",
    "status.default_changed": "Standardappen for {category} er endret til {app}.",
    "status.default_failed": "Kunne ikke oppdatere alle behandlere for {category}; ingen systemrettigheter ble brukt.",
    "status.default_missing": "Ingen kompatibel behandler er tilgjengelig for {category}.",
    "status.theme_imported": "Importerte {name}. Lagre for å aktivere temaet ved neste skallstart.",
    "status.theme_rejected": "Temaimport avvist: {reason}",
    "status.theme_reset": "SWIR-standard er valgt. Lagre for å aktivere temaet.",
    "status.saved": "Lagret sikkert i SWIR-brukerprofilen din. Temaendringer gjelder ved neste skallstart.",
}

_RAW_CATALOGS: Final = {
    "en": {"schema": CATALOG_SCHEMA, "language": "en", "strings": _ENGLISH},
    "pl-PL": {"schema": CATALOG_SCHEMA, "language": "pl-PL", "strings": _POLISH},
    "nb-NO": {"schema": CATALOG_SCHEMA, "language": "nb-NO", "strings": _NORWEGIAN_BOKMAL},
}


def _placeholders(text: str) -> frozenset[str]:
    names: set[str] = set()
    for _literal, field_name, _format_spec, _conversion in string.Formatter().parse(text):
        if field_name:
            if any(token in field_name for token in (".", "[", "]")):
                raise CatalogPolicyError("translation placeholders must be simple names")
            names.add(field_name)
    return frozenset(names)


def _validate_catalog(language: str, value: object, english: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, dict) or set(value) != {"schema", "language", "strings"}:
        raise CatalogPolicyError(f"invalid catalog envelope: {language}")
    if value.get("schema") != CATALOG_SCHEMA or value.get("language") != language:
        raise CatalogPolicyError(f"catalog identity mismatch: {language}")
    strings_value = value.get("strings")
    if not isinstance(strings_value, dict):
        raise CatalogPolicyError(f"catalog strings must be an object: {language}")
    if set(strings_value) != set(english):
        raise CatalogPolicyError(f"catalog key set differs from English source: {language}")

    normalized: dict[str, str] = {}
    for key, text in strings_value.items():
        if not isinstance(key, str) or not key or len(key) > MAX_TRANSLATION_KEY_CHARS:
            raise CatalogPolicyError(f"invalid translation key in {language}")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TRANSLATION_VALUE_CHARS:
            raise CatalogPolicyError(f"invalid translation value for {key} in {language}")
        if _placeholders(text) != _placeholders(english[key]):
            raise CatalogPolicyError(f"placeholder mismatch for {key} in {language}")
        normalized[key] = text
    return MappingProxyType(normalized)


def _build_catalogs() -> Mapping[str, Mapping[str, str]]:
    english = _ENGLISH
    catalogs = {
        language: _validate_catalog(language, envelope, english)
        for language, envelope in _RAW_CATALOGS.items()
    }
    return MappingProxyType(catalogs)


CATALOGS: Final = _build_catalogs()


@dataclass(frozen=True)
class Translator:
    requested_language: str
    catalog_language: str
    strings: Mapping[str, str]

    @property
    def uses_fallback(self) -> bool:
        return self.requested_language != self.catalog_language

    @property
    def text_direction(self) -> str:
        # Direction follows the rendered catalog, never an untranslated request.
        return "rtl" if self.catalog_language.split("-", 1)[0] in {"ar", "he"} else "ltr"

    def translate(self, key: str, **values: object) -> str:
        if key not in self.strings:
            raise KeyError(f"unknown translation key: {key}")
        text = self.strings[key]
        expected = _placeholders(text)
        if set(values) != set(expected):
            raise KeyError(f"translation arguments for {key} must be exactly {sorted(expected)}")
        return text.format(**values) if values else text

    __call__ = translate


def available_catalog_languages() -> tuple[str, ...]:
    return tuple(CATALOGS)


def translator_for(language: object) -> Translator:
    normalized = normalize_language_tag(language)
    requested = normalized or DEFAULT_CATALOG_LANGUAGE
    catalog_language = requested if requested in CATALOGS else DEFAULT_CATALOG_LANGUAGE
    return Translator(
        requested_language=requested,
        catalog_language=catalog_language,
        strings=CATALOGS[catalog_language],
    )
