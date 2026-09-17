# Map foundation performance baseline

This document records development measurements for the current exporter. The
numbers are evidence for algorithm and memory decisions, not timing assertions
in the normal test suite. `peak_traced_bytes` is Python allocation measured by
`tracemalloc`; it is not the process resident-set size.

## Reproduce locally

Use an explicit output directory. The benchmark refuses to write into a
non-empty directory and removes its generated artifact afterward unless
`--keep-output` is supplied:

```powershell
python tools/benchmark_foundation.py `
  --project projects/Belgium_Map_v1_1.hoi4proj `
  --output-dir "$env:TEMP\hoi4-map-maker-foundation-benchmark" `
  --json-output "$env:TEMP\hoi4-map-maker-foundation-benchmark.json"
```

The measured stages are project loading, vectorized project statistics,
pre-export validation/repair analysis, the complete export, and the static MOD
verifier. The command is opt-in and is never collected by pytest.

## Belgium Map v1.1 capture

The repository contains the full-size project at
`projects/Belgium_Map_v1_1.hoi4proj` (5,632 × 2,048, 12,521 province IDs).
The capture below was run on 17 September 2026 from this checkout with the
local Python 3.13 environment and HOI4 1.19.3.0 assets. Run the command above
to refresh the machine-specific measurements. Do not commit generated MOD
files; commit only intentionally updated measurement values and methodology.

| Stage | Elapsed seconds | Peak traced bytes | Notes |
|---|---:|---:|---|
| project_load | 0.366 | 121,526,779 | reads the project archive |
| project_statistics | 0.567 | 196,485,760 | one-pass province/tile statistics |
| pre_export_check_and_fix | 24.312 | 196,184,584 | current repair-oriented precheck |
| export_full_mod | 26.098 | 537,283,559 | writes a disposable full artifact |
| mod_verifier | 0.467 | 5,410,936 | static post-export validation |

Measurements depend on Python, NumPy/SciPy, disk, and the selected game
installation. Compare runs on the same machine and game version.
