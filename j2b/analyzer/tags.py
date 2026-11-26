"""Item tag resolution.

Bedrock recipes accept one concrete item per slot, so a Java tag ingredient has
to become either one representative item (lossy) or one recipe per tag member
(exact, but produces N documents). This module reads the tag files that ship in
the mod jar so the recipe converter can make that choice with real data instead
of guessing.
"""

from __future__ import annotations

from typing import Any

from ..utils import split_id

TAG_DIRECTORIES = ("tags/item/", "tags/items/")

#: A tag nested deeper than this is almost certainly a build mistake.
MAX_DEPTH = 6

#: Vanilla item tags, written out from the 1.21.1 data pack
#: (``mcmeta/1.21.1-data``) rather than guessed from the naming pattern.
#:
#: A mod jar only ships the tags it *adds to*. Tags the game itself supplies
#: live in ``data/minecraft/tags/item/`` and are only present when the mod
#: appends to them -- and even then the file lists the additions, not the whole
#: membership. Create's recipes lean on ``minecraft:wooden_doors``,
#: ``minecraft:wooden_slabs`` and ``minecraft:planks`` constantly and the jar
#: carries none of them, so those recipes were dropped for a missing ingredient
#: that actually exists in the game.
#:
#: ``minecraft:logs`` is deliberately absent: its real content is three nested
#: tags (``logs_that_burn``, ``crimson_stems``, ``warped_stems``), and a flat
#: list here would claim a membership this table cannot verify.
VANILLA_ITEM_TAGS: dict[str, tuple[str, ...]] = {
    "minecraft:planks": (
        "minecraft:oak_planks", "minecraft:spruce_planks", "minecraft:birch_planks",
        "minecraft:jungle_planks", "minecraft:acacia_planks", "minecraft:dark_oak_planks",
        "minecraft:crimson_planks", "minecraft:warped_planks", "minecraft:mangrove_planks",
        "minecraft:bamboo_planks", "minecraft:cherry_planks",
    ),
    "minecraft:wooden_slabs": (
        "minecraft:oak_slab", "minecraft:spruce_slab", "minecraft:birch_slab",
        "minecraft:jungle_slab", "minecraft:acacia_slab", "minecraft:dark_oak_slab",
        "minecraft:crimson_slab", "minecraft:warped_slab", "minecraft:mangrove_slab",
        "minecraft:bamboo_slab", "minecraft:cherry_slab",
    ),
    "minecraft:wooden_stairs": (
        "minecraft:oak_stairs", "minecraft:spruce_stairs", "minecraft:birch_stairs",
        "minecraft:jungle_stairs", "minecraft:acacia_stairs", "minecraft:dark_oak_stairs",
        "minecraft:crimson_stairs", "minecraft:warped_stairs", "minecraft:mangrove_stairs",
        "minecraft:bamboo_stairs", "minecraft:cherry_stairs",
    ),
    "minecraft:wooden_doors": (
        "minecraft:oak_door", "minecraft:spruce_door", "minecraft:birch_door",
        "minecraft:jungle_door", "minecraft:acacia_door", "minecraft:dark_oak_door",
        "minecraft:crimson_door", "minecraft:warped_door", "minecraft:mangrove_door",
        "minecraft:bamboo_door", "minecraft:cherry_door",
    ),
    "minecraft:wooden_trapdoors": (
        "minecraft:oak_trapdoor", "minecraft:spruce_trapdoor", "minecraft:birch_trapdoor",
        "minecraft:jungle_trapdoor", "minecraft:acacia_trapdoor",
        "minecraft:dark_oak_trapdoor", "minecraft:crimson_trapdoor",
        "minecraft:warped_trapdoor", "minecraft:mangrove_trapdoor",
        "minecraft:bamboo_trapdoor", "minecraft:cherry_trapdoor",
    ),
    "minecraft:wooden_buttons": (
        "minecraft:oak_button", "minecraft:spruce_button", "minecraft:birch_button",
        "minecraft:jungle_button", "minecraft:acacia_button", "minecraft:dark_oak_button",
        "minecraft:crimson_button", "minecraft:warped_button", "minecraft:mangrove_button",
        "minecraft:bamboo_button", "minecraft:cherry_button",
    ),
    "minecraft:wooden_pressure_plates": (
        "minecraft:oak_pressure_plate", "minecraft:spruce_pressure_plate",
        "minecraft:birch_pressure_plate", "minecraft:jungle_pressure_plate",
        "minecraft:acacia_pressure_plate", "minecraft:dark_oak_pressure_plate",
        "minecraft:crimson_pressure_plate", "minecraft:warped_pressure_plate",
        "minecraft:mangrove_pressure_plate", "minecraft:bamboo_pressure_plate",
        "minecraft:cherry_pressure_plate",
    ),
    "minecraft:wooden_fences": (
        "minecraft:oak_fence", "minecraft:acacia_fence", "minecraft:dark_oak_fence",
        "minecraft:spruce_fence", "minecraft:birch_fence", "minecraft:jungle_fence",
        "minecraft:crimson_fence", "minecraft:warped_fence", "minecraft:mangrove_fence",
        "minecraft:bamboo_fence", "minecraft:cherry_fence",
    ),
    "minecraft:small_flowers": (
        "minecraft:dandelion", "minecraft:poppy", "minecraft:blue_orchid",
        "minecraft:allium", "minecraft:azure_bluet", "minecraft:red_tulip",
        "minecraft:orange_tulip", "minecraft:white_tulip", "minecraft:pink_tulip",
        "minecraft:oxeye_daisy", "minecraft:cornflower", "minecraft:lily_of_the_valley",
        "minecraft:wither_rose", "minecraft:torchflower",
    ),
}

