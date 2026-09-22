# HOI4 MOD troubleshooting and acceptance testing

When a MOD fails to load, start with the first useful error rather than the last message. One malformed definition can create a cascade of missing IDs, so the final line is often only a symptom.

## Debug launch and log files

Launch the selected game with the debug options relevant to the failure:

```text
hoi4.exe -debug -crash_data_log
```

`-debug` enables additional diagnostics and console/testing behavior. `-crash_data_log` adds crash-read information such as `LastRead`. `LastRead` identifies the last item successfully read; the invalid entry may be immediately after it, so inspect the surrounding file and the first error in `error.log`.

The game normally writes logs below:

```text
Documents/Paradox Interactive/Hearts of Iron IV/logs/
```

| File | Start here for |
| --- | --- |
| `error.log` | Parser, map, asset, definition, and runtime errors |
| `exceptions.log` | Exception details; corroborate with the other logs |
| `setup.log` | Map/database setup and initialization progress |
| `game.log` | In-game triggers, effects, country behavior, and setup messages |
| `graphics.log` | Graphics and renderer asset problems |
| `memory.log` | Memory and loading diagnostics |
| `text.log` | Localization and text-parser diagnostics |
| `time.log` | Timing information during loading and processing |

Move or archive old logs before a test run. A stale log is not evidence that the current export reached the same stage.

## Common failures

| Symptom | First checks |
| --- | --- |
| Crash while loading the menu | MOD root, descriptor path, replacement directories, BMP dimensions/bit depth/compression, and `default.map` references |
| Provinces have wrong terrain or ownership | `definition.csv` colors, province IDs, state lists, continent assignments, and state history |
| Coastal state, port, or naval base failure | Coastline geometry, `coastal` metadata, port position, adjacent sea province, and `buildings.txt` |
| Supply or railway failure | Final province/state IDs, railway neighbor order, network levels, supply-node references, and disconnected components |
| Map reaches the menu but a new game fails | State owners, capitals, strategic-region coverage, OOBs, country tags, and first-tick script errors |
| Text appears as a raw key | `l_english:` header, UTF-8 BOM, language filename token, exact key spelling, and `text.log` |
| Empty or missing focus/decision/event UI | Script path, duplicate ID, localization key, icon/sprite definition, and referenced image |
| A vanilla definition unexpectedly disappears | `replace_path`, load order, dependencies, and whether the MOD actually contains the replacement directory |

## Map-specific triage

For a map crash, validate in this order:

1. the MOD descriptor points to the intended root and the game version matches the export profile;
2. `default.map` points to files that exist and uses the target version's key names;
3. `provinces.bmp`, `definition.csv`, `continent.txt`, and state province lists agree exactly;
4. height, terrain, river, tree, normal, color-map, and atlas assets satisfy their dimensions and encoding contracts;
5. state IDs, strategic-region IDs, supply nodes, railways, adjacencies, buildings, ports, and positions use final IDs;
6. country tags and history are unique and every state has a valid owner/capital for the test scenario;
7. the map starts, ticks, saves, reloads, and reaches the first gameplay map modes without new errors.

The project's static verifier is useful for deterministic file and reference checks, but it cannot prove that the selected HOI4 executable accepts the export. An engine run with isolated logs is a separate acceptance gate.

## Replacement paths and inherited content

`replace_path` is a common source of apparently unrelated errors. It unloads files directly in the named directory during menu loading; it does not recursively replace every child directory, and it does not change ordinary load order. A full-conversion exporter must either provide a complete replacement directory or leave that directory inherited. Keep the decision in the export manifest and test with dependencies enabled.

When the exporter imports a MOD, distinguish files that are generated, preserved from the source, inherited from vanilla/dependencies, intentionally omitted, or unsupported. An empty compatibility file can be worse than a deliberate omission when the selected version no longer reads that file.

## Useful console checks

These commands help isolate a loaded-game problem:

