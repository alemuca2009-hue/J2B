"""Java→Bedrock identifier mapping.

Only *documented* differences are remapped; everything else passes through
unchanged, because guessing at ids produces blocks that silently do not exist.
"""

from __future__ import annotations

import json
from pathlib import Path

# Java id -> Bedrock id, for vanilla names that differ between editions.
ALIASES: dict[str, str] = {
    "minecraft:grass": "minecraft:short_grass",
    "minecraft:grass_block": "minecraft:grass_block",
    "minecraft:stone_slab": "minecraft:stone_block_slab",
    "minecraft:oak_slab": "minecraft:oak_slab",
    "minecraft:cobweb": "minecraft:web",
    "minecraft:magma_block": "minecraft:magma",
    "minecraft:terracotta": "minecraft:hardened_clay",
    "minecraft:snow_block": "minecraft:snow",
    "minecraft:nether_bricks": "minecraft:nether_brick",
    "minecraft:nether_brick_fence": "minecraft:nether_brick_fence",
    "minecraft:smooth_stone": "minecraft:smooth_stone",
    "minecraft:wall_torch": "minecraft:torch",
    "minecraft:short_grass": "minecraft:short_grass",
    "minecraft:tall_grass": "minecraft:double_plant",
    "minecraft:sunflower": "minecraft:double_plant",
    "minecraft:lilac": "minecraft:double_plant",
    "minecraft:rose_bush": "minecraft:double_plant",
    "minecraft:peony": "minecraft:double_plant",
    "minecraft:poppy": "minecraft:poppy",
    "minecraft:carved_pumpkin": "minecraft:carved_pumpkin",
    "minecraft:oak_planks": "minecraft:oak_planks",
    "minecraft:iron_bars": "minecraft:iron_bars",
    "minecraft:crafting_table": "minecraft:crafting_table",
    "minecraft:furnace": "minecraft:furnace",
    "minecraft:diamond_ore": "minecraft:diamond_ore",
    "minecraft:deepslate_diamond_ore": "minecraft:deepslate_diamond_ore",
    "minecraft:water": "minecraft:water",
    "minecraft:lava": "minecraft:lava",
    "minecraft:stone": "minecraft:stone",
    "minecraft:deepslate": "minecraft:deepslate",
    "minecraft:dirt": "minecraft:dirt",
    "minecraft:gravel": "minecraft:gravel",
    "minecraft:sand": "minecraft:sand",
    "minecraft:netherrack": "minecraft:netherrack",
    "minecraft:end_stone": "minecraft:end_stone",
    "minecraft:andesite": "minecraft:andesite",
    "minecraft:diorite": "minecraft:diorite",
    "minecraft:granite": "minecraft:granite",
    "minecraft:tuff": "minecraft:tuff",
    "minecraft:calcite": "minecraft:calcite",
}

# Tag -> a single representative item, because Bedrock recipes take one item
# per slot. The loss is reported, never hidden.
TAG_REPRESENTATIVES: dict[str, str] = {
    "minecraft:planks": "minecraft:oak_planks",
    "minecraft:logs": "minecraft:oak_log",
    "minecraft:logs_that_burn": "minecraft:oak_log",
    "minecraft:wooden_slabs": "minecraft:oak_slab",
    "minecraft:stone_crafting_materials": "minecraft:cobblestone",
    "minecraft:coals": "minecraft:coal",
    "minecraft:wool": "minecraft:white_wool",
    "minecraft:sand": "minecraft:sand",
    "minecraft:flowers": "minecraft:poppy",
    "minecraft:small_flowers": "minecraft:poppy",
    "minecraft:leaves": "minecraft:oak_leaves",
    # Tool tags: Create's deployers and saws take "any axe"/"any pickaxe". No
    # Bedrock item means "any tool", so one representative is named and the
    # collapse is reported like every other tag loss.
    "minecraft:axes": "minecraft:iron_axe",
    "minecraft:pickaxes": "minecraft:iron_pickaxe",
    "minecraft:shovels": "minecraft:iron_shovel",
    "minecraft:hoes": "minecraft:iron_hoe",
    "minecraft:swords": "minecraft:iron_sword",
    "minecraft:tools": "minecraft:iron_axe",
    "minecraft:cluster_max_harvestables": "minecraft:iron_pickaxe",
}