#: Convention tags shipped by NeoForge itself (``src/generated/resources``).
#: Note the nether woods: stripped crimson/warped are a *stem* and a *hyphae*,
#: and bamboo is a block, so the naive ``stripped_<wood>_log`` cross product
#: would name three items that do not exist.
CONVENTION_ITEM_TAGS: dict[str, tuple[str, ...]] = {
    "c:stripped_logs": (
        "minecraft:stripped_oak_log", "minecraft:stripped_spruce_log",
        "minecraft:stripped_birch_log", "minecraft:stripped_jungle_log",
        "minecraft:stripped_acacia_log", "minecraft:stripped_dark_oak_log",
        "minecraft:stripped_mangrove_log", "minecraft:stripped_cherry_log",
        "minecraft:stripped_bamboo_block", "minecraft:stripped_crimson_stem",
        "minecraft:stripped_warped_stem",
    ),
    "c:stripped_woods": (
        "minecraft:stripped_oak_wood", "minecraft:stripped_spruce_wood",
        "minecraft:stripped_birch_wood", "minecraft:stripped_jungle_wood",
        "minecraft:stripped_acacia_wood", "minecraft:stripped_dark_oak_wood",
        "minecraft:stripped_mangrove_wood", "minecraft:stripped_cherry_wood",
        "minecraft:stripped_crimson_hyphae", "minecraft:stripped_warped_hyphae",
    ),
}


def vanilla_members(tag: str) -> list[str]:
    """Members of a tag the game or the loader supplies, or ``[]`` if unknown."""
    if tag in VANILLA_ITEM_TAGS:
        return list(VANILLA_ITEM_TAGS[tag])
    if tag in CONVENTION_ITEM_TAGS:
        return list(CONVENTION_ITEM_TAGS[tag])
    for loader in ("forge:", "neoforge:"):
        if tag.startswith(loader):
            return list(VANILLA_ITEM_TAGS.get("minecraft:" + tag.split(":", 1)[1], ()))
    return []


class TagIndex:
    """Lazily resolved ``data/<namespace>/tags/item/*.json`` files."""

    def __init__(self, archive: Any) -> None:
        self.archive = archive
        self._raw: dict[str, list[Any]] | None = None
        self._cache: dict[str, list[str]] = {}

    # -- loading ----------------------------------------------------------
    def _tag_namespaces(self) -> list[str]:
        """Every namespace that ships tags, not just the ones that ship assets.

        Convention tags live in ``data/c/`` and ``data/neoforge/``, namespaces
        that have no ``assets/`` folder at all. Reading only
        ``archive.namespaces`` (derived from ``assets/``) made 90 tag files in
        Create's jar invisible, and every recipe that used one was dropped.
        """
        found: list[str] = list(getattr(self.archive, "namespaces", None) or [])
        try:
            names = list(self.archive.names())
        except Exception:  # pragma: no cover - archive is already validated
            names = []
        for name in names:
            if not name.startswith("data/"):
                continue
            parts = name.split("/")
            if len(parts) > 2 and parts[1] and parts[1] not in found:
                found.append(parts[1])
        return found

    def _index(self) -> dict[str, list[Any]]:
        if self._raw is not None:
            return self._raw
        raw: dict[str, list[Any]] = {}
        if self.archive is not None:
            for namespace in self._tag_namespaces():
                for directory in TAG_DIRECTORIES:
                    prefix = f"data/{namespace}/{directory}"
                    try:
                        names = list(self.archive.iter_files(prefix, ".json"))
                    except Exception:  # pragma: no cover - archive already validated
                        continue
                    for name in names:
                        body = self.archive.json(name)
                        if not isinstance(body, dict):
                            continue
                        values = body.get("values")
                        if not isinstance(values, list):
                            continue
                        tag_name = name[len(prefix) : -5].replace("\\", "/")
                        raw[f"{namespace}:{tag_name}"] = values
        self._raw = raw
        return raw

    def has(self, tag: str) -> bool:
        key = normalize_tag(tag)
        return key in self._index() or bool(vanilla_members(key))

    def members(self, tag: str, _depth: int = 0, _seen: frozenset[str] = frozenset()) -> list[str]:
        """Concrete item ids (no ``#``) for ``tag``, expanding nested tags."""
        key = normalize_tag(tag)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        if _depth > MAX_DEPTH or key in _seen:
            return []
        values = self._index().get(key)
        if values is None:
            # The jar does not carry this file. A tag the game or the loader
            # supplies is still real, so consult the reference table before
            # letting the caller report a missing ingredient.
            fallback = vanilla_members(key)
            if _depth == 0:
                self._cache[key] = fallback
            return list(fallback)
        resolved: list[str] = []
        for entry in values:
            if isinstance(entry, str) and entry.startswith("#"):
                for nested in self.members(entry, _depth + 1, _seen | {key}):
                    if nested not in resolved:
                        resolved.append(nested)
            elif isinstance(entry, str):
                if entry not in resolved:
                    resolved.append(entry)
            elif isinstance(entry, dict):
                nested_id = entry.get("id")
                if isinstance(nested_id, str):
                    if nested_id.startswith("#"):
                        for nested in self.members(nested_id, _depth + 1, _seen | {key}):
                            if nested not in resolved:
                                resolved.append(nested)
                    elif nested_id not in resolved:
                        resolved.append(nested_id)
        if _depth == 0:
            self._cache[key] = resolved
        return list(resolved)


def normalize_tag(tag: str) -> str:
    clean = str(tag or "").strip().lstrip("#")
    namespace, name = split_id(clean)
    return f"{namespace}:{name}"
