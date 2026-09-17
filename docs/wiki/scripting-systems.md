# HOI4 scripting systems

This is a practical reference for the script systems that the tool may generate after the map foundation is stable: events, focuses, decisions, ideas, and on-actions. Script identifiers, effects, triggers, scopes, and available fields are version-sensitive; use the selected game's vanilla files as the final schema.

## Shared Clausewitz rules

HOI4 script is a Clausewitz key/value language, not JSON or general-purpose code:

```pdx
key = value
block = {
    nested_key = value
}
```

Comments use `#`. Values are usually unquoted identifiers, numbers, `yes`/`no`, dates, or quoted text. Braces must balance, duplicate IDs should be avoided, and an empty argument after `=` is not a harmless placeholder. Keep generated IDs namespaced by project and country tag.

The important semantic categories are:

| Category | Meaning | Typical use |
| --- | --- | --- |
| Scope | The object currently being evaluated | Country, state, province, character, unit, strategic region |
| Trigger | A boolean condition | `has_war = yes`, ownership, technology, date |
| Effect | A state-changing operation | Add stability, fire an event, add an idea |
| Modifier | A temporary or permanent numeric rule | Production, war support, construction, AI behavior |
| Localization key | Player-facing text looked up from a `.yml` file | Event title, focus name, tooltip |

An effect changes the current or explicitly targeted scope; a trigger tests it. A country-scoped trigger cannot be assumed to work in a state or province scope. Before emitting a block, record the scope at the point where it runs and verify each trigger/effect against the target version's definitions.

## Events

Event definitions live in `events/*.txt`. Declare a namespace outside the event blocks and use a namespaced ID:

```pdx
add_namespace = aurora

country_event = {
    id = aurora.1
    title = aurora.1.t
    desc = aurora.1.d
    picture = GFX_aurora_event
    is_triggered_only = yes

    option = {
        name = aurora.1.a
        add_political_power = 25
    }
}
```

Common event types include `country_event`, `news_event`, `state_event`, `unit_leader_event`, and `operative_leader_event`. A triggered-only event is called by an effect; an event with a `trigger` or mean-time-to-happen block can be evaluated automatically. Use the event type and recipient scope required by the target version.

Fire an event with a short form or a parameter block:

```pdx
country_event = aurora.1
country_event = { id = aurora.1 days = 3 random_days = 2 }
```

Localize the title, description, options, and any generated tooltip keys. A missing picture or invalid scope can remain hidden until the event is displayed or fired.

## National focuses

Focus trees are defined in `common/national_focus/*.txt`. Continuous focuses use `common/continuous_focus/*.txt`:

```pdx
focus_tree = {
    id = aurora_focus_tree
    country = { factor = 0 modifier = { add = 10 tag = AUR } }

    focus = {
        id = AUR_industry
        icon = GFX_goal_generic_construct_civilian
        x = 0
        y = 0
        cost = 10
        completion_reward = {
            add_political_power = 50
        }
    }
}
```

Focus IDs, prerequisites, mutually exclusive groups, availability triggers, completion effects, AI weights, icons, and localization keys all form one contract. Shared and joint trees have additional selection syntax; copy a working vanilla pattern from the target version before generating them.

## Decisions

Decision categories and decisions are defined in `common/decisions/*.txt`; category placement can vary by game version. A category controls presentation and visibility, while a decision provides its cost and lifecycle:

```pdx
aurora_decisions = {
    icon = generic_political_pressure
    visible = { has_war = yes }

    aurora_rebuild = {
        icon = generic_construct_civilian
        visible = { has_war = no }
        available = { has_equipment = { infantry_equipment = 100 } }
        cost = 50
        complete_effect = { add_stability = 0.05 }
        days_remove = 30
        ai_will_do = { base = 1 }
    }
}
```

The usual lifecycle is `visible` -> `available` -> `complete_effect`, with optional removal and cancellation triggers/effects. Localize the decision name, description, blocked text, and tooltip variants expected by the UI.

## Ideas and national spirits

Ideas are defined under `common/ideas/*.txt` and added by country history or effects:

```pdx
ideas = {
    country = {
        aurora_reconstruction = {
            picture = generic_industry
            allowed = { tag = AUR }
            removal_cost = 50
            consumer_goods_factor = -0.05
            production_speed_buildings_factor = 0.10
        }
    }
}
```

The idea category, modifiers, removal rules, picture, and localization must all be legal in the target version. Use country effects to add or remove ideas after startup; do not rely on rewriting already-exported history as a runtime mechanism.

## On-actions and reusable script

On-actions live in `common/on_actions/*.txt` and run at engine-defined points. Add an event or effect under the exact on-action key used by the selected version and keep the active scope in mind. Reusable scripted effects and triggers are useful for generated content, but their parameter names and scope assumptions should be documented beside the definition.

Do not generate a large content system before the map foundation has stable IDs. Events, focuses, decisions, and ideas may mention state, province, country, or strategic-region IDs; a province migration after content generation can invalidate all of them.

## Assets and localization

Player-facing text belongs in `localisation/english/*_l_english.yml`. Event pictures, focus icons, decision icons, and idea pictures need matching interface sprite definitions and image assets in `gfx/`:

```text
interface/*.gfx
gfx/interface/*.dds or *.tga
localisation/english/*_l_english.yml
```

Do not reference an asset that only exists in the vanilla installation when the MOD is intended to run independently, unless the export manifest explicitly records that inheritance.

## Script validation checklist

- every file is in the directory expected by the target version;
- IDs and event namespaces are unique within the effective load order;
- each effect and trigger is legal in its current scope;
- every visible identifier has English localization;
- every icon, portrait, and event picture resolves to an interface asset;
- map/state/country references use the final frozen ID mapping;
- the first parser error in `error.log` is fixed before chasing cascaded messages;
- at least one clean start/tick/save/reload test exercises generated scripts.

## Sources

- [HOI4 Event modding](https://hoi4.paradoxwikis.com/Event_modding)
- [HOI4 National focus modding](https://hoi4.paradoxwikis.com/National_focus_modding)
- [HOI4 Decision modding](https://hoi4.paradoxwikis.com/Decision_modding)
- [HOI4 Idea modding](https://hoi4.paradoxwikis.com/Idea_modding)
- [HOI4 On actions](https://hoi4.paradoxwikis.com/On_actions)
- [HOI4 Effects](https://hoi4.paradoxwikis.com/Effects)
- [HOI4 Triggers](https://hoi4.paradoxwikis.com/Triggers)
- [HOI4 Scopes](https://hoi4.paradoxwikis.com/Scopes)