def map_block_id(identifier: str, *, is_item: bool = False) -> tuple[str, str | None]:
    """Return ``(bedrock_id, note_or_None)`` for a Java block/item id."""
    raw = str(identifier or "").strip()
    if not raw:
        return "minecraft:stone", "Empty identifier replaced with minecraft:stone."
    if ":" not in raw:
        raw = f"minecraft:{raw}"
    if raw in ALIASES:
        mapped = ALIASES[raw]
        if mapped != raw:
            return mapped, f"`{raw}` is `{mapped}` on Bedrock."
        return mapped, None
    if raw.startswith("minecraft:"):
        # Vanilla ids generally match; no note needed, and no false claim either.
        return raw, None
    return raw, None


#: Convention tags (``c:`` from Fabric/NeoForge, ``forge:``) that name a
#: universal ingredient. The tag file is not in the jar because another mod
#: supplies it, so the only honest options are a representative member or no
#: recipe at all. Each value below is the single vanilla item that tag denotes
#: when it denotes only one thing; the substitution is reported as a loss.
CONVENTION_TAGS: dict[str, str] = {
    "c:dusts/redstone": "minecraft:redstone",
    "c:rods/wooden": "minecraft:stick",
    "c:slimeballs": "minecraft:slime_ball",
    "c:eggs": "minecraft:egg",
    "c:strings": "minecraft:string",
    "c:gunpowders": "minecraft:gunpowder",
    "c:netherracks": "minecraft:netherrack",
    "c:stones": "minecraft:stone",
    "c:cobblestones": "minecraft:cobblestone",
    "c:glass_blocks": "minecraft:glass",
    "c:glass_blocks/colorless": "minecraft:glass",
    "c:glass_panes": "minecraft:glass_pane",
    "c:ingots/iron": "minecraft:iron_ingot",
    "c:ingots/copper": "minecraft:copper_ingot",
    "c:ingots/gold": "minecraft:gold_ingot",
    "c:ingots/netherite": "minecraft:netherite_ingot",
    "c:nuggets/iron": "minecraft:iron_nugget",
    "c:nuggets/gold": "minecraft:gold_nugget",
    "c:storage_blocks/iron": "minecraft:iron_block",
    "c:storage_blocks/copper": "minecraft:copper_block",
    "c:storage_blocks/gold": "minecraft:gold_block",
    "c:barrels/wooden": "minecraft:barrel",
    "c:chests/wooden": "minecraft:chest",
    "c:dyes": "minecraft:white_dye",
    "minecraft:buttons": "minecraft:oak_button",
    "minecraft:wooden_buttons": "minecraft:oak_button",
    "minecraft:stone_buttons": "minecraft:stone_button",
    "minecraft:wooden_pressure_plates": "minecraft:oak_pressure_plate",
    "minecraft:walls": "minecraft:cobblestone_wall",
    "minecraft:wooden_fences": "minecraft:oak_fence",
}
for _colour in (
    "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
    "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black",
):
    CONVENTION_TAGS[f"c:dyes/{_colour}"] = f"minecraft:{_colour}_dye"

TAG_REPRESENTATIVES.update(CONVENTION_TAGS)


def map_tag(tag: str) -> tuple[str, bool]:
    """Return ``(representative_item, matched)``.

    The exact tag name is tried first: rewriting ``c:`` to ``minecraft:`` before
    the lookup only ever worked for tags that happen to be spelled the same in
    both editions.
    """
    clean = str(tag or "").strip()
    if not clean.startswith("#"):
        clean = f"#{clean}"
    key = clean.lstrip("#")
    if key in TAG_REPRESENTATIVES:
        return TAG_REPRESENTATIVES[key], True
    for loader in ("forge:", "c:", "neoforge:"):
        if key.startswith(loader):
            vanilla = "minecraft:" + key.split(":", 1)[1]
            if vanilla in TAG_REPRESENTATIVES:
                return TAG_REPRESENTATIVES[vanilla], True
            if vanilla in ALIASES:
                return ALIASES[vanilla], True
    return "minecraft:air", False


