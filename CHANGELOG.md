# Changelog

All notable changes to J2B Studio. Format follows [Keep a Changelog](https://keepachangelog.com/),
versioning is [semantic](https://semver.org/).

## [1.2.1] — 2026-11-26

### Fixed
- **The Windows build failed on a good executable.** `build.yml` applied the `--onefile` size
  floor (3 MB) to the `--onedir` stub as well. A one-dir build ships a ~2 MB launcher and keeps
  the interpreter in `_internal\`, so the guard rejected a build that had just passed every
  self-test probe (one-file: 12.27 MB, 7/7 ok; portable: 2.06 MB, never got to run). Each kind
  now has its own floor and the portable folder is measured as a whole, with an explicit check
  that `_internal\` exists.

### Added
- **The self-test now converts a mod.** Every probe until now proved a module *imports* — the
  check that passes on a frozen build which cannot write a pack. The `conversion` probe builds
  the synthetic fixture jar, converts it inside the frozen process, and asserts a `.mcaddon`
  with block definitions was written to disk: `4 converted, 2 blocks, 10 KB bundle`. This is the
  probe that would have caught a missing `j2b/data` entry, not `import tkinter`.
- `j2b/fixtures.py` — the synthetic mod jar moved out of `tests/` into the package so the tests
  and the frozen executable convert the *same* fixture. `tests/make_test_jar.py` is now a shim
  that re-exports it.
- `tests/test_selftest.py` — 8 tests: a raising probe is recorded as a failure rather than
  crashing the process, an informational probe can never fail the run, an unwritable report
  path does not change the exit code, and a pipeline that produces no `.mcaddon` is caught.

### Changed
- **`CaseMemory` opens one connection per run instead of one per feature.** Each `record()` used
  `with self._connect()`, and `sqlite3.Connection.__exit__` commits but does not close — so a
  Create conversion (2 890 features) leaked a file handle per feature and paid one fsync each.
  Rows are now buffered and written by `flush()` in a single transaction (WAL,
  `synchronous=NORMAL`), with an automatic flush every 500 rows so a long run stays bounded.
  `stats()` counts buffered rows, so it no longer reports 0 cases mid-run.

## [1.2.0] — 2026-11-26

### Added
- **Composite rotation composition** (`j2b/converters/rotation.py`). A model whose element is
  tilted *and* whose blockstate turns it now keeps both. The two rotations collapse into one
  (`compose`), the quarter-turn part of it is folded into the box's corners and face names
  (`bake_box`), and the fractional part is handed to Bedrock as a `rotation` about the pivot it
  really turns around. Previously the element rotation was discarded and the block came out flat.
- `split_permutation` — writes any rotation a blockstate can build as `permutation · single-axis
  turn`, which is exactly what Bedrock's cube format can hold. The permutation with the smallest
  residual angle wins, so the geometry stays readable (a 90° facing keeps its quarter turn baked
  and only the authored 22.5° tilt survives as a rotation).
- `as_coordinate_rotation`, `best_coordinate_rotation`, `rotation_angle` — matrix introspection,
  including a measured error in degrees for the one case Bedrock cannot express.
- `tests/test_composite_rotation.py` — 20 tests pinning composition order, fixed points,
  permutation splitting, baked corners against the true transform, and the annotated
  unrepresentable case.

### Changed
- `variants.rotate_elements` now composes element rotations instead of stashing and dropping them.
- A fluid-only machine recipe is reported as a `warning` (`RECIPE_FLUID_ONLY`) instead of an
  `error`. Nothing invalid was reaching the pack, so the validator was calling a clean add-on
  broken. Create 6.0.10 now converts with **0 validation errors**.

### Measured
Create 6.0.10 / MC 1.21.1, end to end: estimated fidelity `0.541 → 0.5435`, validation errors
`1 → 0`, all 99 tests and 256 subtests green.

## [1.1.0]
- First published state: analyzer, converters (blocks, items, recipes, worldgen, entities,
  geometry, machines, variants, pack writer), knowledge base, validation, history, report,
  CLI and tkinter GUI.
