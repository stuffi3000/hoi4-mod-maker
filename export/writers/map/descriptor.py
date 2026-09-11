"""descriptor.mod writes."""
import os
from data.constants import DEFAULT_MOD_VERSION, REPLACE_PATHS
from services.game_assets import resolve_supported_version


def write_descriptor(mod_name, output_dir):
    rp = "\n".join(f'replace_path="{p}"' for p in REPLACE_PATHS)
    # Automatically follow the local game version (the export will not be marked "outdated" by the launcher after the game is updated)
    supported = resolve_supported_version()

    # Internal descriptor.mod (in MOD directory)
    with open(os.path.join(output_dir, "descriptor.mod"), "w", encoding="utf-8") as f:
        f.write(f'version="{DEFAULT_MOD_VERSION}"\n')
        f.write('tags={\n\t"Alternative History"\n\t"Map"\n\t"Total Conversion"\n}\n')
        f.write(f'name="{mod_name}"\n')
        f.write(f'supported_version="{supported}"\n')
        f.write(rp + "\n")

    # Outer .mod file (next to the MOD directory, required by the launcher)
    mod_dir_name = os.path.basename(output_dir)
    outer_mod = os.path.join(os.path.dirname(output_dir), f"{mod_dir_name}.mod")
    with open(outer_mod, "w", encoding="utf-8") as f:
        f.write(f'version="{DEFAULT_MOD_VERSION}"\n')
        f.write('tags={\n\t"Alternative History"\n\t"Map"\n\t"Total Conversion"\n}\n')
        f.write(f'name="{mod_name}"\n')
        f.write(f'supported_version="{supported}"\n')
        # Use forward slash for path
        abs_path = os.path.abspath(output_dir).replace("\\", "/")
        f.write(f'path="{abs_path}"\n')
        f.write(rp + "\n")

