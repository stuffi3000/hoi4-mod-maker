"""Write the English localisation files used by exported HOI4 mods."""
import os


def _state_name(s, sid: int) -> str:
    """Return a state's configured English name or a stable fallback."""
    configured = (getattr(s, "name_en", "") or "").strip()
    if configured:
        return configured
    name = (getattr(s, "name", "") or "").strip()
    if name and name != f"STATE_{sid}":
        return name
    return f"State {sid}"


def _region_name(region, rid: int) -> str:
    """Return a strategic region's configured name or a stable fallback."""
    configured = (getattr(region, "name_en", "") or "").strip()
    if configured:
        return configured
    name = (getattr(region, "name", "") or "").strip()
    if name and name != f"STRATEGICREGION_{rid}":
        return name
    return f"Region {rid}"


def _city_name(state, province_id: int, fallback: str, vp_index: int) -> str:
    """Return a victory-point name, preferring its explicit English value."""
    configured = (getattr(state, "vp_names_en", {}) or {}).get(province_id, "").strip()
    if configured:
        return configured
    name = (getattr(state, "vp_names", {}) or {}).get(province_id, "").strip()
    if name:
        return name
    if vp_index == 0:
        return fallback
    return f"{fallback} City {vp_index + 1}"


def _escape_yml(text: str) -> str:
    """Keep a value safe inside a quoted HOI4 YAML entry."""
    return text.replace('"', "'").replace("\n", " ").replace("\r", "")


def write_localisation_simple(mod_name, tag, states, output_dir, region_count=24):
    """Write a compact English localisation file for a minimal export."""
    directory = os.path.join(output_dir, "localisation")
    os.makedirs(directory, exist_ok=True)
    safe_name = mod_name.replace(" ", "_")
    path = os.path.join(directory, f"{safe_name}_l_english.yml")
    with open(path, "w", encoding="utf-8-sig") as stream:
        stream.write("l_english:\n")
        for sid in states:
            stream.write(f' STATE_WT_{sid}:0 "State {sid}"\n')
        for rid in range(1, region_count + 1):
            stream.write(f' STRATEGICREGION_WT_{rid}:0 "Region {rid}"\n')
        stream.write(' SUPPLYAREA_WT_1:0 "Fantasy Supply"\n')
        stream.write(' FANTASY_BOOKMARK:0 "Fantasy World"\n')
        stream.write(' FANTASY_BOOKMARK_DESC:0 "A fantasy world awaits."\n')
        stream.write(f' {tag}:0 "Fantasy Country"\n')
        stream.write(f' {tag}_DEF:0 "Fantasy Country"\n')
        stream.write(f' {tag}_ADJ:0 "Fantasy"\n')
        stream.write(f' {tag}_BOOKMARK_DESC:0 "Play as Fantasy Country"\n')
        stream.write(' OTHER_BOOKMARK_DESC:0 "Other nations"\n')


def _open_yml(directory: str, safe_name: str, topic: str):
    """Open a topic file with the English localisation header."""
    path = os.path.join(directory, f"zz_{safe_name}_{topic}_l_english.yml")
    stream = open(path, "w", encoding="utf-8-sig")
    stream.write("l_english:\n")
    return stream


