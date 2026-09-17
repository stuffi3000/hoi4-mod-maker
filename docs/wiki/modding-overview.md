# HOI4 modding workflow and file loading

This is the project-facing summary of the wiki's **Modding** page. It is the
place to check before adding a generated file or changing descriptor behavior.

## A mod is mounted at the game root

The contents of a mod directory are loaded at the same relative paths as the
base game. A file at:

```text
my_mod/common/country_tags/aurora.txt
```

is read as if it were:

```text
Hearts of Iron IV/common/country_tags/aurora.txt
```

Do not insert an extra wrapper directory such as
`my_mod/project/common/...`; those files will appear to be ignored. The mod
root is the directory named by the user-specific descriptor's `path` field.

Typical roots are:

```text
common/          database definitions: countries, ideas, focuses, buildings
events/          event definitions
history/         starting states, countries, units, and diplomacy
map/             provinces, map art, regions, railways, supply, positions
localisation/    language files
gfx/             image assets
interface/       sprites and GUI definitions
```

The game loads the base game first, then DLC, the user directory, and finally
mods in their effective load order. Files with the same relative path compete:
the later file wins. Different files in the same normal directory are merged,
so a mod can usually add `my_mod_focuses.txt` without copying the vanilla
focus catalogue.

## Descriptors and paths

Each local mod has two descriptors:

| File | Purpose |
| --- | --- |
| `<user>/Hearts of Iron IV/mod/<name>.mod` | User-specific path and launcher metadata; the filename also participates in default load ordering |
| `<mod root>/descriptor.mod` | Mod-shared metadata, suitable for Workshop or another user's checkout |

The user-specific descriptor normally contains the `path` field. Keep the two
descriptors aligned for `name`, `version`, `supported_version`, `tags`,
`dependencies`, and `replace_path` when those fields are used. The launcher may
rewrite the user-specific file and can drop fields it does not understand.

Use forward slashes in descriptor paths and keep the path ASCII-only. A
non-ASCII character in the user directory or mod path can prevent the game
from loading the mod or opening its logs.

Example:

```text
name = "Aurora Map"
path = "C:/mods/aurora-map"
version = "0.1.0"
supported_version = "1.19.*"
tags = { "Total Conversion" }
dependencies = { "Required Base Mod" }
```

`path` belongs only in the user-specific descriptor when the mod is meant to
be shared. `dependencies` changes ordering; it does not magically install the
listed mods. It is the correct mechanism for sub-mods that must load after a
base mod.

## `replace_path` is a full-folder decision

`replace_path = "history/states"` unloads previously indexed files directly in
that folder during main-menu loading. It does not recursively unload every
subdirectory, does not change load order, and does not repair a wrong path. It
also does not affect files that are loaded later by a direct filename link,
such as a country history file's OOB reference.

Use it for a deliberate total replacement of a database folder, especially for
a total-conversion map. Before adding it, copy or intentionally recreate the
generic entries the folder needs. Reckless replacement can leave the game with
no focus tree, no dynamic countries, or no other required database entries.

The launcher must retain `replace_path` in both descriptors. The exporter
should therefore write it deterministically and verify both files rather than
assuming the launcher copied it.

## Clausewitz text structure

Most HOI4 script uses `attribute = argument`:

```pdx
completion_reward = {
    add_political_power = 50
}
```

Important rules for generated text:

- `#` starts a comment that lasts to the end of the line; there is no block
  comment syntax.
- Braces are the only grouping syntax. Indentation is ignored by the engine,
  but consistent indentation exposes unbalanced scopes.
- Do not leave an argument empty. `icon =` causes the next token to be read as
  the icon value.
- Strings use ordinary double quotes. Escape `\"` and `\\` only where needed.
- Effects change game state, triggers return a boolean, scopes move execution
  to another entity, and modifiers apply numeric changes. The active scope is
  part of the API and must be checked before generating a command.
- Evaluation order can matter for effects, database creation, and files with
  the same type. Use stable, namespaced IDs and predictable filenames.

Use UTF-8 without BOM for normal script files. Localisation is the important
exception and requires UTF-8 with BOM; see
[localisation-and-mod-structure.md](localisation-and-mod-structure.md).

## Debugging workflow

Launch with `-debug` while developing. It enables extra map diagnostics,
debug tooltips, the Nudge tool, and more useful error logging. For a crash that
does not identify the cause, add `-crash_data_log` temporarily and inspect the
crash folder's `meta.yml` `LastRead` entry. The last-read line is evidence, not
proof that the preceding file is invalid; the next file or a later runtime
reference may be the actual cause.

Always start with a clean log directory and fix the first meaningful error.
Use [troubleshooting.md](troubleshooting.md) for the map-specific sequence.

## Sources

- [HOI4 Modding](https://hoi4.paradoxwikis.com/Modding)
- [HOI4 Troubleshooting](https://hoi4.paradoxwikis.com/Troubleshooting)
- [HOI4 Defines](https://hoi4.paradoxwikis.com/Defines)
