"""国家相关文件: country_tags/countries/history/characters/names/colors/ideas/bookmark/dynamic."""
import os
from data.constants import (
    VALID_MAIN_IDEOLOGIES, DEFAULT_IDEOLOGY_SUBTYPE,
    DEFAULT_MOD_VERSION, DEFAULT_SUPPORTED_VERSION, REPLACE_PATHS,
)
from export.writers.gfx.portraits import write_country_portraits
from export.writers.gfx.flags import write_country_flags


def write_country_colors(tag, rgb, output_dir):
    """生成 common/countries/zz_worldtest_colors.txt — 地图上国家的颜色

    用 zz_worldtest_ 前缀避免覆盖 vanilla 的同名 colors.txt（1220 行，定义所有
    vanilla TAG 的颜色）。MOD 不再 replace common/countries 后，若文件名相同
    会让 vanilla 颜色全部丢失 → 渲染管线除零崩溃。
    """
    d = os.path.join(output_dir, "common", "countries")
    os.makedirs(d, exist_ok=True)
    r, g, b = rgb
    # 追加模式：如果文件已存在（多国家情况），累加
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
    """生成 common/names/<TAG>_names.txt

    HOI4 的人物自动生成器（character_manager）会从这个文件里拉取
    姓名和姓氏。如果国家没有对应的 names 条目，游戏会用国家的本地化
    名字作为 origins 去查找，查找失败则导致崩溃。

    不 replace_path common/names（保留原版名字），只【添加】我们的文件。
    """
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
    """生成国家人物文件 common/characters/<TAG>.txt

    HOI4 引擎会为每个国家自动生成 country_leader/scientist/field_marshal 等人物。
    如果国家没有这些角色定义，自动生成会因为找不到 origins 而失败，
    进而导致游戏在启动时崩溃（character_manager.cpp 报错）。

    解决：至少提供 country_leader + field_marshal + general + scientist，
    覆盖游戏的自动生成路径。
    注意：这里不 replace_path common/characters，而是【添加】文件，
    和原版 characters 共存。
    """
    d = os.path.join(output_dir, "common", "characters")
    os.makedirs(d, exist_ok=True)
    # name 字段用 character ID 作为 localisation key (vanilla 做法 `name=CHI_chiang_kaishek`),
    # 不能直接写 country_name 字符串 — country_name 可能含中文 + open() 默认 GBK + 无 BOM,
    # 三重 bug 叠加导致 HOI4 parse 失败 → 引擎自动生成 character 时除零崩溃.
    # 文件用 UTF-8 BOM 编码与 vanilla character 文件保持一致 (HOI4 parser 对 BOM 容忍).
    # 显示名走 localisation/*_l_<lang>.yml (yml.py 已写 leader/marshal/general/admiral key,
    # scientist 这里也保留 key, yml 没翻译就显示 raw key, 不会崩).
    with open(os.path.join(d, f"{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("﻿")  # UTF-8 BOM
        f.write("characters = {\n\n")

        # 1. 国家领袖 (4种意识形态子类型各一个, 对齐 vanilla 最小格式;
        #    1.17 去掉 id=-1 和 expire 字段以避免 AI 初始化校验失败)
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

        # 2. 元帅
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

        # 3. 将军
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

        # 4. 海军将领
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

        # 5. 科学家 (4种专业, 避免自动生成失败)
        specializations = ["air", "industry", "naval", "army"]
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
    """dynamic countries 占位 — 由 vanilla 提供，MOD 不再重复生成。

    旧实现写了 D01-D75 的 country_tags 注册 + country 文件。但自从 REPLACE_PATHS
    移除 common/country_tags 和 common/countries（避免 vanilla gfx TAG 查找失败崩溃）后，
    MOD 和 vanilla 的 D01-D75 会重名 → "Duplicate Country Tag" → 加载阶段除零崩。

    vanilla 自带 D01-D75 dynamic countries，数量足够内战/傀儡使用，MOD 直接复用即可。
    保留本函数空实现是为了兼容所有调用点（write_country / write_countries_from_mgr 等）。
    """
    return


def write_country(tag, capital_state_id, output_dir):
    """写一个默认国家。capital_state_id 必须是有效的 State ID，不是省份ID！"""
    os.makedirs(os.path.join(output_dir, "common", "country_tags"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "common", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "units"), exist_ok=True)

    # 生成 80 个 dynamic countries（HOI4 强制要求，否则崩溃）
    write_dynamic_countries(output_dir)

    with open(os.path.join(output_dir, "common", "country_tags", "02_worldtest_countries.txt"), "w", encoding="utf-8") as f:
        f.write(f'{tag} = "countries/{tag}.txt"\n')

    with open(os.path.join(output_dir, "common", "countries", f"{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("graphical_culture = western_european_gfx\n")
        f.write("graphical_culture_2d = western_european_2d\n")
        f.write("color = { 100 100 200 }\n")

    # 生成国家人物（country_leader/将领/科学家）
    write_country_characters(tag, output_dir)
    # 生成国家名字数组（避免 character_manager 找不到名字崩溃）
    write_country_names(tag, output_dir)
    # 生成国家肖像池（避免 scientist 自动生成崩溃）★崩溃根因★
    write_country_portraits(tag, output_dir)
    # 生成国家颜色（地图上显示）
    write_country_colors(tag, (100, 100, 200), output_dir)

    with open(os.path.join(output_dir, "history", "countries", f"{tag} - Fantasy.txt"), "w", encoding="utf-8") as f:
        f.write(f"capital = {capital_state_id}\n")
        f.write(f'oob = "{tag}_1936"\n')
        f.write("set_research_slots = 3\n")
        # 不 recruit_character — 让 HOI4 自动从 common/characters 生成 leader。
        # 显式 recruit 在 1.17 可能引用格式不对的字段导致 AI 启动校验失败崩溃
        f.write("set_politics = {\n\truling_party = neutrality\n")
        f.write('\tlast_election = "1932.1.1"\n\telection_frequency = 48\n')
        f.write("\telections_allowed = no\n}\n")
        f.write("set_popularities = {\n\tdemocratic = 10\n\tfascism = 5\n")
        f.write("\tcommunism = 5\n\tneutrality = 80\n}\n")
        # Wiki: 文件不能以 recruit_character 结尾，最后必须有非 recruit 行
        # 这里 set_popularities 已经是最后一个，所以本身就符合要求
        f.write("\n# end of country history\n")

    with open(os.path.join(output_dir, "history", "units", f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
        f.write("units = { }\n\n")


def write_countries_from_mgr(country_mgr, output_dir, states):
    """用 CountryManager 的数据写国家文件。
    注意：country_mgr.capital 存的是【省份ID】，但 HOI4 的 capital 字段要求【State ID】。
    这里会自动把省份ID转换成包含该省份的State ID。
    """
    os.makedirs(os.path.join(output_dir, "common", "country_tags"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "common", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "units"), exist_ok=True)

    # 构建 省份ID -> State ID 反查表
    prov_to_state = {}
    for sid, provs in states.items():
        for p in provs:
            prov_to_state[p] = sid
    if not states:
        raise ValueError(
            "Cannot export countries: no states have been generated. Generate province and state data first."
        )
    fallback_state = min(states.keys())

    # 生成 80 个 dynamic countries（HOI4 强制要求，否则崩溃）
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

        # 生成国家人物（country_leader/将领/科学家）
        write_country_characters(tag, output_dir, country_name=c.name)
        # 生成国家名字数组
        write_country_names(tag, output_dir, country_name=c.name)
        # 生成国家肖像池（避免 scientist 自动生成崩溃）★崩溃根因★
        write_country_portraits(tag, output_dir)
        # 生成国家颜色
        write_country_colors(tag, c.color, output_dir)

        # 省份ID → State ID 转换
        capital_state = prov_to_state.get(c.capital, fallback_state)

        # 意识形态白名单校验：非法的 ruling_party 降级为 neutrality，
        # 非法的 popularities 键会被丢弃，缺失的键补 0，总和归一化到 100
        ruling = c.ruling_party if c.ruling_party in VALID_MAIN_IDEOLOGIES else "neutrality"
        pops = {k: max(0, int(v)) for k, v in (c.popularities or {}).items()
                if k in VALID_MAIN_IDEOLOGIES}
        for k in VALID_MAIN_IDEOLOGIES:
            pops.setdefault(k, 0)
        total = sum(pops.values())
        if total <= 0:
            # 全空 → ruling_party 100%
            pops = {k: (100 if k == ruling else 0) for k in VALID_MAIN_IDEOLOGIES}
        elif total != 100:
            # 按比例归一化，四舍五入后再用 ruling_party 补余数
            scaled = {k: round(v * 100 / total) for k, v in pops.items()}
            diff = 100 - sum(scaled.values())
            scaled[ruling] = scaled.get(ruling, 0) + diff
            pops = scaled

        # 文件名必须与 country_tags/02_worldtest_countries.txt 里的 "countries/{tag}.txt"
        # 完全一致, 否则 HOI4 (PHYSFS) 找不到文件 → 国家加载失败 → 引用该 TAG 时除零崩溃.
        # vanilla 用 "TAG - English_Name.txt" 是因为名字全 ASCII 引擎能模糊匹配; 我们的国家
        # 名常含中文, PHYSFS 在 Windows 加载非 ASCII 路径失败, 必须严格匹配 = 纯 TAG 命名.
        with open(os.path.join(output_dir, "history", "countries", f"{tag}.txt"), "w", encoding="utf-8") as f:
            f.write(f"capital = {capital_state}\n")
            f.write(f'oob = "{tag}_1936"\n')
            f.write("set_research_slots = 3\n")
            # 强制加载 vanilla generic_focus 通用国策树，避免引擎尝试匹配
            # FRA/GER/ENG 等特定国策树（触发条件引用 vanilla idea/trigger 会错）
            f.write("load_focus_tree = generic_focus\n")
            # 不 recruit_character — 让 HOI4 自动从 common/characters 生成 leader。
            # 显式 recruit 在 1.17 可能引用格式不对（id/expire 废弃字段）导致 AI
            # 启动时校验失败崩溃
            f.write(f"set_politics = {{\n\truling_party = {ruling}\n")
            f.write('\tlast_election = "1932.1.1"\n\telection_frequency = 48\n')
            f.write("\telections_allowed = no\n}\n")
            f.write("set_popularities = {\n")
            for party in VALID_MAIN_IDEOLOGIES:
                f.write(f"\t{party} = {pops[party]}\n")
            f.write("}\n")
            # 注意：不再在 country history 写 add_ideas —— 引用未定义 idea 会触发
            # AI 每 tick 评估时崩。national_spirits 数据保留在 country_mgr 但不
            # 写入 history（以后真要做 spirits 必须先把所有 ideas 完整定义）
            f.write("\n# end of country history\n")

        # OOB：必须有至少一个 division template + 一个部署的 division，
        # 否则 5x 速度时 AI 多线程评估空军队 → null deref → client_ping 崩
        # location 用国家首都所在的 land province
        capital_prov = c.capital if c.capital else 1
        # 如果 capital 是 0 或不在该国土地，找一个 fallback
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

    # 不再生成 country ideas 文件 —— 阶段 2 已禁止 country history add_ideas
    # write_country_ideas(country_mgr, output_dir)

    # 为所有 dynamic countries 写空 OOB 文件
    # （D01-D75 在 country_tags/zz_dynamic_countries.txt 里注册但没有 history/units/Dxx_1936.txt
    #  → AI 5x 多线程评估它们的军队时 null → tbb race → 崩）
    write_dynamic_country_oobs(output_dir)


def write_dynamic_country_oobs(output_dir, count=75):
    """为 D01..D75 写空 OOB。HOI4 对每个注册的 country 都会尝试读 history/units/<TAG>_1936.txt"""
    d = os.path.join(output_dir, "history", "units")
    os.makedirs(d, exist_ok=True)
    for i in range(1, count + 1):
        tag = f"D{i:02d}"
        with open(os.path.join(d, f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
            f.write("units = { }\n")


def write_country_ideas(country_mgr, output_dir):
    """生成 common/ideas/<MOD>_country_ideas.txt 包含所有国家的 national spirits。
    不 replace_path common/ideas（vanilla idea 都保留），只【添加】我们的文件。
    """
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
    """生成 bookmark 文件。
    策略：
    1. 用同名文件 the_gathering_storm.txt / blitzkrieg.txt 覆盖原版为【空 bookmarks 块】
       - 原因：原版 bookmark 引用 GER/ENG/JAP 等我们已移除的国家，选中会崩溃
       - 覆盖为空让玩家在菜单里看不到原版 bookmark
    2. 用 z_{safe}.txt 写我们自己的 bookmark（z_ 前缀确保排序在后，不会和原版冲突）
    """
    d = os.path.join(output_dir, "common", "bookmarks")
    os.makedirs(d, exist_ok=True)
    safe = mod_name.replace(" ", "_").upper()

    # --- 1. 屏蔽原版 bookmark（必须有完整结构，不能空块） ---
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

    # --- 2. 写我们自己的 bookmark ---
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
