"""Documented Java→Bedrock strategies.

Every entry is a claim about how a Java feature maps to Bedrock, with the
reason it works, the parts that do not survive the trip, and where the claim
comes from. The converter never invents a strategy that is not in this table
(plus the user's own overlay), which is why the report can be trusted.
"""

from __future__ import annotations

from typing import Any

# An entry matches when *all* of its signals are present on the feature.
ENTRIES: list[dict[str, Any]] = [
    {
        "id": "kb.block.cube",
        "title": "Textured block with a cube/cube_all model",
        "kind": "block",
        "signals": ["block"],
        "strategy": "block_model",
        "outcome": "converted",
        "rationale": "Bedrock blocks use the same texture-atlas shorthands, and a full cube needs no custom geometry.",
        "limitations": [
            "Hardness, blast resistance, light level, sounds and tool requirements come from Java code and must be re-declared.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Blocks", "url": "https://wiki.bedrock.dev/blocks/blocks-intro"},
            {"title": "Microsoft Learn — Behaviour packs", "url": "https://learn.microsoft.com/en-us/minecraft/creator/documents/behaviorpack"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.block.cross",
        "title": "Plant/flower block using the cross model",
        "kind": "block",
        "signals": ["block"],
        "strategy": "block_model",
        "outcome": "converted",
        "rationale": "Two intersecting planes reproduce Java's cross model; the alpha_test render method keeps cutout transparency.",
        "limitations": [
            "Block sounds and placement rules (soil type) must be re-declared manually.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Blocks", "url": "https://wiki.bedrock.dev/blocks/blocks-intro"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.block.states",
        "title": "Block with several blockstate variants",
        "kind": "block",
        "signals": ["block", "block_multistate"],
        "strategy": "block_model",
        "outcome": "partial",
        "rationale": "Only one appearance is generated; Bedrock needs explicit block states and permutations for the rest.",
        "limitations": [
            "Variants beyond the base appearance are lost unless re-declared with block permutations.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Block states", "url": "https://wiki.bedrock.dev/blocks/block-states"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.block.entity",
        "title": "Block with tile-entity logic (container, machine, sign-like)",
        "kind": "block",
        "signals": ["block", "block_entity_logic"],
        "strategy": "block_entity_rebuild",
        "outcome": "manual",
        "rationale": "Block entities are code in Java; Bedrock has no data-driven equivalent for custom block entities.",
        "limitations": [
            "Inventory, ticking and saved state must be reimplemented with the Script API.",
            "The block itself can still be converted as decoration.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Script API", "url": "https://wiki.bedrock.dev/scripting/starting-scripts"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.item.generated",
        "title": "Item with a generated model",
        "kind": "item",
        "signals": ["item"],
        "strategy": "item_model",
        "outcome": "converted",
        "rationale": "A single layer0 texture maps directly to a Bedrock item icon.",
        "limitations": [
            "Stack size, durability, food values and tool stats are code-defined in Java and default in the output.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Items", "url": "https://wiki.bedrock.dev/items/items-intro"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.item.tool",
        "title": "Tool or weapon item",
        "kind": "item",
        "signals": ["item", "item_handheld"],
        "strategy": "item_model",
        "outcome": "partial",
        "rationale": "The icon converts, but Bedrock tool stats live in item components that Java does not expose in assets.",
        "limitations": [
            "Attack damage, durability and mining speed are not recovered; defaults are emitted.",
            "Bedrock custom tools also need `minecraft:digger` and `minecraft:enchantable` components written by hand.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Items", "url": "https://wiki.bedrock.dev/items/items-intro"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.item.food",
        "title": "Food item",
        "kind": "item",
        "signals": ["item", "item_food"],
        "strategy": "item_model",
        "outcome": "partial",
        "rationale": "The icon converts; nutrition/saturation are code values that Bedrock expresses with food components.",
        "limitations": [
            "`minecraft:food` values must be filled in by hand (Java stores them in code, not in assets).",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Items", "url": "https://wiki.bedrock.dev/items/items-intro"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.recipe.crafting",
        "title": "Shaped or shapeless crafting recipe",
        "kind": "recipe",
        "signals": ["recipe"],
        "strategy": "recipe_direct",
        "outcome": "converted",
        "rationale": "Bedrock recipe JSON uses the same pattern/key/ingredient structure as Java.",
        "limitations": [
            "Java ingredient tags have no Bedrock equivalent and are collapsed to a representative item.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Recipes", "url": "https://wiki.bedrock.dev/loot/recipes"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.recipe.tag",
        "title": "Recipe that uses an ingredient tag",
        "kind": "recipe",
        "signals": ["recipe", "recipe_tag"],
        "strategy": "recipe_direct",
        "outcome": "partial",
        "rationale": "Bedrock recipes accept one concrete item per slot; a tag becomes its documented representative.",
        "limitations": [
            "Only the representative item is accepted by the converted recipe; other tag members stop working.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Recipes", "url": "https://wiki.bedrock.dev/loot/recipes"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.recipe.smithing",
        "title": "Smithing or trim recipe",
        "kind": "recipe",
        "signals": ["recipe", "recipe_smithing"],
        "strategy": "recipe_manual",
        "outcome": "unsupported",
        "rationale": "Java smithing recipes use template/base/addition slots that Bedrock's recipe schema does not model.",
        "limitations": [
            "Must be redesigned (usually as a custom crafting-table recipe or with the Script API).",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Recipes", "url": "https://wiki.bedrock.dev/loot/recipes"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.entity.custom",
        "title": "Custom mob / entity",
        "kind": "entity",
        "signals": ["entity"],
        "strategy": "entity_rebuild",
        "outcome": "manual",
        "rationale": "Java entity models, renderers and AI are code; Bedrock needs separate behaviour, geometry and animation files.",
        "limitations": [
            "The Java model format is not convertible to Bedrock geometry; rebuild it in Blockbench or GeckoLib.",
            "Health, hitbox, loot, sounds and AI goals must be re-authored.",
            "Textures are copied as reference art only.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Entities", "url": "https://wiki.bedrock.dev/entities/entity-intro"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.worldgen.ore",
        "title": "Ore configured feature",
        "kind": "worldgen",
        "signals": ["worldgen_configured_feature", "worldgen_ore"],
        "strategy": "worldgen_ore",
        "outcome": "converted",
        "rationale": "Bedrock has a first-class `minecraft:ore_feature` with count and replace rules.",
        "limitations": [
            "Biome placement is approximated with an overworld biome filter unless edited by hand.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — World generation", "url": "https://wiki.bedrock.dev/worldgen/world-generation"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.worldgen.non_ore",
        "title": "Tree, flower, structure or custom worldgen feature",
        "kind": "worldgen",
        "signals": ["worldgen"],
        "strategy": "worldgen_manual",
        "outcome": "manual",
        "rationale": "Bedrock's feature types do not correspond one-to-one with Java's configured/placed split.",
        "limitations": [
            "Must be rebuilt with Bedrock feature JSON or the Script API; nothing is generated automatically.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — World generation", "url": "https://wiki.bedrock.dev/worldgen/world-generation"},
        ],
        "verification": "community",
    },
    {
        "id": "kb.gui.screen",
        "title": "Custom screen or menu",
        "kind": "gui",
        "signals": ["gui_screen"],
        "strategy": "gui_unsupported",
        "outcome": "unsupported",
        "rationale": "Bedrock add-ons cannot draw arbitrary screens; only server forms (modal/dialog) exist via the Script API.",
        "limitations": [
            "Rebuild as a form UI if the feature can be expressed as buttons and fields.",
            "Pixel-accurate custom rendering is not possible.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Script API", "url": "https://wiki.bedrock.dev/scripting/starting-scripts"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.gui.menu",
        "title": "Container menu / screen handler",
        "kind": "gui",
        "signals": ["gui_menu"],
        "strategy": "gui_unsupported",
        "outcome": "unsupported",
        "rationale": "Screen handlers are code; Bedrock has no data-driven custom container UI.",
        "limitations": [
            "Use a chest/hopper container with the Script API, or a form UI.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Forms / UI", "url": "https://wiki.bedrock.dev/scripting/ui"},
            {"title": "Microsoft Learn — Custom commands (script API)", "url": "https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/minecraft-server"},
        ],
        "verification": "community",
    },
    {
        "id": "kb.mechanic.command",
        "title": "Custom command",
        "kind": "mechanic",
        "signals": ["mechanic_command"],
        "strategy": "script_api",
        "outcome": "manual",
        "rationale": "Bedrock commands are implemented with `system.beforeEvents.startup` custom commands in the Script API.",
        "limitations": [
            "Needs a script entry point in the behaviour pack and a JavaScript port of the command logic.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Script API", "url": "https://wiki.bedrock.dev/scripting/starting-scripts"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.mechanic.keybind",
        "title": "Key binding",
        "kind": "mechanic",
        "signals": ["mechanic_keybind"],
        "strategy": "unsupported",
        "outcome": "unsupported",
        "rationale": "Add-ons cannot register new key bindings on Bedrock.",
        "limitations": [
            "Replace with an item interaction, a form button or a custom command.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Items & interactions", "url": "https://wiki.bedrock.dev/items/item-interactions"},
            {"title": "Microsoft Learn — Block components", "url": "https://learn.microsoft.com/en-us/minecraft/creator/reference/content/blockreference/examples/blockcomponents/minecraftblock_on_player_destroyed"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.mechanic.client",
        "title": "Client-side initializer or rendering hook",
        "kind": "mechanic",
        "signals": ["mechanic_client"],
        "strategy": "unsupported",
        "outcome": "unsupported",
        "rationale": "Client modding hooks do not exist for Bedrock add-ons; rendering is data-driven only.",
        "limitations": [
            "Behaviour that lived on the client must be dropped or moved server-side where possible.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Client-server model", "url": "https://wiki.bedrock.dev/scripting/starting-scripts"},
            {"title": "Microsoft Learn — Entity client definition", "url": "https://learn.microsoft.com/en-us/minecraft/creator/reference/content/entityreference"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.mechanic.particle",
        "title": "Custom particle",
        "kind": "mechanic",
        "signals": ["mechanic_particle"],
        "strategy": "particle_rebuild",
        "outcome": "manual",
        "rationale": "Bedrock particles are data-driven but use a different schema and texture atlas.",
        "limitations": [
            "Particle JSON and textures must be re-authored; behaviour is not translated.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Particles", "url": "https://wiki.bedrock.dev/visuals/particles"},
        ],
        "verification": "community",
    },
    {
        "id": "kb.mechanic.dimension",
        "title": "Custom dimension or chunk generator",
        "kind": "mechanic",
        "signals": ["mechanic_dimension"],
        "strategy": "unsupported",
        "outcome": "unsupported",
        "rationale": "Bedrock add-ons cannot register new dimensions or replace chunk generation from data.",
        "limitations": [
            "Only vanilla dimensions can be modified (biomes, features, blocks).",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Biomes & features", "url": "https://wiki.bedrock.dev/world-generation/biomes"},
            {"title": "Microsoft Learn — Feature rules", "url": "https://learn.microsoft.com/en-us/minecraft/creator/reference/content/featuresreference/examples/features_json"},
        ],
        "verification": "verified",
    },
    {
        "id": "kb.mechanic.unmapped",
        "title": "Unmapped mechanic",
        "kind": "mechanic",
        "signals": ["mechanic"],
        "strategy": "manual_review",
        "outcome": "manual",
        "rationale": "The scanner saw a behavioural hint it cannot classify with confidence.",
        "limitations": [
            "Inspect the classes listed in the report and decide whether the Script API can reproduce them.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Script API", "url": "https://wiki.bedrock.dev/scripting/starting-scripts"},
        ],
        "verification": "unverified",
    },
    {
        "id": "kb.gui.unmapped",
        "title": "Unclassified GUI class",
        "kind": "gui",
        "signals": ["gui"],
        "strategy": "gui_unsupported",
        "outcome": "unsupported",
        "rationale": "Any custom screen in Java must be rebuilt as a Bedrock form; nothing carries over.",
        "limitations": [
            "Rebuild with server forms via the Script API.",
        ],
        "refs": [
            {"title": "Bedrock Wiki — Script API", "url": "https://wiki.bedrock.dev/scripting/starting-scripts"},
        ],
        "verification": "community",
    },
]
