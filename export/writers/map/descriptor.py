"""descriptor.mod writes."""
import os
from data.constants import DEFAULT_MOD_VERSION, REPLACE_PATHS
from services.game_assets import resolve_supported_version


def write_descriptor(mod_name, output_dir, supported_version=None, game_target=None,
                     replace_paths=None, write_outer=True):
    rp = "\n".join(f'replace_path="{p}"' for p in (list(replace_paths) if replace_paths is not None else list(REPLACE_PATHS)))
    # Automatically follow the local game version (the export will not be marked "outdated" by the launcher after the game is updated)
    if supported_version is not None:
        supported = str(supported_version)
    elif game_target is not None and getattr(game_target, "supported_version", None):
        supported = str(game_target.supported_version)
    else:
        supported = resolve_supported_version(game_target)

    # Internal descriptor.mod (in MOD directory)
    with open(os.path.join(output_dir, "descriptor.mod"), "w", encoding="utf-8") as f:
        f.write(f'version="{DEFAULT_MOD_VERSION}"\n')
        f.write('tags={\n\t"Alternative History"\n\t"Map"\n\t"Total Conversion"\n}\n')
        f.write(f'name="{mod_name}"\n')
        f.write(f'supported_version="{supported}"\n')
        f.write(rp + "\n")

    if write_outer:
        # Outer .mod file (next to the MOD directory, required by the launcher).
        # Staged exports defer this sidecar until the directory is promoted so a
        # failed write can never leave a misleading launcher entry behind.
        mod_dir_name = os.path.basename(output_dir)
        outer_mod = os.path.join(os.path.dirname(output_dir), f"{mod_dir_name}.mod")
        with open(outer_mod, "w", encoding="utf-8") as f:
            f.write(f'version="{DEFAULT_MOD_VERSION}"\n')
            f.write('tags={\n\t"Alternative History"\n\t"Map"\n\t"Total Conversion"\n}\n')
            f.write(f'name="{mod_name}"\n')
            f.write(f'supported_version="{supported}"\n')
            # Use forward slash for path.
            abs_path = os.path.abspath(output_dir).replace("\\", "/")
            f.write(f'path="{abs_path}"\n')
            f.write(rp + "\n")

