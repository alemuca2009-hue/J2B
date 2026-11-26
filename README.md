# J2B Studio

Converts a **Java Edition mod** (`.jar`) into a **Bedrock add-on** (`.mcaddon`) — and is explicit about
the parts it cannot convert.

Most "mod converters" fail the same way: they emit a skeleton for everything, the add-on half-works, and
you find out at runtime. J2B Studio only builds what it can justify from files in the jar, and reports
everything else as *partial*, *manual* or *unsupported*, with the reason and the work required.

```
python -m j2b convert mods/ruby.jar -o out
```

## What actually converts

| Java asset | Bedrock output | Verdict |
| --- | --- | --- |
| Block with a cube model | BP block + RP texture | **converted** — texture, geometry, render method |
| Plant / flower (`block/cross`) | BP block + custom geometry | **converted** — two planes, `alpha_test` |
| Block with many blockstates | base appearance only | **partial** — permutations must be hand-written |
| Item with `item/generated` | BP item + RP icon + lang | **converted** |
| Tool / food item | icon + registration | **partial** — stats live in Java code |
| Shaped / shapeless / furnace / stonecutter recipe | BP recipe | **converted** |
| Recipe using an ingredient tag | representative item | **partial** — Bedrock takes one item per slot |
| Smithing recipe | — | **unsupported** — no Bedrock schema |
| Ore configured + placed feature | BP `ore_feature` + `feature_rules` | **converted** |
| Tree / structure / biome worldgen | — | **manual** — must be rebuilt |
| Entity with a GeckoLib or `.bbmodel` file | RP geometry + texture | **partial** — bones and UVs are the author's; health, hitbox, loot and AI are code |
| Entity whose model exists only as a Java class | texture copied as reference | **manual** — nothing to translate |
| GUI screen / menu, command, keybind, particle, dimension | — | **manual / unsupported** |

Nothing is invented. If a texture is missing from the jar, the block still generates but is marked
*partial* with a note saying the placeholder is vanilla stone.

## Measured on a real mod

Create 6.0.10 for 1.21.1, converted end to end (`28 890` features detected, ~9 s, no network access):

| | blocks | geometries | permutations | dangling atlas refs | validation errors | estimated fidelity |
| --- | --- | --- | --- | --- | --- | --- |
| before the atlas and rotation work | 643 | 1 762 | 6 754 | 26 | 252 | 0.446 |
| current | 643 | 1 762 | 6 754 | 0 | 0 | 0.490 |

The two defects that table records were both silent ones — the add-on loaded and simply looked wrong:

* **Texture names were rebuilt instead of looked up.** `minecraft:block/oak_log` is `oak_log_side` on
  Bedrock, and `warped_planks` lives under `textures/blocks/huge_fungus/`. The converter now resolves
  every borrowed name against the shipped atlas (`official_tiles()`, 1 852 tiles) and writes the tile
  key and file path from it. Reusing a vanilla tile is legitimate: resource packs merge their atlas
  with vanilla's, so no PNG has to be copied.
* **Rotations were not baked into geometry.** A `variants` entry with `x`/`y` is now applied to the
  exported cubes and face names (`block.rotation_bake`), so stairs, shafts and pipes face the way the
  blockstate says instead of all facing north.

The remaining `12` non-error findings are recipes whose ingredient has no Bedrock counterpart. Those
recipes are **not** written — a recipe pointing at a missing item is an uncraftable dead entry — and
each one is listed with the symbol that failed.

## Install

Python 3.10+. No third-party dependencies — standard library only.

```
pip install -e .
```

or run in place:

```
python -m j2b --help
```

## Usage

```
# convert (writes packs, .mcaddon and three reports)
python -m j2b convert mods/ruby.jar -o out

# scan without converting — see what the tool found and why
python -m j2b analyze mods/ruby.jar

# re-validate an existing output folder
python -m j2b validate out/ruby

# inspect the rules the converter applies
python -m j2b kb list --kind block
python -m j2b kb search durability
python -m j2b kb audit

# compare runs
python -m j2b history

# desktop UI
python -m j2b gui
```

`convert` exits `1` if validation found a blocking error, `2` if the archive could not be read — usable in CI.

## Output layout

```
out/test_mod/
├── behavior_pack/          # blocks, items, recipes, features, feature_rules, manifests
├── resource_pack/          # textures, atlases, geometry, lang
├── test_mod.mcaddon        # both packs, ready to import
├── conversion_report.json  # machine-readable, one record per feature
├── conversion_report.md    # human report with a manual-work checklist
└── conversion_report.html
```

Pack UUIDs are derived from the mod id, so re-converting the same mod updates the pack instead of
creating a duplicate in Minecraft.

