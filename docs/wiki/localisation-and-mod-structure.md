# HOI4 localization and MOD structure

This reference combines the text-file encoding rules with the directory and descriptor rules that determine which generated files the game loads. The spelling “localization” is used here for consistency with the repository; the wiki and game paths use `localisation`.

## Localization files

Localization files use the `.yml` extension and are normally stored in a language directory:

```text
localisation/english/*_l_english.yml
```

The filename must contain the language token, and the first non-empty line must declare it:

```yaml
l_english:
 MY_MOD_TITLE:0 "My Mod"
 MY_MOD_DESCRIPTION:0 "A custom world for Hearts of Iron IV."
```

Use UTF-8 with a BOM, ordinary ASCII quotation marks, and one entry per physical line. The numeric `:0` version marker is conventional and accepted by common vanilla files. Escape an embedded quotation mark as `\"`; use `\\n` where a game text line break is intended. Keep keys stable, unique, and made from safe Latin identifiers. Keys are case-sensitive.

The localization parser is not a general YAML parser. Indentation is only the visual convention shown above; a malformed header, non-BOM encoding, wrapped value, or stray character can make an otherwise valid-looking file disappear from the localization database.

## Formatting, text icons, and substitutions

Color codes and text icons use literal game control characters, not mojibake produced by opening a UTF-8 file with the wrong code page:

```yaml
l_english:
 MY_STATUS:0 "Control: §G[?control_value|%0]§!"
 MY_ICON:0 "£army_experience Army experience"
 MY_SCOPE_TEXT:0 "[ROOT.GetName] joined [FROM.GetFactionName]"
```

The expression inside `$OTHER_KEY$`, `[ROOT.GetName]`, or a text-icon token is syntax, not ordinary prose. Preserve its spelling and punctuation when translating. Test strings containing icons, colors, scripted variables, or scope functions in the game and inspect `logs/text.log` if they display as raw text.

## Overriding vanilla localization

To override selected vanilla keys, place a file below a localization `replace` directory:

```text
localisation/english/replace/my_mod_l_english.yml
```

The file still needs the `l_english:` header. A localization `replace` directory is a key-level override mechanism; it is different from a descriptor `replace_path`, which replaces a whole game directory and can remove inherited vanilla definitions. Keep full-directory replacement decisions explicit in the export manifest.

## MOD root and descriptors

The MOD root is mounted as if it were the game's installation root. Put `common`, `history`, `map`, `events`, `gfx`, `interface`, `localisation`, and other game directories directly below that root. An extra wrapper directory such as `my_mod/my_mod/common` means the game cannot find the files. An extra wrapper around the selected MOD directory is ignored by the launcher, not interpreted as part of the MOD.

There are normally two descriptor files:

| File | Typical location | Purpose |
| --- | --- | --- |
| User-specific descriptor | `<user>/Documents/Paradox Interactive/Hearts of Iron IV/mod/name.mod` | Launcher registration and local `path` |
| MOD-specific descriptor | `<mod root>/descriptor.mod` | MOD metadata distributed with the MOD |

A local descriptor can contain a filesystem path; `descriptor.mod` should not depend on the user's absolute path. Keep both descriptors' name, version, supported-version, tags, dependencies, and replacement intent synchronized where both are emitted:

```text
name = "My Mod"
version = "1.0.0"
supported_version = "1.19.*"
tags = { "Total Conversion" }
dependencies = { "A required MOD" }
```

Use forward slashes in descriptor paths, keep paths and filenames ASCII-compatible, and do not quote a path in a way that leaves an extra wrapper component. `dependencies` affects load order; it is not a substitute for copying or replacing a file.

## Load order and `replace_path`

The effective data set is built from the base game, DLC, user modifications, and their load order. For the same relative filename, the later loaded file wins. Different files in the same directory are merged. A dependency is therefore part of the data contract and must be tested with the generated MOD enabled.

`replace_path = "directory"` unloads the files directly in that directory during menu loading. It does not recursively replace every subdirectory, and it does not change load order. Use it only when the MOD owns the complete directory contract; a too-broad replacement can remove definitions that the generated MOD never wrote. If a full-conversion exporter uses replacement paths, write and validate an explicit allowlist.

## MOD layout checklist

```text
my_mod/
  descriptor.mod
  common/
    country_tags/
    countries/
    decisions/
    national_focus/
    on_actions/
  events/
  history/
    countries/
    states/
    units/
  localisation/
    english/
  map/
  interface/
  gfx/
```

- files are directly below the MOD root's expected game directories;
- every localization file has the correct language token and BOM;
- descriptors agree about the intended target version and MOD root;
- dependencies are resolved and replacement paths are narrow and intentional;
- every player-facing identifier has an English localization entry;
- `error.log`, `text.log`, and the launcher log are checked after a clean enable/disable cycle.

## Sources

- [HOI4 Modding](https://hoi4.paradoxwikis.com/Modding)
- [HOI4 Mod structure](https://hoi4.paradoxwikis.com/Mod_structure)
- [HOI4 Localisation](https://hoi4.paradoxwikis.com/Localisation)
- [Modding reference mirror](https://github.com/thelight0211/hoi4-wiki/blob/main/Modding%20-%20Hearts%20of%20Iron%204%20Wiki.md)