| Command | Purpose |
| --- | --- |
| `tdebug` | Show state, province, country, and other debug IDs |
| `tag TAG` | Switch the active country |
| `ai` | Toggle AI while isolating AI-triggered behavior |
| `reload localization` | Reload localization after editing `.yml` files |
| `reloadfx all` | Reload visual effects during asset work |
| `Focus.NoChecks` | Ignore focus prerequisites during testing |
| `Focus.AutoComplete` | Complete focuses immediately during testing |

Use console commands only to diagnose a reproducible test case; they do not replace a clean new-game acceptance run.

## Acceptance run

For a generated MOD, record the game executable/profile and run an isolated test with:

- a fresh log directory and unique test country tags;
- the main menu and new-game setup;
- a 1936 start (or the selected bookmark) and at least 30 days of ticking;
- map modes, land/naval/air interactions, supply, and at least one generated script path;
- save, reload, and additional ticking;
- a final scan of `error.log`, `exceptions.log`, `text.log`, and relevant setup/game logs.

Record the result in the export manifest. “The menu opened” is a useful milestone, not proof of a playable MOD.

## Finding codes and the assisted harness

The planner and artifact verifier use stable finding-code families so the same
problem can be triaged in the GUI, CLI JSON report, and documentation:

| Finding family | Typical examples | First action |
| --- | --- | --- |
| `map.*`, `province.*`, `raster.*` | dimensions, empty IDs, mixed province types | inspect the raster and selected game profile |
| `state.*`, `region.*`, `adjacency.*` | missing membership, disconnected region, unreviewed strait | review geography/topology and rerun the relevant validator |
| `logistics.*` | invalid railway endpoint, disconnected supply component | inspect graph components and record an intentional exception only when justified |
| `placement.*` | generated fallback, out-of-province coordinate, missing port sea link | replace or accept the authored placement in the review UI |
| `asset.*`, `export.*` | unsupported format, missing output owner, staged artifact mismatch | inspect the manifest's resolution/provenance and target contract |
| `engine.*`, `acceptance.*` | stale log, tag collision, map-load error | rerun the isolated acceptance harness with fresh logs |

The assisted harness is deliberately conservative. It launches only the
selected executable, uses a unique run directory, captures fresh logs, and
binds the result to the artifact manifest identity. A successful process exit
without the required start/tick/save/reload evidence is not a pass. Use the
M7 CLI tool to inspect or run the checklist, then use
`tools/foundation_freeze.py record-acceptance` only for a successful record
whose foundation source identity matches the frozen foundation.

For an executed run, `error.log` is required by default. It must be readable
and observably created, rewritten, or extended after the pre-run snapshot;
missing, stale, or unreadable evidence fails the run. Every nonblank fresh
`error.log` line is classified as error evidence. Messages may be marked
non-blocking only when their category is known, and optional-DLC messages are
downgraded only when a complete fresh `system.log` active-DLC list proves the
owning DLC is inactive. `--allow-non-error-log-set` is an explicit diagnostic
escape hatch, not a release-acceptance path.

Use `--activate-artifact --hoi4-user-dir <directory>` for an exact direct-run
test. The harness temporarily stages the artifact descriptor, enables only
that descriptor in `dlc_load.json`, requires fresh `system.log` proof that
exactly one matching mod loaded, and restores the original files after the
game exits. It refuses symbolic-link collisions, concurrent changes, and
command-line `-mod` overrides instead of risking an ambiguous test.

The expected save name is also evidence: every requested save must be fresh,
and save/checklist failures are reported alongside launch or log blockers
rather than being hidden by the first failure. For the naval check, create a
convoy-backed naval-invasion route with the generated land division; merely
opening the naval map mode is not sufficient.

When a required interaction is genuinely unavailable in the isolated
scenario, record it with `--waive-check ID=REASON`; do not mark it checked.
Waivers are identity-attested, remain visible in the JSON and CLI summary, and
need a non-empty reason. A completed assisted result can be corrected without
changing captured launch/log/save evidence by using
`--amend-checklist <engine_acceptance.json>`; the command writes a sibling
`-amended.json` file and refuses to overwrite the original.

