#!/usr/bin/env python3
"""Add a translation key to the application's English catalog."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = PROJECT_ROOT / "ui" / "i18n"
NON_ENGLISH_RE = re.compile(r"[\u3400-\u9fff\u0400-\u04ff]")


def list_languages() -> list[str]:
    """Return the catalogs supported by the application."""
    return ["en"] if (I18N_DIR / "en").is_dir() else []


def _format_key_line(key: str, value: str) -> str:
    if "\n" in value:
        safe = value.replace('"""', '\\"\\"\\"')
        return f'    "{key}": """{safe}""",'
    safe = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'    "{key}": "{safe}",'


def _key_exists(source: str, key: str) -> bool:
    return f'"{key}":' in source


def _write_new_file(path: Path, file_stem: str, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''"""
{file_stem} — English translation
"""

STRINGS: dict[str, str] = {{
{_format_key_line(key, value)}
}}
''',
        encoding="utf-8",
    )


def _append_key_to_file(path: Path, key: str, value: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if _key_exists(source, key):
        return False
    lines = source.split("\n")
    insert_at = next(
        (index for index in range(len(lines) - 1, -1, -1) if lines[index].strip() == "}"),
        None,
    )
    if insert_at is None:
        raise RuntimeError(f"Could not find the STRINGS closing brace: {path}")
    lines.insert(insert_at, _format_key_line(key, value))
    path.write_text("\n".join(lines), encoding="utf-8")
    return True


def add_key(
    file_stem: str,
    key: str,
    values: dict[str, str],
    force: bool = False,
) -> dict[str, str]:
    """Add ``key`` to the English catalog and return per-language statuses."""
    results: dict[str, str] = {}
    value = values.get("en")
    if value is None:
        return results
    path = I18N_DIR / "en" / f"{file_stem}.py"
    if not path.exists():
        _write_new_file(path, file_stem, key, value)
        results["en"] = "created_file"
        return results
    source = path.read_text(encoding="utf-8")
    if _key_exists(source, key):
        if not force:
            results["en"] = "skipped_exists"
            return results
        lines = [line for line in source.split("\n") if not line.lstrip().startswith(f'"{key}":')]
        path.write_text("\n".join(lines), encoding="utf-8")
        _append_key_to_file(path, key, value)
        results["en"] = "force_overwritten"
        return results
    _append_key_to_file(path, key, value)
    results["en"] = "written"
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a key to the English-only i18n catalog"
    )
    parser.add_argument("file_stem", help="Catalog file name without .py")
    parser.add_argument("key", help="Translation key")
    parser.add_argument("text", help="English translation")
    parser.add_argument(
        "--en", default=None, help="Explicit English translation (overrides text)"
    )
    # Accept the old option for scripts that have not migrated yet, but never
    # create or load a Russian catalog.
    parser.add_argument("--ru", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help="Overwrite an existing key")
    args = parser.parse_args()

    if not list_languages():
        print("No English catalog directory found", file=sys.stderr)
        return 2
    value = args.en if args.en is not None else args.text
    if NON_ENGLISH_RE.search(value):
        print("Translation text must be English; CJK and Cyrillic text is not supported", file=sys.stderr)
        return 2
    results = add_key(args.file_stem, args.key, {"en": value}, force=args.force)
    print(f"key={args.key!r} -> file_stem={args.file_stem!r}:")
    for lang, status in sorted(results.items()):
        print(f"  [{lang}] {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