# ---------------------------------------------------------------------------
# Vanilla texture names
# ---------------------------------------------------------------------------
# A mod model may point at a vanilla texture (`minecraft:block/acacia_planks`)
# that is not in the jar because it ships with the game. Bedrock has that art
# under a different atlas tile name. Only inversions that are documented and
# stable are listed; when a name is not covered, the caller reports a missing
# texture instead of picking something that looks close.

WOODS = (
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
    "mangrove", "cherry", "bamboo", "crimson", "warped",
)
COLOURS = (
    "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
    "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black",
)

#: Vanilla textures whose Bedrock tile has the same name.
IDENTICAL = {
    "stone", "cobblestone", "dirt", "sand", "gravel", "glass", "obsidian",
    "netherrack", "end_stone", "glowstone", "bricks", "stone_bricks",
    "smooth_stone", "iron_block", "gold_block", "diamond_block",
    "emerald_block", "lapis_block", "redstone_block", "coal_block",
    "quartz_block_side", "quartz_block_top", "quartz_block_bottom",
    "glass_pane_top", "iron_bars", "sandstone_normal", "sandstone_top",
    "sandstone_bottom", "cobblestone", "mossy_cobblestone", "bedrock",
    "clay", "snow", "ice", "packed_ice", "sponge", "tnt_side", "tnt_top",
    "tnt_bottom", "crafting_table_top", "crafting_table_side",
    "crafting_table_front", "furnace_front", "furnace_side", "furnace_top",
    "bookshelf", "melon_side", "melon_top", "pumpkin_side", "pumpkin_top",
    "pumpkin_face", "hay_block_side", "hay_block_top", "cactus_side",
    "cactus_top", "cactus_bottom", "terracotta", "hardened_clay",
}

_BEDROCK_VANILLA: set[str] = set(IDENTICAL)

_OFFICIAL_BLOCKS: set[str] | None = None
_OFFICIAL_ITEMS: set[str] | None = None
_OFFICIAL_PATHS: dict[str, str] = {}


def _official_tiles() -> tuple[set[str], set[str]]:
    """The vanilla atlas tile names, straight from Mojang's reference atlases.

    ``j2b/data/vanilla_tiles.json`` is extracted from ``Mojang/bedrock-samples``
    (``resource_pack/textures/terrain_texture.json`` and ``item_texture.json``).
    Using the official list instead of a hand-written one is the difference
    between "this tile exists" and "this tile looks like the name I remember":
    the old table produced ``planks_oak`` and ``log_spruce``, and Bedrock has
    neither.
    """
    global _OFFICIAL_BLOCKS, _OFFICIAL_ITEMS
    if _OFFICIAL_BLOCKS is None or _OFFICIAL_ITEMS is None:
        path = Path(__file__).with_name("data") / "vanilla_tiles.json"
        blocks: set[str] = set()
        items: set[str] = set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            blocks = set(payload.get("blocks") or ())
            items = set(payload.get("items") or ())
            for key, value in (payload.get("block_paths") or {}).items():
                if isinstance(value, str):
                    _OFFICIAL_PATHS[f"block:{key}"] = value
            for key, value in (payload.get("item_paths") or {}).items():
                if isinstance(value, str):
                    _OFFICIAL_PATHS[f"item:{key}"] = value
        except (OSError, ValueError):  # pragma: no cover - data file ships with the package
            pass
        _OFFICIAL_BLOCKS, _OFFICIAL_ITEMS = blocks, items
    return _OFFICIAL_BLOCKS, _OFFICIAL_ITEMS


def official_tiles() -> frozenset[str]:
    """Every atlas tile name the vanilla packs define."""
    blocks, items = _official_tiles()
    return frozenset(blocks | items)


def vanilla_tile_path(key: str, category: str = "block") -> str | None:
    """The vanilla file a borrowed atlas tile points at, e.g. ``textures/blocks/stone.png``.

    The path cannot be reconstructed from the key: Bedrock keeps
    ``warped_planks`` under ``textures/blocks/huge_fungus/``, so a pack that
    declares ``textures/blocks/warped_planks`` points at nothing.
    """
    _official_tiles()
    return _OFFICIAL_PATHS.get(f"{'item' if category == 'item' else 'block'}:{key}")


