#!/usr/bin/env python3
"""Audit the application's English-only translation catalog.

Commands:
  summary             Show the English catalog size.
  missing <catalog>   Report keys missing from a requested catalog.
  check-placeholders  Check placeholder syntax in the English catalog.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import string
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = PROJECT_ROOT / "ui" / "i18n"
SUPPORTED_LANGUAGES = ("en",)
NON_ENGLISH_RE = re.compile(r"[\u3400-\u9fff\u0400-\u04ff]")


def load_lang(lang: str) -> dict[str, str]:
    """Load all ``STRINGS`` dictionaries for a supported catalog."""
    if lang not in SUPPORTED_LANGUAGES:
        return {}
    lang_dir = I18N_DIR / lang
    if not lang_dir.is_dir():
        return {}
    result: dict[str, str] = {}
    for py_file in sorted(lang_dir.glob("*.py")):
        if py_file.stem == "__init__":
            continue
        spec = importlib.util.spec_from_file_location(
            f"_audit_{lang}_{py_file.stem}", py_file
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            print(f"[WARN] Failed to load {py_file}: {exc}", file=sys.stderr)
            continue
        strings = getattr(module, "STRINGS", None)
        if isinstance(strings, dict):
            result.update(strings)
    return result


def list_languages() -> list[str]:
    """Return the catalogs supported by the application."""
    return [lang for lang in SUPPORTED_LANGUAGES if (I18N_DIR / lang).is_dir()]


def _pick_baseline(langs: list[str], exclude: str | None = None) -> str:
    """Select English as the only baseline catalog."""
    return "en" if "en" in langs and exclude != "en" else ""


def cmd_summary() -> int:
    langs = list_languages()
    if not langs:
        print("No English catalog found", file=sys.stderr)
        return 1
    data = load_lang("en")
    print(f"=== i18n Summary (English-only, {len(data)} keys) ===")
    print(f"* en     | {len(data):>5} keys")
    return 0


def cmd_missing(target_lang: str) -> int:
    langs = list_languages()
    if target_lang not in langs:
        print(
            f"Catalog {target_lang!r} not found. Available: {langs}",
            file=sys.stderr,
        )
        return 2
    # With one catalog, checking ``missing en`` is a useful no-op rather than
    # an error caused by excluding the only possible baseline.
    baseline = _pick_baseline(langs, exclude=target_lang) or "en"
    base = load_lang(baseline)
    target = load_lang(target_lang)
    missing = sorted(set(base) - set(target))
    print(f"=== {target_lang} missing {len(missing)} keys (baseline: {baseline}) ===")
    for key in missing:
        print(f"  {key}: {base[key]!r}")
    extra = sorted(set(target) - set(base))
    if extra:
        print(f"=== {target_lang} has {len(extra)} extra keys (review if needed) ===")
        for key in extra:
            print(f"  {key}")
    return 0 if not missing else 1


def cmd_check_placeholders() -> int:
    langs = list_languages()
    if not langs:
        return 2
    data = load_lang("en")
    malformed = []
    for key, value in data.items():
        if NON_ENGLISH_RE.search(value):
            malformed.append((key, value))
            continue
        try:
            list(string.Formatter().parse(value))
        except ValueError:
            malformed.append((key, value))
    print(f"=== Placeholder consistency (English-only): {len(malformed)} mismatches ===")
    for key, value in malformed[:50]:
        print(f"  {key}: {value!r}")
    return 0 if not malformed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the English-only i18n catalog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("summary", help="Show the English catalog size")
    missing = sub.add_parser("missing", help="List missing keys in a catalog")
    missing.add_argument("lang", help="Catalog code (only en is supported)")
    sub.add_parser("check-placeholders", help="Check English placeholders")
    args = parser.parse_args()
    if args.mode == "summary":
        return cmd_summary()
    if args.mode == "missing":
        return cmd_missing(args.lang)
    if args.mode == "check-placeholders":
        return cmd_check_placeholders()
    return 1


if __name__ == "__main__":
    sys.exit(main())
