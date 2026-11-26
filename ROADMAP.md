# Roadmap

Ordered by what blocks a usable release, then by how much fidelity each item buys.

## P0 — Windows executable

- [x] `.github/workflows/build.yml`: `windows-latest`, Python 3.10/3.12 matrix, `pyinstaller`,
      upload `dist/J2BStudio.exe` as an artifact and to a Release on tag `v*`.
- [x] Verify the frozen exe starts without Python: tkinter present, knowledge data bundled,
      `sys._MEIPASS` paths resolved. The self-test runs *inside* the frozen process and
      converts a mod, so an import that only works from source cannot pass it.
- [x] Portable build (`--onedir`) next to the one-file exe — one-file unpacks to `%TEMP%` on
      every launch, which is slow for a 9 s conversion.
- [ ] Version resource stamped into the exe (`--version-file`).

## P1 — Content fidelity

- [x] **Entity models.** Java `geo`/`bbmodel` → Bedrock `geometry` with bones. Done in 1.3.0:
      GeckoLib passthrough, `.bbmodel` outliner → bones, models matched to entities by filename.
- [ ] **Animations.** Java `.json` entity animations → Bedrock `animations` block. Keyframe and
      molang translation; partial coverage is fine if each animation is marked exact/approximate.
- [x] **Audio.** `sounds.json` + `.ogg` → `sound_definitions.json` + `sounds/`. Done in 1.4.0:
      names rewritten to file paths, categories mapped onto Bedrock's enum, `event` entries and
      subtitles reported.
- [ ] **Item models with sub-models** (`display` transforms) → Bedrock `minecraft:icon` and
      `attachables`, so handheld tools do not render flat.
- [x] **Blockbench `.bbmodel`** import: mods increasingly ship these instead of `elements`.

## P2 — Conversion engine

- [ ] Parallel conversion of independent features (`multiprocessing`), target <4 s for Create.
- [ ] Streaming atlas resolution — the 1 852-tile index is rebuilt per block today.
- [ ] Incremental conversion: skip features whose source files did not change (hash manifest).
- [ ] Smarter tag expansion: prefer the smallest Bedrock item set, not the first alphabetically.

## P3 — Interface

- [ ] Diff view: previous conversion vs current, per feature, with the fidelity delta.
- [ ] Filterable results table (status, kind, limitation) with export to CSV.
- [ ] Live log pane with cancellation that keeps a partial report.

## P4 — Quality

- [ ] Property-based tests over random element lists (rotations, negative sizes, missing UVs).
- [ ] Golden-file test: a small hand-built jar → committed expected output tree.
- [ ] Fuzz the archive reader against truncated/malformed jars.

## P5 — Geometry fidelity, remaining

- [ ] **In-game sign check for the X mirror.** The convention is now pinned to four
      implementations and to the `cross` golden, but a screenshot of a stair, a door and a
      Create shaft in a real world would close it completely.
- [x] **`rescale` on Java elements.** Done in 1.4.0: the factor is folded into the bounds about the
      rotation origin, which is the point Java scales about, so the pivot does not move.
- [ ] **Cylinders.** Create and Valkyrien build curved parts from explicit vertex polygons, not
      cubes. Bedrock `poly_mesh` is the only target and it supports triangles/free vertices;
      nothing converts `.json` polylines yet.
- [ ] **Group-tinted faces.** Java `tintindex` → Bedrock `minecraft:block` tint behaviour is
      per-block, not per-face, so a model with a tinted overlay loses the difference.
