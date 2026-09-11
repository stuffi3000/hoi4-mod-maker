"""Country-related files: country_tags/countries/history/characters/names/colors/ideas/bookmark/dynamic."""
import os
from data.constants import (
    VALID_MAIN_IDEOLOGIES, DEFAULT_IDEOLOGY_SUBTYPE,
    DEFAULT_MOD_VERSION, DEFAULT_SUPPORTED_VERSION, REPLACE_PATHS,
    get_vanilla_tags,
)
from export.writers.gfx.portraits import write_country_portraits
from export.writers.gfx.flags import write_country_flags


def write_country_colors(tag, rgb, output_dir):
    """Generate common/countries/zz_worldtest_colors.txt — Colors of countries on the map

    Use the zz_worldtest_ prefix to avoid overwriting vanilla's colors.txt of the same name (line 1220, defines all
    color of vanilla TAG). After MOD no longer replaces common/countries, if the file names are the same
    Will cause all vanilla colors to be lost → divide-by-zero crash in the rendering pipeline."""
    d = os.path.join(output_dir, "common", "countries")
    os.makedirs(d, exist_ok=True)
    r, g, b = rgb
    # Append mode: If the file already exists (multi-country situation), accumulate
    path = os.path.join(d, "zz_worldtest_colors.txt")
    mode = "a" if os.path.exists(path) else "w"
    with open(path, mode, encoding="utf-8") as f:
        if mode == "w":
            f.write("#reload countrycolors\n\n")
        f.write(f"{tag} = {{\n")
        f.write(f"\tcolor = rgb {{ {r} {g} {b} }}\n")
        f.write(f"\tcolor_ui = rgb {{ {r} {g} {b} }}\n")
        f.write("}\n\n")


def write_country_names(tag, output_dir, country_name="Fantasy"):
    """Generate common/names/<TAG>_names.txt

    HOI4's automatic character generator (character_manager) will pull it from this file
    First and last name. If a country does not have a corresponding names entry, the game will use the country's localization
    The name is used as origins to search. Failure to search will result in a crash.

    Do not replace_path common/names (keep the original names), just [add] our files."""
    d = os.path.join(output_dir, "common", "names")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{tag}_names.txt"), "w", encoding="utf-8") as f:
        f.write(f"{tag} = {{\n")
        f.write("\tmale = {\n")
        f.write('\t\tnames = { "Alex" "Benjamin" "Charles" "David" "Edward" "Frank" "George" "Henry" "James" "John" "Kevin" "Louis" "Michael" "Nathan" "Oliver" "Peter" }\n')
        f.write("\t}\n")
        f.write("\tfemale = {\n")
        f.write('\t\tnames = { "Alice" "Beatrice" "Catherine" "Diana" "Emma" "Fiona" "Grace" "Helen" "Isabel" "Julia" "Kate" "Laura" "Maria" "Nora" "Olivia" "Patricia" }\n')
        f.write("\t}\n")
        f.write('\tsurnames = { "Smith" "Jones" "Taylor" "Brown" "Williams" "Wilson" "Evans" "Walker" "White" "Roberts" "Lewis" "Harris" "Clark" "Young" "King" "Hill" }\n')
        f.write("\tcallsigns = { }\n")
        f.write("}\n")


