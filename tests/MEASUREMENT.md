# Measurement harness status

This is an initial CSV benchmark, not the full competition measurement system.
No pipeline fixes were made while building it. Scores must not be used as evidence
that unimplemented formats or attack models pass.

## Commands

```powershell
python -m tests.gen --seed 1 --patients 300 --profile tune --out benchmark
python main.py --input benchmark/input --output benchmark/output
python -m tests.score --truth benchmark/truth --output benchmark/output
python -m tests.measure --out measurement-runs
```

`tests.measure` runs each dataset twice in a subprocess and compares bytes, excluding
timing/resources in the report. It discards subprocess stdout/stderr. Holdout
outputs are not printed; only scorecard aggregates are emitted. Templates were
frozen in commit 8d7ab01 before evaluation and are checked by SHA-256 in CI tests.

## Implemented

- Deterministic seeded generation, separate truth/input subtrees, disjoint pools,
  explicit coverage manifest, all seven truth artifact types.
- Namesakes, shared household phones, 2–3 hospital appearances, canary patient,
  standard CSV, malformed JSON and unsupported/binary/empty quarantine bait.
- Inventory recall grouped by type/surface/script; canary penalty deduplicated by
  value; medical-span survival, CSV LOS and age bands, pairwise linkage metrics,
  missing/null rate, CSV row/column checks, two-run determinism and reported resources.
- Restricted self-attack using age/sex/location/diagnosis; emitted limitations state
  that admission month/LOS and shift inference are not yet included.
- Scorer controls: raw copy privacy=0, delete-all approximately 17 total,
  repeated one-canary leakage penalized exactly once.
- Runtime open guard asserts no path containing `truth` is opened during the tested run.

## Not yet implemented

Configurable trap rates; full entity/script representation; twins/newborns,
doctor-patients, marriage/relative transitions, conflict oracles; JSON/FHIR/text
adversarial generation; full encodings/obfuscations; odd-surface canaries;
independent all-format date parser; FHIR R4 schema validation with fhir.resources;
metadata/event count reconciliation; logs/temp independent canary sweep semantics;
null-reason scoring; raw-copy penalties; month/season inference; six-category
calibration against the competition scoring function; prior-tag comparison;
unreported full regression fixture oracle set; worst-10 ranked failures.

The current 20-point-per-unique-canary penalty is a declared local benchmark
choice, not an organizer-supplied weight. The printed categories are provisional.
Holdout scores must not be inspected for examples or used for tuning.

Available hand-built fixtures: pasted YMC register (`t1`) and pasted family JSON.
Their automated regression tests pass in the 147-test suite. The ten original
first-set files remain unavailable. No numeric hand-built score is claimed.
