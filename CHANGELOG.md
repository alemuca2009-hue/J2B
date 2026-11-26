# Changelog

All notable changes to J2B Studio. Format follows [Keep a Changelog](https://keepachangelog.com/),
versioning is [semantic](https://semver.org/).

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