def write_country_characters(tag, output_dir, country_name="Fantasy"):
    """Generate national characters file common/characters/<TAG>.txt

    The HOI4 engine will automatically generate country_leader/scientist/field_marshal and other characters for each country.
    If the country does not have these roles defined, automatic generation will fail because origins cannot be found,
    This in turn causes the game to crash on startup (character_manager.cpp reports an error).

    Solution: Provide at least country_leader + field_marshal + general + scientist,
    Override the game's automatically generated paths.
    Note: This is not replace_path common/characters, but [add] file.
    Coexists with original characters."""
    d = os.path.join(output_dir, "common", "characters")
    os.makedirs(d, exist_ok=True)
    # Older exporter versions used ``<TAG>.txt``.  Remove that file only when
    # its distinctive generated shape proves it was exporter-owned, so a
    # user-authored character file is never deleted during re-export.
    legacy_path = os.path.join(d, f"{tag}.txt")
    if os.path.isfile(legacy_path):
        try:
            with open(legacy_path, "r", encoding="utf-8-sig", errors="replace") as legacy_file:
                legacy_head = legacy_file.read(4096)
        except OSError:
            legacy_head = ""
        generated_signature = (
            "characters = {" in legacy_head
            and f"{tag}_leader_despotism" in legacy_head
            and "GFX_Portrait_Europe_Generic_1" in legacy_head
        )
        if generated_signature:
            os.remove(legacy_path)
    # The name field uses character ID as localization key (vanilla approach `name=CHI_chiang_kaishek`),
    # The country_name string cannot be written directly: user-entered text may be non-ASCII,
    # Triple bug stacking causes HOI4 parse to fail → division by zero crashes when the engine automatically generates characters.
    # Files are encoded with UTF-8 BOM consistent with vanilla character files (HOI4 parser is BOM tolerant).
    # The display name goes to localisation/*_l_<lang>.yml (yml.py has written leader/marshal/general/admiral key,
    # Scientist also retains the key here, and the yml will display the raw key without translation, which will not crash).
    with open(os.path.join(d, f"zz_fantasy_{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("# Generated - TC MOD character definitions\n")
        f.write("characters = {\n\n")

        # 1. National leader (one for each of the 4 ideological subtypes, aligned to vanilla minimal format;
        # 1.17 Remove the id=-1 and expire fields to avoid AI initialization verification failure)
        for ideo in ("despotism", "conservatism", "nazism", "marxism"):
            f.write(f"\t{tag}_leader_{ideo} = {{\n")
            f.write(f"\t\tname = {tag}_leader_{ideo}\n")
            f.write("\t\tportraits = {\n")
            f.write("\t\t\tcivilian = { large = GFX_Portrait_Europe_Generic_1 }\n")
            f.write("\t\t}\n")
            f.write("\t\tcountry_leader = {\n")
            f.write(f"\t\t\tideology = {ideo}\n")
            f.write("\t\t\ttraits = { }\n")
            f.write("\t\t}\n")
            f.write("\t}\n\n")

        # 2. Marshal
        f.write(f"\t{tag}_field_marshal_1 = {{\n")
        f.write(f"\t\tname = {tag}_field_marshal_1\n")
        f.write("\t\tportraits = {\n")
        f.write("\t\t\tarmy = { large = GFX_Portrait_Europe_Generic_land_1 }\n")
        f.write("\t\t}\n")
        f.write("\t\tfield_marshal = {\n")
        f.write("\t\t\ttraits = { }\n")
        f.write("\t\t\tskill = 3\n")
        f.write("\t\t\tattack_skill = 3\n")
        f.write("\t\t\tdefense_skill = 3\n")
        f.write("\t\t\tplanning_skill = 3\n")
        f.write("\t\t\tlogistics_skill = 3\n")
        f.write("\t\t}\n")
        f.write("\t}\n\n")

        # 3. General
        f.write(f"\t{tag}_general_1 = {{\n")
        f.write(f"\t\tname = {tag}_general_1\n")
        f.write("\t\tportraits = {\n")
        f.write("\t\t\tarmy = { large = GFX_Portrait_Europe_Generic_land_2 }\n")
        f.write("\t\t}\n")
        f.write("\t\tcorps_commander = {\n")
        f.write("\t\t\ttraits = { }\n")
        f.write("\t\t\tskill = 2\n")
        f.write("\t\t\tattack_skill = 2\n")
        f.write("\t\t\tdefense_skill = 2\n")
        f.write("\t\t\tplanning_skill = 2\n")
        f.write("\t\t\tlogistics_skill = 2\n")
        f.write("\t\t}\n")
        f.write("\t}\n\n")

        # 4. Admiral
        f.write(f"\t{tag}_admiral_1 = {{\n")
        f.write(f"\t\tname = {tag}_admiral_1\n")
        f.write("\t\tportraits = {\n")
        f.write("\t\t\tarmy = { large = GFX_Portrait_Europe_Generic_navy_1 }\n")
        f.write("\t\t}\n")
        f.write("\t\tnavy_leader = {\n")
        f.write("\t\t\ttraits = { }\n")
        f.write("\t\t\tskill = 2\n")
        f.write("\t\t\tattack_skill = 2\n")
        f.write("\t\t\tdefense_skill = 2\n")
        f.write("\t\t\tmaneuvering_skill = 2\n")
        f.write("\t\t\tcoordination_skill = 2\n")
        f.write("\t\t}\n")
        f.write("\t}\n\n")

        # 5. Scientist (4 majors, to avoid automatic generation failure)
        #
        # The scientist database uses the facility specializations
        # ``air``, ``land``, ``naval`` and ``nuclear``.  ``industry`` and
        # ``army`` look plausible but are not registered specialization
        # identifiers; emitting either leaves a dangling role in the
        # character database and is reported during map startup.
        specializations = ["air", "land", "naval", "nuclear"]
        for i, spec in enumerate(specializations, 1):
            f.write(f"\t{tag}_scientist_{i} = {{\n")
            f.write(f"\t\tname = {tag}_scientist_{i}\n")
            f.write("\t\tportraits = {\n")
            f.write("\t\t\tcivilian = { large = GFX_Portrait_Europe_Generic_1 }\n")
            f.write("\t\t}\n")
            f.write("\t\tscientist = {\n")
            f.write("\t\t\tskills = {\n")
            f.write(f"\t\t\t\tspecialization_{spec} = 2\n")
            f.write("\t\t\t}\n")
            f.write("\t\t\ttraits = { }\n")
            f.write("\t\t}\n")
            f.write("\t}\n\n")

        f.write("}\n")


def write_dynamic_countries(output_dir, count=75):
    """Generate the dynamic country pool used by civil wars and puppets.

    ``common/country_tags`` and ``common/countries`` are complete replace
    paths for an exported map, so the vanilla D01-D75 definitions are not
    visible to the game.  Every dynamic tag therefore needs both an entry in
    the tag registry and its own country definition.  Keep the files
    independent (rather than one shared country file) because the engine
    associates country-local name groups and AI state with each tag.
    """
    if count < 0:
        raise ValueError("count must be non-negative")

    tags_dir = os.path.join(output_dir, "common", "country_tags")
    countries_dir = os.path.join(output_dir, "common", "countries")
    os.makedirs(tags_dir, exist_ok=True)
    os.makedirs(countries_dir, exist_ok=True)

    # The zz_ prefix keeps this registry after the regular exported countries
    # file while remaining deterministic across exports.
    tags_path = os.path.join(tags_dir, "zz_dynamic_countries.txt")
    with open(tags_path, "w", encoding="utf-8") as tags_file:
        tags_file.write("dynamic_tags = yes\n\n")
        for i in range(1, count + 1):
            tag = f"D{i:02d}"
            tags_file.write(f'{tag} = "countries/{tag}.txt"\n')

            # Use distinct, valid colours so the country database does not
            # treat all generated countries as one definition at render time.
            r = (i * 37) % 200 + 40
            g = (i * 73) % 200 + 40
            b = (i * 113) % 200 + 40
            with open(os.path.join(countries_dir, f"{tag}.txt"), "w", encoding="utf-8") as country_file:
                country_file.write("use_legacy_ai_pp_spend = yes\n")
                country_file.write(f"color = {{ {r} {g} {b} }}\n")


def write_country(tag, capital_state_id, output_dir):
    """Write a default country. capital_state_id must be a valid State ID, not a province ID!"""
    os.makedirs(os.path.join(output_dir, "common", "country_tags"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "common", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "units"), exist_ok=True)

    # Generate 80 dynamic countries (mandatory for HOI4, otherwise it will crash)
    write_dynamic_countries(output_dir)

    with open(os.path.join(output_dir, "common", "country_tags", "02_worldtest_countries.txt"), "w", encoding="utf-8") as f:
        f.write(f'{tag} = "countries/{tag}.txt"\n')

    with open(os.path.join(output_dir, "common", "countries", f"{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("graphical_culture = western_european_gfx\n")
        f.write("graphical_culture_2d = western_european_2d\n")
        f.write("color = { 100 100 200 }\n")

    # Generate national figures (country_leader/general/scientist)
    write_country_characters(tag, output_dir)
    # Generate an array of country names (to avoid character_manager crashing when it cannot find a name)
    write_country_names(tag, output_dir)
    # Generate national portrait pool (avoid scientist automatic generation crash) ★Crash root cause★
    write_country_portraits(tag, output_dir)
    # Generate country colors (shown on map)
    write_country_colors(tag, (100, 100, 200), output_dir)

    with open(os.path.join(output_dir, "history", "countries", f"{tag} - Fantasy.txt"), "w", encoding="utf-8") as f:
        f.write(f"capital = {capital_state_id}\n")
        f.write(f'oob = "{tag}_1936"\n')
        f.write("set_research_slots = 3\n")
        # No recruit_character — Let HOI4 automatically generate leaders from common/characters.
        # Explicit recruit in 1.17 may reference incorrectly formatted fields, causing AI startup verification to fail and crash.
        f.write("set_politics = {\n\truling_party = neutrality\n")
        f.write('\tlast_election = "1932.1.1"\n\telection_frequency = 48\n')
        f.write("\telections_allowed = no\n}\n")
        f.write("set_popularities = {\n\tdemocratic = 10\n\tfascism = 5\n")
        f.write("\tcommunism = 5\n\tneutrality = 80\n}\n")
        # Wiki: File cannot end with recruit_character, must have non-recruit line at the end
        # Here set_popularities is already the last one, so it meets the requirements
        f.write("\n# end of country history\n")

    with open(os.path.join(output_dir, "history", "units", f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
        f.write("units = { }\n\n")

    write_neutral_country_histories(
        output_dir,
        exported_tags={tag},
        capital_state_id=capital_state_id,
    )


def write_countries_from_mgr(country_mgr, output_dir, states):
    """Write country files using data from CountryManager.
    Note: country_mgr.capital stores [Province ID], but the capital field of HOI4 requires [State ID].
    Here, the province ID will be automatically converted into the State ID containing the province."""
    os.makedirs(os.path.join(output_dir, "common", "country_tags"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "common", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "units"), exist_ok=True)

    # Construct Province ID -> State ID reverse lookup table
    prov_to_state = {}
    for sid, provs in states.items():
        for p in provs:
            prov_to_state[p] = sid
    if not states:
        raise ValueError(
            "Cannot export countries: no states have been generated. Generate province and state data first."
        )
    fallback_state = min(states.keys())

    # Generate 80 dynamic countries (mandatory for HOI4, otherwise it will crash)
    write_dynamic_countries(output_dir)

    # country_tags
    with open(os.path.join(output_dir, "common", "country_tags", "02_worldtest_countries.txt"), "w", encoding="utf-8") as f:
        for tag in country_mgr.countries:
            f.write(f'{tag} = "countries/{tag}.txt"\n')

    for tag, c in country_mgr.countries.items():
        r, g, b = c.color
        with open(os.path.join(output_dir, "common", "countries", f"{tag}.txt"), "w", encoding="utf-8") as f:
            f.write("graphical_culture = western_european_gfx\n")
            f.write("graphical_culture_2d = western_european_2d\n")
            f.write(f"color = {{ {r} {g} {b} }}\n")

        # Generate national figures (country_leader/general/scientist)
        write_country_characters(tag, output_dir, country_name=c.name)
        # Generate an array of country names
        write_country_names(tag, output_dir, country_name=c.name)
        # Generate national portrait pool (avoid scientist automatic generation crash) ★Crash root cause★
        write_country_portraits(tag, output_dir)
        # Generate country colors
        write_country_colors(tag, c.color, output_dir)

        # Province ID → State ID conversion
        capital_state = prov_to_state.get(c.capital, fallback_state)

        # Ideological whitelist verification: illegal ruling_party downgraded to neutrality,
        # Illegal popularity keys are discarded, missing keys are filled with 0, and the sum is normalized to 100
        ruling = c.ruling_party if c.ruling_party in VALID_MAIN_IDEOLOGIES else "neutrality"
        pops = {k: max(0, int(v)) for k, v in (c.popularities or {}).items()
                if k in VALID_MAIN_IDEOLOGIES}
        for k in VALID_MAIN_IDEOLOGIES:
            pops.setdefault(k, 0)
        total = sum(pops.values())
        if total <= 0:
            # All empty → ruling_party 100%
            pops = {k: (100 if k == ruling else 0) for k in VALID_MAIN_IDEOLOGIES}
        elif total != 100:
            # Normalize according to proportion, round off and then use ruling_party to make up the remainder
            scaled = {k: round(v * 100 / total) for k, v in pops.items()}
            diff = 100 - sum(scaled.values())
            scaled[ruling] = scaled.get(ruling, 0) + diff
            pops = scaled

        # The file name must be the same as "countries/{tag}.txt" in country_tags/02_worldtest_countries.txt
        # Exactly, otherwise HOI4 (PHYSFS) cannot find file → country load fails → crash on divide-by-zero when referencing this TAG.
        # vanilla uses "TAG - English_Name.txt" because the full ASCII engine of the name can fuzzy match; our country
        # PHYSFS may fail on non-ASCII paths on Windows, so this file name must be an ASCII TAG.
        with open(os.path.join(output_dir, "history", "countries", f"{tag}.txt"), "w", encoding="utf-8") as f:
            f.write(f"capital = {capital_state}\n")
            f.write(f'oob = "{tag}_1936"\n')
            f.write("set_research_slots = 3\n")
            # Force loading of the vanilla generic_focus universal national policy tree to prevent the engine from trying to match
            # Specific national policy trees such as FRA/GER/ENG (the trigger conditions refer to vanilla idea/trigger will be wrong)
            f.write("load_focus_tree = generic_focus\n")
            # No recruit_character — Let HOI4 automatically generate leaders from common/characters.
            # Explicit recruit may have incorrect reference format (id/expire obsolete fields) in 1.17, causing AI
            # Verification failed and crashed during startup
            f.write(f"set_politics = {{\n\truling_party = {ruling}\n")
            f.write('\tlast_election = "1932.1.1"\n\telection_frequency = 48\n')
            f.write("\telections_allowed = no\n}\n")
            f.write("set_popularities = {\n")
            for party in VALID_MAIN_IDEOLOGIES:
                f.write(f"\t{party} = {pops[party]}\n")
            f.write("}\n")
            # Note: no longer write add_ideas in country history - referencing undefined idea will trigger
            # AI crashes when evaluating every tick. national_spirits data is retained in country_mgr but not
            # Write history (if you really want to use spirits in the future, you must first fully define all ideas)
            f.write("\n# end of country history\n")

        # OOB: There must be at least one division template + one deployed division,
        # Otherwise 5x speed when AI multi-threaded evaluation air force → null deref → client_ping crashes
        # location uses the land province where the country's capital is located
        capital_prov = c.capital if c.capital else 1
        # If capital is 0 or is not in the country's land, find a fallback
        country_states = country_mgr.get_states_of_country(tag)
        any_land_prov = capital_prov
        if country_states:
            first_state = states.get(country_states[0]) if isinstance(states, dict) else None
            if first_state:
                any_land_prov = first_state[0]
        with open(os.path.join(output_dir, "history", "units", f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
            f.write("division_template = {\n")
            f.write(f'\tname = "Infantry Division"\n')
            f.write("\tregiments = {\n")
            f.write("\t\tinfantry = { x = 0 y = 0 }\n")
            f.write("\t\tinfantry = { x = 0 y = 1 }\n")
            f.write("\t\tinfantry = { x = 0 y = 2 }\n")
            f.write("\t}\n")
            f.write("}\n\n")
            f.write("units = {\n")
            f.write("\tdivision = {\n")
            f.write(f'\t\tname = "1st Infantry Division"\n')
            f.write(f"\t\tlocation = {any_land_prov}\n")
            f.write(f'\t\tdivision_template = "Infantry Division"\n')
            f.write("\t\tstart_experience_factor = 0.3\n")
            f.write("\t}\n")
            f.write("}\n")

    # Country ideas files are no longer generated - country history add_ideas is disabled in stage 2
    # write_country_ideas(country_mgr, output_dir)

    # Write empty OOB files for all dynamic countries
    # (D01-D75 are registered in country_tags/zz_dynamic_countries.txt but there is no history/units/Dxx_1936.txt
    # → AI 5x multi-threaded when evaluating their armies null → tbb race → crash)
    write_dynamic_country_oobs(output_dir)

    write_neutral_country_histories(
        output_dir,
        exported_tags=set(country_mgr.countries),
        capital_state_id=fallback_state,
    )


_NEUTRAL_HISTORY_MARKER = "# Generated - TC MOD neutral country history"


def write_neutral_country_histories(
    output_dir: str,
    exported_tags: set[str] | None = None,
    capital_state_id: int = 1,
) -> list[str]:
    """Give still-visible vanilla tags a valid history under ``replace_path``.

    The exporter intentionally keeps ``common/country_tags`` additive: replacing
    that directory removes definitions required by vanilla scripted systems.
    ``history/countries`` is different, however; it is replaced so vanilla
    state IDs cannot leak into the custom map.  Without a history file for each
    additive vanilla tag, the engine reports hundreds of missing histories and
    later dereferences an incompletely initialized country while entering a
    session.  A neutral, unowned country is enough to keep the database
    consistent; only tags explicitly exported by the project receive gameplay
    history and OOB data.

    Dynamic ``D01``…``D75`` tags are excluded because the game provisions those
    slots separately and the exporter already supplies their country/OOB files.
    Existing files (including user-authored histories) are never overwritten.
    The returned list is useful to callers/tests for reporting.
    """
    history_dir = os.path.join(output_dir, "history", "countries")
    os.makedirs(history_dir, exist_ok=True)

    exported = {str(tag).upper() for tag in (exported_tags or ())}
    try:
        fallback_state = max(1, int(capital_state_id))
    except (TypeError, ValueError):
        fallback_state = 1

    # History files are matched by their three-character country-tag prefix.
    # Respect any file already present in an output folder, including files
    # supplied by a user or a previous exporter run.
    existing_prefixes: set[str] = set()
    for filename in os.listdir(history_dir):
        if not filename.lower().endswith(".txt"):
            continue
        stem = os.path.splitext(filename)[0]
        if len(stem) >= 3:
            existing_prefixes.add(stem[:3].upper())

    generated: list[str] = []
    for tag in sorted(get_vanilla_tags()):
        tag = str(tag).upper()
        if tag in exported or (len(tag) == 3 and tag.startswith("D") and tag[1:].isdigit()):
            continue
        if tag in existing_prefixes:
            continue

        path = os.path.join(history_dir, f"{tag}.txt")
        with open(path, "w", encoding="utf-8") as file:
            file.write(f"{_NEUTRAL_HISTORY_MARKER}: {tag}\n")
            file.write(f"capital = {fallback_state}\n")
            file.write("set_research_slots = 1\n")
            file.write("set_politics = {\n")
            file.write("\truling_party = neutrality\n")
            file.write('\tlast_election = "1932.1.1"\n')
            file.write("\telection_frequency = 48\n")
            file.write("\telections_allowed = no\n")
            file.write("}\n")
            file.write("set_popularities = {\n\tneutrality = 100\n}\n")
            file.write("\n# end of neutral country history\n")
        generated.append(tag)
        existing_prefixes.add(tag)

    return generated


def write_dynamic_country_oobs(output_dir, count=75):
    """Write empty OOB for D01..D75. HOI4 will try to read history/units/<TAG>_1936.txt for each registered country."""
    d = os.path.join(output_dir, "history", "units")
    os.makedirs(d, exist_ok=True)
    for i in range(1, count + 1):
        tag = f"D{i:02d}"
        with open(os.path.join(d, f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
            f.write("units = { }\n")


def write_country_ideas(country_mgr, output_dir):
    """Generate common/ideas/<MOD>_country_ideas.txt containing national spirits for all countries.
    Do not replace_path common/ideas (vanilla ideas are retained), only [add] our files."""
    all_spirits = []
    for tag, c in country_mgr.countries.items():
        for spirit in c.national_spirits:
            all_spirits.append(spirit)
    if not all_spirits:
        return

    d = os.path.join(output_dir, "common", "ideas")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "zz_fantasy_country_ideas.txt"), "w", encoding="utf-8") as f:
        f.write("ideas = {\n")
        f.write("\tcountry = {\n")
        for spirit in all_spirits:
            f.write(f"\t\t{spirit.id} = {{\n")
            f.write("\t\t\tallowed = { always = yes }\n")
            f.write("\t\t\tallowed_civil_war = { always = yes }\n")
            f.write("\t\t\tremoval_cost = -1\n")
            f.write(f"\t\t\tpicture = {spirit.picture}\n")
            f.write("\t\t\tmodifier = {\n")
            for k, v in spirit.modifiers.items():
                f.write(f"\t\t\t\t{k} = {v}\n")
            f.write("\t\t\t}\n")
            f.write("\t\t}\n")
        f.write("\t}\n")
        f.write("}\n")


def write_bookmark(mod_name, country_tags, output_dir):
    """Generate bookmark files.
    Strategy:
    1. Use the file with the same name the_gathering_storm.txt / blitzkrieg.txt to overwrite the original version into [empty bookmarks block]
       - Reason: The original bookmark references GER/ENG/JAP and other countries that we have removed, and it will crash when selected.
       - Leave the coverage empty so that players cannot see the original bookmark in the menu
    2. Use z_{safe}.txt to write our own bookmark (the z_ prefix ensures that it is sorted last and will not conflict with the original version)"""
    d = os.path.join(output_dir, "common", "bookmarks")
    os.makedirs(d, exist_ok=True)
    safe = mod_name.replace(" ", "_").upper()

    # --- 1. Block the original bookmark (must have a complete structure, no empty blocks) ---
    for bm_file in ("the_gathering_storm.txt", "blitzkrieg.txt"):
        with open(os.path.join(d, bm_file), "w", encoding="utf-8") as f:
            f.write("bookmarks = {\n")
            f.write("\tbookmark = {\n")
            f.write(f'\t\tname = "DISABLED_{bm_file.replace(".txt", "").upper()}"\n')
            f.write('\t\tdesc = ""\n')
            f.write('\t\tdate = 1936.1.1.12\n')
            f.write('\t\tpicture = GFX_select_date_1936\n')
            f.write('\t\teffect = { randomize_weather = 12345 }\n')
            f.write("\t}\n")
            f.write("}\n")

    # --- 2. Write our own bookmark ---
    safe_file = mod_name.replace(" ", "_").lower()
    bm_name_key = f"{safe}_BOOKMARK"
    bm_desc_key = f"{safe}_BOOKMARK_DESC"
    with open(os.path.join(d, f"z_{safe_file}.txt"), "w", encoding="utf-8") as f:
        f.write("bookmarks = {\n")
        f.write("\tbookmark = {\n")
        f.write(f'\t\tname = {bm_name_key}\n')
        f.write(f'\t\tdesc = {bm_desc_key}\n')
        f.write('\t\tdate = 1936.1.1.12\n')
        f.write('\t\tpicture = GFX_select_date_1936\n')
        if country_tags:
            f.write(f'\t\tdefault_country = "{country_tags[0]}"\n')
        f.write("\t\tdefault = yes\n\n")
        for i, tag in enumerate(country_tags):
            f.write(f'\t\t"{tag}" = {{\n')
            f.write(f'\t\t\thistory = "{tag}_BOOKMARK_DESC"\n')
            f.write(f'\t\t\tideology = neutrality\n')
            if i > 0:
                f.write(f'\t\t\tminor = yes\n')
            f.write(f'\t\t}}\n')
        f.write('\t\t"---" = {\n')
        f.write(f'\t\t\thistory = {safe}_OTHER_BOOKMARK_DESC\n')
        f.write('\t\t}\n')
        f.write('\t\teffect = {\n')
        f.write('\t\t\trandomize_weather = 22345\n')
        f.write('\t\t}\n')
        f.write("\t}\n")
        f.write("}\n")
