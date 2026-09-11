# HOI4 localisation and MOD structure

This page is an English-only reference for the localisation and file-layout conventions used by the exporter.

## Localisation files

Localisation files use the `.yml` extension and are stored in a language directory, for this project:

```text
localisation/english/*_l_english.yml
```

The first non-empty line must declare the language:

```yaml
l_english:
 MY_MOD_TITLE:0 "My Mod"
 MY_MOD_DESCRIPTION:0 "A custom world for Hearts of Iron IV."
```

Use UTF-8 with a BOM, ASCII quotation marks, and one localisation entry per line. The optional `:0` version marker is conventional. Escape an embedded quotation mark as `\"`, and write a literal dollar sign as `$$` when the string parser requires it.

Keys should use stable Latin identifiers such as `MY_MOD_TITLE`. Keep keys unique, avoid whitespace, and ensure every key used by a script, focus, decision, event, country, or GUI has an English value.

## Formatting and substitutions

HOI4 localisation supports colour codes, text icons, variables, and scope functions. Preserve their syntax when editing translated text:

```yaml
 MY_STATUS:0 "Control: §G[?control_value|%0]§!"
 MY_ICON:0 "£army_experience Army experience"
 MY_SCOPE_TEXT:0 "[ROOT.GetName] joined [FROM.GetFactionName]"
```

The key inside `$OTHER_KEY$`, `[ROOT.GetName]`, or a text-icon expression is not ordinary prose and must not be translated. Test strings with the game's `logs/text.log` after changing formatting codes.

## `replace` localisation

To override a vanilla key without copying an entire catalogue, place an English file below `replace/`:

```text
localisation/english/replace/my_mod_l_english.yml
```

The file still needs the `l_english:` header. `replace_path` in a descriptor affects whole game directories and is separate from localisation key replacement; use it only when the complete replacement behavior is intended.

## MOD layout

A minimal MOD commonly contains:

```text
my_mod/
├── descriptor.mod
├── common/
│   ├── country_tags/
│   ├── countries/
│   ├── decisions/
│   ├── national_focus/
│   └── on_actions/
├── events/
├── history/
│   ├── countries/
│   ├── states/
│   └── units/
├── localisation/
│   └── english/
├── interface/
└── gfx/
```

The descriptor's `path` points to the local MOD directory in the user's MOD registry file. The published `descriptor.mod` describes the MOD itself. Keep paths slash-separated and make sure the directory names match the target game's expected layout.

## Descriptor essentials

```text
name = "My Mod"
version = "1.0.0"
supported_version = "1.19.*"
tags = { "Total Conversion" }
```

Optional fields include `picture`, `remote_file_id`, `dependencies`, and `replace_path`. Edit the descriptor copies consistently and preserve Workshop metadata when deploying an existing item.

## Export checklist

- use only `l_english` files in the generated localisation tree;
- save localisation as UTF-8 with BOM;
- verify every referenced key has an English entry;
- keep scripted placeholders and formatting codes unchanged;
- check `error.log` and `text.log` after loading the MOD;
- confirm the descriptor points to the intended MOD root.

## Sources

- [HOI4 Localisation](https://hoi4.paradoxwikis.com/Localisation)
- [HOI4 Mod structure](https://hoi4.paradoxwikis.com/Mod_structure)
- [HOI4 Modding](https://hoi4.paradoxwikis.com/Modding)
- [Localisation reference mirror](https://github.com/cpntodd/HOI4-MCP/blob/main/paradox_wiki/Localisation%20-%20Hearts%20of%20Iron%204%20Wiki.md)
