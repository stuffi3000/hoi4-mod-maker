# English catalog layout

**Date**: 2026-04-21
**Status**: Implemented and kept as the maintenance record for the catalog split.

## Goal

Keep user-facing text in small, discoverable catalog modules while making the application predictable to package, test, and maintain. The repository currently ships one supported language: English.

## Current layout

```text
ui/i18n/
├── __init__.py          # catalog loading, tr(), and language settings
└── en/
    ├── __init__.py
    ├── menu.py
    ├── toolbar.py
    ├── status.py
    ├── navigation.py
    ├── welcome.py
    ├── common.py
    ├── dialogs.py
    ├── context_menu.py
    ├── tips.py
    ├── validate.py
    ├── export.py
    ├── import_.py
    ├── crash.py
    ├── land.py
    ├── province.py
    ├── state.py
    ├── country.py
    ├── continent.py
    ├── strategic_region.py
    ├── logistics.py
    ├── colormap.py
    ├── default_map.py
    ├── height.py
    ├── river.py
    ├── terrain.py
    ├── density.py
    └── new_land.py
```

Each catalog module exports a `STRINGS` dictionary:

```python
STRINGS = {
    "action_new": "New project",
    "action_open": "Open project",
    "action_save": "Save project",
}
```

## Loader behavior

`ui.i18n` discovers Python catalog modules below the English catalog directory and merges their `STRINGS` dictionaries. Duplicate keys are rejected during loading so a key cannot silently change meaning because of import order.

The public API is intentionally small:

- `tr(key, *args, **kwargs)` formats a catalog value and returns the key when no value exists.
- `set_language(language)` normalizes unsupported settings to English.
- `get_language()` returns the active language code.
- `available_languages()` reports the supported catalog list.
- `reload_translations()` reloads the catalog during tests or development.

The saved language is read from `QSettings` with English as the default. Unsupported or malformed saved values are normalized to English, keeping a fresh installation usable.

## Adding a key

Use `tools/add_i18n_key.py` to add a key to the appropriate English module. The tool refuses duplicate keys unless explicitly forced and validates that the value does not contain CJK or Cyrillic characters. Run `tools/i18n_audit.py check-placeholders` after editing formatted strings.

## Packaging

`hoi4_map_maker.spec` discovers catalog modules dynamically and adds them to the PyInstaller hidden-import list. This keeps packaged builds synchronized with the files present in `ui/i18n/en/`.

## Migration outcome

The former monolithic catalog and obsolete non-English catalogs were removed after their maintained English values had been retained. Runtime call sites continue to use `tr()`; no feature needs to know how catalog files are organized.

## Acceptance checks

- `available_languages()` returns only `en`.
- Every loaded English value is free of CJK and Cyrillic characters.
- Placeholder checks pass for every catalog entry.
- The application starts with English settings on a fresh installation.
- PyInstaller includes every English catalog module.
- The full test suite passes without relying on removed catalog paths.
