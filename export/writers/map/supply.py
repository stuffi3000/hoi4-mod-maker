"""supply_nodes.txt / railways.txt / supply_areas/*.txt."""
import os
import numpy as np


def write_supply_nodes(states, province_map, output_dir):
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "supply_nodes.txt"), "w", encoding="utf-8") as f:
        # Place a supply node every 5 states by index
        state_list = [(sid, provs) for sid, provs in states.items() if provs]
        written = False
        for i, (sid, provs) in enumerate(state_list):
            if i % 5 == 0:
                f.write(f"1 {provs[0]}\n")
                written = True
        if not written and state_list:
            f.write(f"1 {state_list[0][1][0]}\n")
            written = True
        if not written:
            # The file cannot be empty and comments cannot be written. Write a placeholder node.
            f.write("1 1\n")


def write_railways(states, province_map, output_dir):
    """fallback: When there is no user railway data, write the minimum occupancy."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    fallback_pid = 1
    for sid, provs in states.items():
        if provs:
            fallback_pid = provs[0]
            break
    with open(os.path.join(d, "railways.txt"), "w", encoding="utf-8") as f:
        f.write(f"1 2 {fallback_pid} {fallback_pid}\n")


def write_supply_areas(states, output_dir, states_per_area: int = 15):
    """Write map/supplyareas/*.txt, each supply area contains states_per_area states.

    HOI4 requires each state to belong to a supply_area, otherwise an error will be reported.
    Sort all states by ID and then group them, and write one file for each group."""
    d = os.path.join(output_dir, "map", "supplyareas")
    os.makedirs(d, exist_ok=True)

    state_ids = sorted(states.keys())
    if not state_ids:
        # Write at least one empty supply area file to avoid the directory being empty
        with open(os.path.join(d, "1-SupplyArea.txt"), "w", encoding="utf-8") as f:
            f.write("supply_area={\n\tid=1\n")
            f.write('\tname="SUPPLYAREA_WT_1"\n\tvalue=1\n')
            f.write("\tstates={\n\t\t1\n\t}\n}\n")
        return

    # Group by states_per_area
    area_id = 0
    for i in range(0, len(state_ids), states_per_area):
        area_id += 1
        chunk = state_ids[i:i + states_per_area]
        # The value scales with the number of states (1-10), and areas with more states give higher supply values.
        value = max(1, min(10, len(chunk)))
        with open(os.path.join(d, f"{area_id}-SupplyArea.txt"), "w", encoding="utf-8") as f:
            f.write("supply_area={\n")
            f.write(f"\tid={area_id}\n")
            f.write(f'\tname="SUPPLYAREA_WT_{area_id}"\n')
            f.write(f"\tvalue={value}\n")
            f.write("\tstates={\n\t\t")
            f.write(" ".join(str(s) for s in chunk))
            f.write("\n\t}\n}\n")