## How the decisions are made

Every verdict comes from a documented entry: the signals it matches, the outcome, the losses, and
references. A feature is turned into signals and matched against the most specific entry.

The knowledge base is layered, and later layers correct earlier ones:

| Layer | Source | Overrides |
|---|---|---|
| builtin | `j2b/knowledge/entries.py` | — |
| bundled | `j2b/knowledge/data/entries.jsonl` (1 case per line, e.g. `kb-block-cross-plant`) | nothing with the same id |
| overlay | `~/.j2b-studio/knowledge_overlay.json` | any entry with the same id |

Signals come in two generations. Bare tokens (`block`, `block_multistate`, `worldgen_ore`) date from the
first table; namespaced tokens (`class:mixin`, `recipe:smelting`, `feature:ore`, `loader:fabric`,
`cube_all`, `cross_model`) name where the signal came from, so an entry cannot match on a keyword
collision. Entries may be written either way:

```json
{"id": "kb.example", "kind": "block", "signals": ["block"]}
{"id": "kb.example", "kind": "block", "match": {"all": ["block"], "any": ["cube_all", "cube"]}}
```

`match.all` must all be present, `match.any` needs one hit. Specificity is the number of *required*
signals, so an entry listing ten branches does not outrank one that pins down two exact signals.

`python -m j2b kb audit` proves the table is sound: unique ids, known kinds/outcomes/verification
levels, a rationale, at least one limitation and one http reference per entry, and — the important one —
every matched signal must actually be emitted by `derive_signals`. A typo therefore cannot create an
entry that silently never fires. The audit exits non-zero on any defect and is covered by
`tests/test_knowledge.py`.

Two rules keep the report honest:

1. **The knowledge base can downgrade the engine.** If the engine says "converted" but the documented
   strategy says the pattern is only partially reproducible, the feature is downgraded
   (`FIDELITY_DOWNGRADED`) and the documented limitation is attached. A tool icon never claims more than
   the icon supports.
2. **Unmatched features are recorded as gaps.** They are written to `knowledge_suggestions.json` so they
   can be curated later.

### Teaching it a new pattern

Drop an overlay into `~/.j2b-studio/knowledge_overlay.json` (or `$J2B_DATA_DIR`):

```bash
python -m j2b kb template > ~/.j2b-studio/knowledge_overlay.json
```

```json
[{
  "id": "user.factory.blocks",
  "title": "My mod's machine blocks",
  "kind": "block",
  "signals": ["block", "block_entity_logic"],
  "strategy": "script_api",
  "outcome": "manual",
  "rationale": "Machines tick in Java; Bedrock needs a scripted block.",
  "limitations": ["Rebuild the inventory with @minecraft/server block components."],
  "refs": [],
  "verification": "community"
}]
```

Overlay entries override built-ins with the same id and are listed by `j2b kb stats`.

## Validation

Before finishing, the generated packs are checked for: readable manifests, distinct UUIDs, valid module
types, atlas entries pointing at existing textures, block/item identifiers, lang keys, recipe identifiers
and station tags, ore feature `replace_rules`, and feature rules referencing a feature that exists.
Problems appear in the CLI output and in the report — an add-on that Minecraft would reject is not
reported as clean.

## Tests

```
python -m unittest discover -s tests -t tests
```

The fixture (`tests/make_test_jar.py`) is a synthetic Fabric mod with a cube block, a cross block, a
generated item, a tool, a tagged recipe, a smithing recipe, an ore feature with placement, a tree
feature, an entity and three class-name hints. It covers conversion, downgrading, validation,
determinism and failure paths.

## Limits worth stating up front

* **Code is not converted.** Entities, GUIs, commands, particles, dimensions and every custom mechanic
  live in Java bytecode. J2B Studio reports them; it does not decompile them.
* **Assets are the source of truth.** Stats that Java keeps in code (hardness, nutrition, attack damage,
  spawn weights) default in the output and are flagged.
* **Class-name hints are hints.** A class named `FooScreen` is a lead to inspect, not a finding.
* **Java tags have no Bedrock equivalent** and are collapsed to one representative item, always reported.
* **Fidelity is an average of the features found**, weighted by outcome. It is a summary, not a guarantee.

## Layout

```
j2b/
├── analyzer/        # archive reader + resource/class scanner
├── converters/      # pack writer, blocks, items, recipes, entities, worldgen
├── knowledge/       # documented strategies + case memory
├── cli.py gui.py    # entry points
├── converter.py     # orchestration
├── validate.py      # structural pack checks
└── report.py        # json / markdown / html reports
```
