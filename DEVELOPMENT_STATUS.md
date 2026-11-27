# Development status

Continue-from-here file. If a session ends, this is the first thing to read.

**Base release:** v1.4.1 (`2447d67`). The release includes the Windows executable and portable ZIP.
**Working branch:** `feature/geckolib-entity-animations`

## P1 animation

Resource resolution update on the same branch fixes child-over-parent precedence and unqualified
parent namespaces, restricts vanilla templates to Minecraft, and registers borrowed textures with
official atlas paths. Reference jars/ZIPs now supply PNGs as well as models, accessible in the GUI
and through `--reference`. Mod assets have priority. Four regression tests cover inheritance,
missing custom models, reference pixel copying and item textures used on blocks.
Validation after these changes is 180 tests and 288 subtests. In-game visual checks remain pending.
The executable committed at the repository root predates these source changes and remains under
the Defender investigation documented in `Windows-Defender-Fix`.

The scanner finds `*.animation.json` under each asset namespace and reports each named clip
separately. The output path and identifier are in the report. The client entity still needs a
binding and playback conditions. The converter preserves supported position, rotation and scale
tracks, numeric keyframes and a shared subset of MoLang. A custom curve falls back to linear
interpolation. An unsupported expression drops its channel and the report identifies the loss.

Position values stay in model units. GeckoLib's keyframe loader reads them directly, and its
renderer divides by 16 when applying the translation to the render matrix. Both source links
are pinned in the animation knowledge entry.

**Verification:** 176 tests and 288 subtests pass on Python 3.12. The entity resources in
[GeckoLib's 1.21.1 examples](https://github.com/bernie-g/geckolib-examples/tree/841c1ee4584d65033fa04bf07d4535aafcadd015/common/src/main/resources/assets/examplemod/animations/entity)
contain 52 clips. Converting those files produced 41 exact clip definitions, 10 approximate ones
and one skipped empty source. All 51 definitions read back from the bundled `.mcaddon` passed
[Blockception's actor animation schema](https://github.com/Blockception/Minecraft-bedrock-json-schemas/blob/af82975a5b25d64373e4a4c5fd4d76c2ff774fa5/resource/animations/actor_animation.json).
These checks cover exported data. In-game playback has not been tested.

## Last changes (1.4.1)

`tests/test_geometry_blockbench_oracle.py` pins cube origin, size, pivot and rotation to
Blockbench's compiler. The earlier vertex harness used an assumed Bedrock transform and its
numerical fidelity results were withdrawn.

## Last changes (1.4.0)

| Area | What |
| --- | --- |
| `j2b/converters/sounds.py` | New. `sounds.json` → `sound_definitions.json`, `.ogg` copied to `sounds/`, identifiers rewritten to file paths, categories mapped onto Bedrock's enum. |
| `j2b/analyzer/feature_scan.py` | `_scan_sounds`: one `sound` feature per namespace, bare-string and object entries normalised to one shape. |
| `j2b/converters/geometry.py` | `element_rescale` / `apply_rescale`: Java `rescale` folded into the box bounds about the rotation origin. |
| `j2b/converters/blocks.py` | Rescale applied before the variant rotation is baked, so both agree on the point they scale about. |
| `tests/test_sounds.py` | New. |
| `j2b/fixtures.py` | The fixture jar now ships `sounds.json`, three `.ogg` files and a rotated+rescaled block, so sound and rescale are covered end to end rather than only in unit tests. |
| `tests/test_geometry.py` | `RescaleTests`: origin anchor, UVs untouched, idempotence, nonsense factors, survival of variant baking. |

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
2. **Java element rescale** is folded into the box bounds about the authored rotation origin.
3. **Rotated cubes get no AO.** Shading is computed from the unrotated box. Format limitation.
4. **Collision boxes** are not claimed for rotated cubes (they are not axis-aligned).
5. **Cylinders / free polygons** from Create and Valkyrien are not converted.
6. **Machines lose kinetic behaviour** (stress, speed, processing time, chance byproducts).
7. **Entity behaviour** still requires a manual Bedrock definition and playback controller.

## Next task

The remaining P1 item in `ROADMAP.md` is handheld item models and display transforms.
P2 tracks parallel conversion.

## Rules this repo follows

- GitHub is the source of truth. Nothing of value lives only in a working copy.
- Never claim a change is published without checking the tree on the remote.
- A number in the README is measured, never estimated.