Foundation and acceptance exports have distinct artifact identities because
their profiles and file sets differ. Their shared source is bound separately
through `foundation_source_identity`, derived from target identity, project,
map size, and source hashes. Older acceptance results can be attached only
with `--acceptance-manifest`; the freeze service verifies that manifest's
exact size and SHA-256 against the inventory captured during the run before
deriving the shared identity.

Candidate and freeze commands do not trust the validation context embedded by
an earlier draft export. They re-evaluate the manifest's captured findings as
`foundation_candidate` and `freeze`; warnings that are visible but permitted
for a candidate can therefore still stop the final freeze. In particular,
missing or unreviewed province slots and weather positions must be completed
through the placement review workflow rather than hidden by a draft gate.

Before a successful acceptance report is attached, the freeze service
recomputes its identity hash, run ID, checklist and log summaries, and final
status from the captured evidence. The resulting lock and handoff retain the
exact report SHA-256, creation time, checked/waived counts, every waiver
reason, and both the shared source digest and algorithm. Editing a report's
top-level status or checklist by hand is rejected; use `--amend-checklist` so
the attestation and derived fields are rebuilt consistently.

### Steam and the Paradox launcher

The current Windows Steam entry for HOI4 starts `dowser.exe`, which opens the
Paradox launcher before it starts `hoi4.exe`. The assisted harness therefore
does not treat a successful `steam.exe` helper exit as a game launch: Steam
mode waits for a new `hoi4.exe` process and records whether `Paradox
Launcher.exe` is open while waiting.

Use the Steam path when a human will click **Play** in the launcher:

```text
python tools/run_engine_acceptance.py \
  --artifact-dir out/acceptance \
  --target "C:/Program Files (x86)/Steam/steamapps/common/Hearts of Iron IV" \
  --launch-via steam --execute
```

For an unattended acceptance run, use the direct game executable. The
`--skip-launcher` switch resolves `hoi4.exe` below `--target`; it does not
pretend that passing `-nolauncher` to the current Steam `dowser.exe` command
selected a different Steam launch entry:

```text
python tools/run_engine_acceptance.py \
  --artifact-dir out/acceptance \
  --target "C:/Program Files (x86)/Steam/steamapps/common/Hearts of Iron IV" \
  --launch-via steam --skip-launcher \
  --activate-artifact \
  --hoi4-user-dir "C:/Users/<you>/Documents/Paradox Interactive/Hearts of Iron IV" \
  --log-dir "C:/Users/<you>/Documents/Paradox Interactive/Hearts of Iron IV/logs" \
  --save-dir "C:/Users/<you>/Documents/Paradox Interactive/Hearts of Iron IV/save games" \
  --save-name m10_acceptance.hoi4 \
  --execute
```

If the launcher is left open, the harness reports that state and the missing
HOI4 process instead of calling the run a generic timeout or acceptance.

For a foundation change, compare the new manifest before rerunning content:

```text
python tools/foundation_freeze.py compare \
  --manifest out/new-foundation/foundation_manifest.json \
  --lock out/frozen/foundation.lock.json
```

Breaking identity, topology, foundation-visual, or placement differences
require a candidate review and a new acceptance run. Non-foundation content
changes may be handled independently when the comparison reports them as
non-breaking.

For a legacy successful acceptance result that predates embedded source
identity, freeze only with the unchanged captured acceptance manifest:

```text
python tools/foundation_freeze.py freeze \
  --manifest out/foundation/foundation_manifest.json \
  --artifact-dir out/foundation \
  --lock out/foundation/foundation.lock.json \
  --acceptance out/engine_acceptance-amended.json \
  --acceptance-manifest out/acceptance/foundation_manifest.json \
  --handoff out/foundation/FOUNDATION-HANDOFF.md
```

## Sources

- [HOI4 Troubleshooting](https://hoi4.paradoxwikis.com/Troubleshooting)
- [HOI4 Modding](https://hoi4.paradoxwikis.com/Modding)
- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
- [HOI4 Localisation](https://hoi4.paradoxwikis.com/Localisation)
- [Troubleshooting reference mirror](https://github.com/thelight0211/hoi4-wiki/blob/main/Troubleshooting%20-%20Hearts%20of%20Iron%204%20Wiki.md)
