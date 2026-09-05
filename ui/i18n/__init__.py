"""
国际化支持 — 按语言分文件夹。

目录结构：
    ui/i18n/
        __init__.py   ← 本文件（加载器 + 对外 API）
        zh/*.py       ← 每个文件是一个 feature 的翻译，含 STRINGS dict
        en/*.py
        <lang>/*.py   ← 加新语言 = 新建文件夹

加新语言：复制 en/ → <lang>/，翻译每个文件里的 STRINGS value，重启软件即生效。
缺失的 key 自动 fallback 到 en → zh → key 本身，不会崩。
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 语言 -> {key: text}
_languages: dict[str, dict[str, str]] = {}
_DEFAULT_LANGUAGE = "en"
# The application is intentionally English-only.  The legacy zh/ru catalogs
# remain in the repository for historical reference, but are never loaded or
# exposed through the runtime language API.
_SUPPORTED_LANGUAGES = ("en",)
_current_lang: str = _DEFAULT_LANGUAGE
_PKG_ROOT = Path(__file__).parent


def _load_language_dir(lang: str) -> dict[str, str]:
    """加载 ui/i18n/<lang>/*.py，合并所有 STRINGS。"""
    lang_dir = _PKG_ROOT / lang
    if not lang_dir.is_dir():
        return {}
    merged: dict[str, str] = {}
    for py_file in sorted(lang_dir.glob("*.py")):
        if py_file.stem == "__init__":
            continue
        module_name = f"ui.i18n.{lang}.{py_file.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            logger.exception("Failed to load translation file: %s (%s)", module_name, exc)
            continue
        strings = getattr(mod, "STRINGS", None)
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
    """扫描所有语言文件夹并加载。"""
    for entry in sorted(_PKG_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name not in _SUPPORTED_LANGUAGES:
            continue
        loaded = _load_language_dir(name)
        if loaded:
            _languages[name] = loaded


def _load_saved_language() -> str:
    try:
        from PyQt5.QtCore import QSettings

        s = QSettings("HOI4MapMaker", "Settings")
        saved = str(s.value("language", _DEFAULT_LANGUAGE))
        if saved not in _SUPPORTED_LANGUAGES:
            # Normalize a locale left by an older installation so subsequent
            # launches cannot restore a disabled language.
            s.setValue("language", _DEFAULT_LANGUAGE)
            return _DEFAULT_LANGUAGE
        return saved
    except Exception:
        return _DEFAULT_LANGUAGE


# 启动时加载
_load_all_languages()
_current_lang = _load_saved_language()
if _current_lang not in _languages:
    _current_lang = _DEFAULT_LANGUAGE


# ---------- 对外 API ----------
# 语言 code -> 母语显示名（社区加新语言时扩展此表）
_DISPLAY_NAMES: dict[str, str] = {"en": "English"}


def available_languages() -> list[str]:
    """Return the only supported application language."""
    return [lang for lang in _SUPPORTED_LANGUAGES if lang in _languages]


def language_display_name(code: str) -> str:
    """返回语言 code 的母语显示名，未知则回退到 code 本身。"""
    return _DISPLAY_NAMES.get(code, code)


def set_language(lang: str) -> None:
    """Keep the application in English and normalize legacy locale requests."""
    global _current_lang
    if lang != _DEFAULT_LANGUAGE:
        logger.info("Ignoring unsupported language %s; English-only mode is enabled", lang)
    _current_lang = _DEFAULT_LANGUAGE
    try:
        from PyQt5.QtCore import QSettings

        s = QSettings("HOI4MapMaker", "Settings")
        s.setValue("language", _DEFAULT_LANGUAGE)
    except Exception:
        pass


def get_language() -> str:
    """Return ``en``; non-English locales are intentionally unsupported."""
    return _DEFAULT_LANGUAGE


def tr(key: str, *args: object, **kwargs: object) -> str:
    """
    获取翻译文本，支持 str.format 位置参数和命名参数。
    例：tr("status_pos", 100, 200)             -> "位置: (100, 200)"
        tr("dlg_batch_state_done", sid=5, n=3) -> "已创建州 5（3 个省份）"

    English mode falls back directly to the key so non-English text cannot
    leak into the UI.
    placeholder 不匹配时 logger.warning 不再静默吞 (历史上的 silent KeyError 坑).
    """
    # English-only mode has a single catalog and a single fallback path.
    for lang in (_DEFAULT_LANGUAGE,):
        text = _languages.get(lang, {}).get(key)
        if text is None:
            continue
        if not args and not kwargs:
            return text
        try:
            return text.format(*args, **kwargs)
        except (IndexError, KeyError) as exc:
            logger.warning(
                "i18n placeholder mismatch: key=%s lang=%s args=%r kwargs=%r "
                "template=%r error=%s",
                key, lang, args, kwargs, text, exc,
            )
            return text
    return key


def tr_pair(zh: str, en: str, *args: object, **kwargs: object) -> str:
    """Return the English form for dynamic messages in all circumstances."""
    text = en
    if not args and not kwargs:
        return text
    try:
        return text.format(*args, **kwargs)
    except (IndexError, KeyError) as exc:
        logger.warning(
            "i18n placeholder mismatch: pair lang=%s args=%r kwargs=%r "
            "template=%r error=%s",
            _current_lang, args, kwargs, text, exc,
        )
        return text


def reload_translations() -> None:
    """热重载：清空并重新扫描（用于开发调试）。"""
    global _current_lang
    _languages.clear()
    _load_all_languages()
    _current_lang = _DEFAULT_LANGUAGE