def _candidates(name: str) -> list[str]:
    """Bedrock tile names to try for one Java texture name, best first.

    The order encodes the documented naming difference between the editions:
    Java says ``oak_planks`` / ``oak_log`` / ``oak_leaves``, Bedrock says
    ``oak_planks`` / ``oak_log_side`` / ``oak_leaves`` and keeps older aliases
    (``planks_oak``, ``log_oak``) only where they still exist.
    """
    out = [name]
    if name.endswith("_planks"):
        out.append("planks_" + name[: -len("_planks")])
    if name.endswith("_log"):
        stem = name[: -len("_log")]
        out += [stem + "_log_side", "log_" + stem]
    if name.endswith("_log_top"):
        stem = name[: -len("_log_top")]
        out += [stem + "_log_top", "log_" + stem + "_top"]
    if name.endswith("_leaves"):
        out.append("leaves_" + name[: -len("_leaves")])
    if name.endswith("_wool"):
        out.append("wool_colored_" + name[: -len("_wool")])
    # A mod may name the side texture the Bedrock way already; accept it either
    # way round instead of only for the woods that happen to be in ``WOODS``.
    if name.endswith("_side"):
        out.append(name[: -len("_side")])
    return out


def _build_vanilla_table() -> dict[str, str]:
    """Java texture name -> Bedrock atlas tile, keeping only verified tiles."""
    official = official_tiles()
    wanted: dict[str, str] = {name: name for name in IDENTICAL}
    for wood in WOODS:
        for suffix in ("_planks", "_log", "_log_top", "_leaves"):
            wanted[f"{wood}{suffix}"] = f"{wood}{suffix}"
        wanted[f"stripped_{wood}_log"] = f"stripped_{wood}_log"
        wanted[f"stripped_{wood}_log_top"] = f"stripped_{wood}_log_top"
    for colour in COLOURS:
        wanted[f"{colour}_wool"] = f"{colour}_wool"

    verified: dict[str, str] = {}
    for java_name, bedrock_name in wanted.items():
        for candidate in _candidates(bedrock_name):
            if candidate in official:
                verified[java_name] = candidate
                break
        else:
            # Not in Bedrock at all: report a missing texture rather than point
            # at a tile the game will never find.
            continue
    _BEDROCK_VANILLA.update(verified.values())
    return verified


VANILLA_TEXTURES: dict[str, str] = _build_vanilla_table()

#: Atlas tiles Bedrock itself provides; the validator accepts these without a
#: file in the pack, because resource packs merge their atlas with vanilla's.
#: This is the full official list (``blocks`` + ``items``), not just the curated
#: renames: a pack that reuses ``stone`` or ``stick`` is not broken.
BEDROCK_VANILLA_TEXTURES: frozenset[str] = official_tiles()


def vanilla_texture_key(ref: str, category: str | None = None) -> str | None:
    """Map ``minecraft:block/oak_planks`` to the Bedrock atlas tile ``oak_planks``.

    The curated table is consulted first because it encodes the known renames
    (``oak_log`` -> ``oak_log_side``). Anything else is matched against the
    official atlas exactly, then through ``_candidates``, which is what lets a
    mod reuse a vanilla texture J2B has never seen before without inventing a
    tile name. ``category`` narrows the search when the caller knows whether it
    is asking about terrain or items.
    """
    clean = str(ref or "").strip()
    if not clean or ":" in clean and not clean.startswith("minecraft:"):
        return None
    if clean.startswith("minecraft:"):
        clean = clean.split(":", 1)[1]
    for prefix in ("textures/block/", "textures/blocks/", "block/", "blocks/"):
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]
            category = category or "block"
            break
    else:
        for prefix in ("textures/item/", "textures/items/", "item/", "items/"):
            if clean.startswith(prefix):
                clean = clean[len(prefix) :]
                category = category or "item"
                break

    blocks, items = _official_tiles()
    pool = items if category == "item" else blocks if category == "block" else (blocks | items)

    curated = VANILLA_TEXTURES.get(clean)
    if curated and curated in pool:
        return curated
    for candidate in _candidates(clean):
        if candidate in pool:
            return candidate
    return None
