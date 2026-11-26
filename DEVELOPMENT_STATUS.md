# Development status

Continue-from-here file. If a session ends, this is the first thing to read.

**Version:** 1.3.0
**Branch:** `main`
**Tests:** 136 tests, 259 subtests — all green (`python -m pytest -q`, ~0.4 s)
**Windows build:** workflow green on `windows-latest` (run 45880077117, v1.2.1). One-file exe
12.2 MB and portable folder both passed every self-test probe, including a conversion run inside
the frozen process. Artifacts are on the run; v1.3.0 is the first tag cut with the geometry fix.

## Last changes (1.3.0)

| Area | What |
| --- | --- |
| `j2b/converters/geometry.py` | X mirror (`origin.x = 8 - to.x`, `pivot.x = 8 - origin.x`), rotation negated on X/Y and kept on Z. Every asymmetric model was flipped east to west before this. |
| `j2b/converters/entity_models.py` | New. GeckoLib passthrough, `.bbmodel` outliner → bones, identifier rewriting, `cube`→`cubes` for GeckoLib 2. |
| `j2b/converters/entities.py` | Entities with a model are `partial` 0.5 and write real geometry; entities without stay `manual` 0.15. |
| `j2b/analyzer/feature_scan.py` | `_entity_models` + `_match_models`: collects `.geo.json`/`.bbmodel` from anywhere under `assets/` and matches by filename. |
| `j2b/knowledge/base.py` | `CaseMemory` one connection per run, single transaction. Was 2 890 connections and fsyncs per Create conversion. |
| `tests/test_geometry.py` | New `BedrockMirrorConventionTests` pinning the convention to vanilla `block/cross` as Blockbench exports it. |
| `tests/test_entity_models.py` | New. 17 tests. |

## The mirror bug, in one paragraph

Bedrock block geometry is defined in a space that mirrors X relative to Java's. J2B applied only
the `-8` centring shift, so every model was mirrored east to west -- but only asymmetric ones
showed it, which is exactly why a bug this large sat unnoticed: a pillar, a casing, a full cube
are all symmetric and look perfect. The rules now implemented come from Blockbench
`compileCube`/`compileGroup`, GeyserMC PackConverter `ModelConverter`, Kas-tle `java2bedrock.sh`
and `mc-model-geo`; all four agree, and `mc-model-geo` ships a game-verified golden.

## Measured on the real mod

Create 6.0.10 for MC 1.21.1 (`create-1.21.1-6.0.10.jar`), full conversion, ~5.6 s:

| metric | 1.2.1 | 1.3.0 |
| --- | --- | --- |
| estimated fidelity | 54.35% | 54.4% |
| validation errors | 0 | 0 |
| features | 2 890 | 2 890 |
| converted / partial / manual / unsupported | 805 / 1353 / 133 / 596 | 805 / 1353 / 133 / 596 |

Fidelity barely moves because the fix is a coordinate sign, not extra content -- the models it
corrects were already counted as converted. That is the point: this was a silent wrongness, not
a missing feature.

## Known limitations (honest list)

1. **Two arbitrary angles at different points** cannot be expressed in Bedrock's single-axis cube
   rotation. `best_coordinate_rotation` picks the nearest turn and reports the error in degrees.
2. **`rescale`** on a Java element has no Bedrock equivalent; the cube keeps its authored size.
3. **Rotated cubes get no AO.** Shading is computed from the unrotated box. Format limitation.
4. **Collision boxes** are not claimed for rotated cubes (they are not axis-aligned).
5. **Cylinders / free polygons** from Create and Valkyrien are not converted.
6. **Machines lose kinetic behaviour** (stress, speed, processing time, chance byproducts).
7. **Entity behaviour** is not converted: geometry and texture only.

## Next task

`ROADMAP.md` → **P1: audio**. `sounds.json` + `.ogg` → `sound_definitions.json` + `sounds/`
is the largest remaining chunk of fidelity that is fully mechanical -- no guessing, no
approximation. Then P1 animation, then P2 parallel conversion.

## Rules this repo follows

- GitHub is the source of truth. Nothing of value lives only in a working copy.
- Never claim a change is published without checking the tree on the remote.
- A number in the README is measured, never estimated.
