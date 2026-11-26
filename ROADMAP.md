# Roadmap

Ordered by what blocks a usable release, then by how much fidelity each item buys.

## P0 — Windows executable

- [ ] `.github/workflows/build.yml`: `windows-latest`, Python 3.10/3.12 matrix, `pyinstaller`,
      upload `dist/J2BStudio.exe` as an artifact and to a Release on tag `v*`.
- [ ] Verify the frozen exe starts without Python: tkinter present, knowledge data bundled,
      `sys._MEIPASS` paths resolved (`packaging/j2b.spec` already lists the data dir).
- [ ] Portable build (`--onedir`) next to the one-file exe — one-file unpacks to `%TEMP%` on
      every launch, which is slow for a 9 s conversion.
- [ ] Version resource stamped into the exe (`--version-file`).

## P1 — Content fidelity

- [ ] **Entity models.** Java `geo`/`bbmodel` → Bedrock `geometry` with bones. Currently the
      model is manual; only the texture is copied. Bones, pivots and animations are the bulk of
      the work.
- [ ] **Animations.** Java `.json` entity animations → Bedrock `animations` block. Keyframe and
      molang translation; partial coverage is fine if each animation is marked exact/approximate.
- [ ] **Audio.** `sounds.json` + `.ogg` → `sound_definitions.json` + `sounds/`. Straightforward
      and currently missing entirely.
- [ ] **Item models with sub-models** (`display` transforms) → Bedrock `minecraft:icon` and
      `attachables`, so handheld tools do not render flat.
- [ ] **Blockbench `.bbmodel`** import: mods increasingly ship these instead of `elements`.

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
