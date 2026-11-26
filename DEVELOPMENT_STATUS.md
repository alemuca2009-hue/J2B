# Development status

Continue-from-here file. If a session ends, this is the first thing to read.

**Version:** 1.2.1
**Branch:** `main`
**Tests:** 116 tests, 256 subtests — all green (`python -m pytest -q`, ~0.3 s)
**Windows build:** workflow runs on `windows-latest`; the one-file exe passed all probes on run 45878175282, the run failed on a bogus size guard for the portable stub — fixed in 1.2.1, re-running

## Last changes

| Area | What |
| --- | --- |
| `j2b/knowledge/base.py` | `CaseMemory` keeps one connection per run and buffers rows into a single transaction. 2 890 leaked handles and 2 890 fsyncs per Create conversion are gone. |
| `j2b/selftest.py` | New `conversion` probe: the frozen exe converts the fixture jar and must produce a `.mcaddon` with blocks. Imports were the wrong thing to test. |
| `j2b/fixtures.py` | Synthetic mod jar moved into the package so the exe self-test and the test suite convert the same jar. |
| `tests/test_selftest.py` | New. 8 tests. |
| `.github/workflows/build.yml` | Per-kind size floors; portable folder measured as a whole; `_internal\` presence enforced. |


| Area | What |
| --- | --- |
| `j2b/converters/rotation.py` | New. Rotation algebra: composition, fixed points, signed-permutation splitting, box baking. |
| `j2b/converters/variants.py` | `rotate_elements` composes element rotations with blockstate rotations instead of dropping them. |
| `j2b/converters/recipes.py` | Fluid-only machine recipe: `error` → `warning` (`RECIPE_FLUID_ONLY`). |
| `tests/test_composite_rotation.py` | New. 20 tests. |
| Docs | `CHANGELOG.md`, `ROADMAP.md`, `DEVELOPMENT_STATUS.md` added. |

## Measured on the real mod

Create 6.0.10 for MC 1.21.1 (`create-1.21.1-6.0.10.jar`), full conversion, ~9.6 s:

| metric | 1.1.0 | 1.2.0 |
| --- | --- | --- |
| estimated fidelity | 0.541 | 0.5435 |
| validation errors | 1 | 0 |
| blocks converted / partial | 170 / 473 | 170 / 473 |
| recipes converted / partial / unsupported | 466 / 863 / 551 | 466 / 863 / 551 |
| features detected | 2 890 | 2 890 |

The fidelity number moves little because only blocks that combine an element rotation with a
blockstate rotation were affected — but those were wrong before in a way that is invisible in a
JSON diff and obvious in game (a tilted cog rendered flat).

## Known limitations (honest list)

1. **Two arbitrary angles at different points** cannot be expressed in Bedrock's single-axis cube
   rotation. `best_coordinate_rotation` picks the nearest turn and reports the error in degrees.
   No blockstate in a normal mod produces this — a quarter turn * a single-axis tilt always splits.
2. **`rescale`** on a Java element has no Bedrock equivalent; the cube keeps its authored size.
3. **Rotated cubes get no AO.** Ambient occlusion is computed from the unrotated box, so shading
   of fractional-angle cubes looks flat. Nothing can be done from the format side.
4. **Collision boxes** are not claimed for rotated cubes (they are not axis-aligned).
5. **Machines lose kinetic behaviour** (stress, speed, processing time, chance byproducts).
   Documented per recipe, never invented.

## Next task

`ROADMAP.md` → **P0: Windows executable**. The PyInstaller spec exists
(`packaging/j2b.spec`); the missing piece is `.github/workflows/build.yml` running on
`windows-latest`, uploading `dist/J2BStudio.exe` to a GitHub Release.

After that: `P1: audio/animation`, `P1: entity model translation`, `P2: recipe fidelity`.

## Rules this repo follows

- GitHub is the source of truth. Nothing of value lives only in a working copy.
- Never claim a change is published without checking the tree on the remote.
- A number in the README is measured, never estimated.
