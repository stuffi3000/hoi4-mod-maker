"""National portraits portraits/TAG.txt."""
import os


def write_country_portraits(tag, output_dir):
    """Generate portraits/<TAG>.txt — HOI4 top-level portraits directory

    [Cause of crash] HOI4 automatically generates missing scientists for each country when starting the game.
    It comes from the scientist pool in portraits/<TAG>.txt or portraits/continent_xxx.txt
    Randomly select portraits. If the country does not have this file, autogeneration fails → crashes.

    Files must be placed in the portraits/ folder (not common/portraits) in the MOD root directory."""
    d = os.path.join(output_dir, "portraits")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{tag}.txt"), "w", encoding="utf-8") as f:
        f.write(f"{tag} = {{\n")

        # scientist (key, otherwise crash)
        f.write("\tscientist = {\n")
        f.write("\t\tmale = {\n")
        for i in range(1, 17):
            f.write(f'\t\t\t"GFX_portrait_generic_europe_male_{i:02d}"\n')
        f.write("\t\t}\n")
        f.write("\t\tfemale = {\n")
        for i in range(1, 17):
            f.write(f'\t\t\t"GFX_portrait_generic_europe_female_{i:02d}"\n')
        f.write("\t\t}\n")
        f.write("\t}\n")

        # army (general)
        f.write("\tarmy = {\n")
        f.write("\t\tmale = {\n")
        for i in range(1, 6):
            f.write(f'\t\t\t"GFX_Portrait_Europe_Generic_land_{i}"\n')
        f.write("\t\t}\n")
        f.write("\t}\n")

        # navy
        f.write("\tnavy = {\n")
        f.write("\t\tmale = {\n")
        for i in range(1, 4):
            f.write(f'\t\t\t"GFX_Portrait_Europe_Generic_navy_{i}"\n')
        f.write("\t\t}\n")
        f.write("\t}\n")

        # political (leader, by ideology)
        f.write("\tpolitical = {\n")
        for i, ideo in enumerate(["communism", "democratic", "fascism", "neutrality"], 1):
            f.write(f"\t\t{ideo} = {{\n")
            f.write("\t\t\tmale = {\n")
            f.write(f'\t\t\t\t"GFX_Portrait_Europe_Generic_{i}"\n')
            f.write("\t\t\t}\n")
            f.write("\t\t}\n")
        f.write("\t}\n")

        # operative
        f.write("\toperative = {\n")
        f.write("\t\tmale = { \"GFX_portrait_operative_unknown\" }\n")
        f.write("\t\tfemale = { \"GFX_portrait_operative_unknown\" }\n")
        f.write("\t}\n")

        # fallback male/female
        f.write("\tmale = { \"GFX_portrait_unknown\" }\n")
        f.write("\tfemale = { \"GFX_portrait_unknown_female\" }\n")

        f.write("}\n")