def write_localisation_full(
    mod_name,
    state_mgr,
    country_mgr,
    states,
    output_dir,
    region_count=24,
    region_mgr=None,
):
    """Write topic-separated English localisation for a complete export."""
    directory = os.path.join(output_dir, "localisation")
    os.makedirs(directory, exist_ok=True)
    safe_name = mod_name.replace(" ", "_")

    with _open_yml(directory, safe_name, "states") as stream:
        if state_mgr and state_mgr.states:
            for sid, state in state_mgr.states.items():
                state_name = _state_name(state, sid)
                stream.write(f' STATE_WT_{sid}:0 "{_escape_yml(state_name)}"\n')
                for vp_index, province_id in enumerate(state.victory_points.keys()):
                    city = _city_name(state, province_id, state_name, vp_index)
                    stream.write(
                        f' VICTORY_POINTS_{province_id}:0 "{_escape_yml(city)}"\n'
                    )
        else:
            for sid in states:
                stream.write(f' STATE_WT_{sid}:0 "State {sid}"\n')

    with _open_yml(directory, safe_name, "strategic_regions") as stream:
        if region_mgr is not None and region_mgr.regions:
            for rid, region in sorted(region_mgr.regions.items()):
                name = _region_name(region, rid)
                stream.write(f' STRATEGICREGION_WT_{rid}:0 "{_escape_yml(name)}"\n')
        else:
            for rid in range(1, region_count + 1):
                stream.write(f' STRATEGICREGION_WT_{rid}:0 "Region {rid}"\n')
        stream.write(
            f' SUPPLYAREA_WT_1:0 "{_escape_yml(mod_name)} Supply"\n'
        )

    countries = _open_yml(directory, safe_name, "countries")
    leaders = _open_yml(directory, safe_name, "leaders")
    ideas = _open_yml(directory, safe_name, "ideas")
    try:
        if country_mgr and country_mgr.countries:
            for tag, country in country_mgr.countries.items():
                country_name = _escape_yml(country.name or tag)
                countries.write(f' {tag}:0 "{country_name}"\n')
                countries.write(f' {tag}_DEF:0 "{country_name}"\n')
                countries.write(f' {tag}_ADJ:0 "{country_name}"\n')
                countries.write(
                    f' {tag}_BOOKMARK_DESC:0 "Play as {country_name}"\n'
                )

                leader_name = f"{country_name} Leader"
                for ideology in ("despotism", "conservatism", "nazism", "marxism"):
                    leaders.write(f' {tag}_leader_{ideology}:0 "{leader_name}"\n')
                leaders.write(f' {tag}_field_marshal_1:0 "{country_name} Marshal"\n')
                leaders.write(f' {tag}_general_1:0 "{country_name} General"\n')
                leaders.write(f' {tag}_admiral_1:0 "{country_name} Admiral"\n')
                for index in range(1, 5):
                    leaders.write(
                        f' {tag}_scientist_{index}:0 "{country_name} Scientist {index}"\n'
                    )

                for spirit in country.national_spirits:
                    name = _escape_yml(spirit.name)
                    description = _escape_yml(spirit.desc or spirit.name)
                    ideas.write(f' {spirit.id}:0 "{name}"\n')
                    ideas.write(f' {spirit.id}_desc:0 "{description}"\n')
        else:
            tag = "AAA"
            country_name = "Fantasy Country"
            countries.write(f' {tag}:0 "{country_name}"\n')
            countries.write(f' {tag}_DEF:0 "{country_name}"\n')
            countries.write(f' {tag}_ADJ:0 "Fantasy"\n')
            countries.write(f' {tag}_BOOKMARK_DESC:0 "Play as {country_name}"\n')
            for ideology in ("despotism", "conservatism", "nazism", "marxism"):
                leaders.write(f' {tag}_leader_{ideology}:0 "{country_name} Leader"\n')
            leaders.write(f' {tag}_field_marshal_1:0 "{country_name} Marshal"\n')
            leaders.write(f' {tag}_general_1:0 "{country_name} General"\n')
            leaders.write(f' {tag}_admiral_1:0 "{country_name} Admiral"\n')
            for index in range(1, 5):
                leaders.write(
                    f' {tag}_scientist_{index}:0 "{country_name} Scientist {index}"\n'
                )
    finally:
        countries.close()
        leaders.close()
        ideas.close()

    with _open_yml(directory, safe_name, "bookmarks") as stream:
        bookmark_key = mod_name.replace(" ", "_").upper()
        description = f"A world of {mod_name} awaits."
        stream.write(f' {bookmark_key}_BOOKMARK:0 "{_escape_yml(mod_name)}"\n')
        stream.write(f' {bookmark_key}_BOOKMARK_DESC:0 "{_escape_yml(description)}"\n')
        stream.write(' {0}_OTHER_BOOKMARK_DESC:0 "Other nations"\n'.format(bookmark_key))
        if bookmark_key != "FANTASY":
            stream.write(f' FANTASY_BOOKMARK:0 "{_escape_yml(mod_name)}"\n')
            stream.write(f' FANTASY_BOOKMARK_DESC:0 "{_escape_yml(description)}"\n')
            stream.write(' OTHER_BOOKMARK_DESC:0 "Other nations"\n')
