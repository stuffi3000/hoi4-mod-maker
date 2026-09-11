"""English localization loading and the public translation API."""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_languages: dict[str, dict[str, str]] = {}
_DEFAULT_LANGUAGE = "en"
_SUPPORTED_LANGUAGES = ("en",)
_current_lang = _DEFAULT_LANGUAGE
_PKG_ROOT = Path(__file__).parent


def _load_language_dir(lang: str) -> dict[str, str]:
    """Load and merge the ``STRINGS`` dictionaries in one catalog directory."""
    lang_dir = _PKG_ROOT / lang
    if not lang_dir.is_dir():
        return {}

    merged: dict[str, str] = {}
    for py_file in sorted(lang_dir.glob("*.py")):
        if py_file.stem == "__init__":
            continue
        module_name = f"ui.i18n.{lang}.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.exception("Failed to load translation file: %s (%s)", module_name, exc)
            continue

        strings = getattr(module, "STRINGS", None)
        if not isinstance(strings, dict):
            logger.warning("%s has no STRINGS dictionary; skipping", module_name)
            continue
        overlap = merged.keys() & strings.keys()
        if overlap:
            raise ImportError(
                f"Duplicate translation keys: {sorted(overlap)} in {lang}/{py_file.name}"
            )
        merged.update(strings)
    return merged


def _load_all_languages() -> None:
    """Load the supported English catalog."""
    for lang in _SUPPORTED_LANGUAGES:
        loaded = _load_language_dir(lang)
        if loaded:
            _languages[lang] = loaded


def _load_saved_language() -> str:
    """Read the saved locale and normalize disabled legacy values to English."""
    try:
        from PyQt5.QtCore import QSettings

        settings = QSettings("HOI4MapMaker", "Settings")
        saved = str(settings.value("language", _DEFAULT_LANGUAGE))
        if saved not in _SUPPORTED_LANGUAGES:
            settings.setValue("language", _DEFAULT_LANGUAGE)
            return _DEFAULT_LANGUAGE
        return saved
    except Exception:
        return _DEFAULT_LANGUAGE


_load_all_languages()
_current_lang = _load_saved_language()
if _current_lang not in _languages:
    _current_lang = _DEFAULT_LANGUAGE

_DISPLAY_NAMES = {"en": "English"}


def available_languages() -> list[str]:
    """Return the languages supported by the application."""
    return [lang for lang in _SUPPORTED_LANGUAGES if lang in _languages]


def language_display_name(code: str) -> str:
    """Return a human-readable language name, or the code when unknown."""
    return _DISPLAY_NAMES.get(code, code)


def set_language(lang: str) -> None:
    """Keep the application in English and normalize legacy locale requests."""
    global _current_lang
    if lang != _DEFAULT_LANGUAGE:
        logger.info("Ignoring unsupported language %s; English-only mode is enabled", lang)
    _current_lang = _DEFAULT_LANGUAGE
    try:
        from PyQt5.QtCore import QSettings

        QSettings("HOI4MapMaker", "Settings").setValue("language", _DEFAULT_LANGUAGE)
    except Exception:
        pass


def get_language() -> str:
    """Return the active application language."""
    return _DEFAULT_LANGUAGE


def tr(key: str, *args: object, **kwargs: object) -> str:
    """Translate a key and format its positional or named arguments."""
    text = _languages.get(_DEFAULT_LANGUAGE, {}).get(key)
    if text is None:
        return key
    if not args and not kwargs:
        return text
    try:
        return text.format(*args, **kwargs)
    except (IndexError, KeyError) as exc:
        logger.warning(
            "i18n placeholder mismatch: key=%s args=%r kwargs=%r template=%r error=%s",
            key,
            args,
            kwargs,
            text,
            exc,
        )
        return text


def reload_translations() -> None:
    """Reload the English catalog, primarily for development and tests."""
    global _current_lang
    _languages.clear()
    _load_all_languages()
    _current_lang = _DEFAULT_LANGUAGE
