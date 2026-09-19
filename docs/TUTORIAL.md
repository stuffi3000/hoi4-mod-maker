# HOI4 Map Maker 1.4.0 tutorial

This tutorial covers the normal editor workflow and the map-foundation release
workflow. The application and generated messages are English-only.

## The complete workflow

```text
draft project -> validate and author -> candidate export -> acceptance mod
    -> freeze exact foundation -> hand off to content developers
```

The first four steps are ordinary map editing. The last three protect province
IDs, state geography, topology, placements, and map-owned assets before
scenario content is built on top of them.

## 1. Create a project and draw the map

1. Start the application and choose **New Project**.
2. Choose dimensions that are valid for the selected HOI4 profile. The Belgium
   target uses 5,632 x 2,048.
3. In **Draw Map**, paint land, sea, and lakes. A reference image can be
   imported for tracing; the reference layer is separate from the editable
   map.
4. Save the project as a `.hoi4proj` archive.

Keep the project in `draft` while the raster is changing. Do not use an
exported province ID as a permanent content reference yet.

## 2. Generate and refine provinces

Open **Provinces** and choose the generation scope and density. Sea and lake
density can be adjusted independently. After generation:

- use **Validate** to find tiny, disconnected, or invalid provinces;
- use **Merge**, **Split**, **Lasso**, or the province brush for authored edits;
- rerun validation after each structural change;
- save before a large repair or regeneration operation.

Province IDs are foundation data. A later merge, split, or compaction can
require a reference migration for states, regions, buildings, positions,
railways, supply nodes, and scripts.

## 3. Generate height, terrain, and rivers

Use **Height** to generate or refine elevation, then use **Terrain** to assign
graphical terrain. Gameplay terrain in `definition.csv` and graphical terrain
in `terrain.bmp` are separate layers; review both before freezing. Use
**Rivers** for authored river paths and run the river validator before export.

## 4. Author states, regions, adjacencies, and logistics

Use the editor pages to create and review:

- state membership and state categories;
- continent and strategic-region coverage;
- special adjacencies and adjacency rules;
- railway routes, supply nodes, and disconnected-component exceptions;
- authored province slots, ports, buildings, unit stacks, and weather positions.

Generated proposals are marked as generated/fallback and remain unreviewed
until accepted. A foundation export must not silently turn a centroid or
network proposal into authoritative content.

## 5. Choose an export profile

The export dialog and `cli_export.py` expose the same profiles:

| Profile | Use it for | Content boundary |
| --- | --- | --- |
| `foundation` | map package and candidate/frozen artifact | map-owned layers and geography; no country scenario content |
| `acceptance` | disposable engine test | foundation plus collision-free test countries and history |
| `scaffold` | optional playable starting point | generated gameplay helpers, explicitly outside the foundation lock |
| `legacy_full` | migration compatibility | the pre-staged exporter behavior while callers migrate |

For a normal staged export, use the CLI like this:

```text
python cli_export.py projects/Belgium_Map_v1_1.hoi4proj out/belgium-foundation \
  --profile foundation --game-dir "C:/Program Files (x86)/Steam/steamapps/common/Hearts of Iron IV"
```

The planner snapshots the project, reports repairs and findings, writes to a
fresh staging directory, validates the artifact, and only then promotes it.
The live project is not the export working copy.

## 6. Candidate, frozen, and accepted lifecycle

Use `draft` while map data is changing. A `candidate` is a reviewed export
that is ready for exact-artifact checks. A `frozen` lock prohibits implicit
ID/topology/classification repairs. An `accepted` artifact has a successful
engine record tied to the same manifest and lock identity.

Create and freeze a lock only from the exact exported artifact:

```text
python tools/foundation_freeze.py candidate \
  --manifest out/belgium-foundation/foundation_manifest.json \
  --artifact-dir out/belgium-foundation \
  --lock out/belgium-foundation/foundation.lock.json

python tools/foundation_freeze.py freeze \
  --manifest out/belgium-foundation/foundation_manifest.json \
  --artifact-dir out/belgium-foundation \
  --lock out/belgium-foundation/foundation.lock.json
```

Run the `acceptance` profile and the M7 harness for an in-game start, tick,
save, reload, and map-mode check. Then attach the exact successful record:

```text
python tools/foundation_freeze.py record-acceptance \
  --manifest out/belgium-foundation/foundation_manifest.json \
  --lock out/belgium-foundation/foundation.lock.json \
  --acceptance out/belgium-acceptance/engine_acceptance.json
```

Compare every later foundation export before content work continues:

```text
python tools/foundation_freeze.py compare \
  --manifest out/new-foundation/foundation_manifest.json \
  --lock out/belgium-foundation/foundation.lock.json
```

If a map change is intentional, unfreeze with a reason, review the breaking
change report, and repeat candidate validation. Do not edit a frozen lock by
hand.

## 7. Content handoff

The foundation package contains `foundation_manifest.json`,
`foundation_report.md`, `foundation.lock.json`, and `FOUNDATION-HANDOFF.md`.
Content developers may add owners, countries, focuses, events, equipment,
balance, and narrative without rerunning the map generator. They must not
change locked raster pixels, province IDs, state membership, topology, or
foundation-owned assets without a new migration review.

## Troubleshooting

Use the first meaningful finding in the shared validation report, not the last
line in a cascading game log. For engine work, archive fresh `error.log`,
`setup.log`, `game.log`, `text.log`, `graphics.log`, and `exceptions.log`.
See [the troubleshooting guide](wiki/troubleshooting.md) for finding codes,
replacement-path checks, and the assisted acceptance harness.

Legacy `.hoi4proj` archives remain loadable without `project_meta.json`; they
start as `draft`. Existing `_manifest.txt` asset sidecars are still read.
When an old caller passes a `scope` dictionary, the exporter translates it to
`legacy_full` and emits a deprecation warning. Migrate new integrations to
the profile/planner API.
