"""Recipe conversion.

Crafting/furnace/stonecutter recipes map cleanly. Two honest exceptions:
Bedrock recipes take one concrete item per slot, and smithing recipes have no
schema at all.

A Java tag ingredient stands for "any of these items". Bedrock cannot express
that, so the converter reads the tag from the jar and emits **one recipe per
member** — the same set of valid crafts, just written out. When a tag is too
large to expand, or is a vanilla tag whose contents are not in the jar, the
converter falls back to a single representative item and says so.

A recipe that cannot be written *correctly* is not written at all. Silently
substituting an output or shipping a pattern whose symbol is missing from its own
``key`` produces a recipe that either gives the wrong item or fails to load, and
both are worse than a reported gap.
"""

from __future__ import annotations

from itertools import product
from typing import Any

from ..id_map import map_block_id, map_tag
from ..models import Feature
from ..utils import slugify, split_id
from .context import ConversionContext
from .machines import (
    INEXPRESSIBLE,
    Machine,
    _ingredient_list,
    _read_outputs,
    is_fluid,
    primary_outputs,
    station_for_type,
)

CRAFTING_TYPES = ("minecraft:crafting_shaped", "minecraft:crafting_shapeless")
COOKING_TYPES = {
    "minecraft:smelting": "furnace",
    "minecraft:blasting": "furnace",
    "minecraft:smoking": "furnace",
    "minecraft:campfire_cooking": "furnace",
}
STONECUTTING_TYPES = ("minecraft:stonecutting", "minecraft:stone_cutting")
UNSUPPORTED_TYPES = ("minecraft:smithing_transform", "minecraft:smithing_trim")

#: Upper bound on recipes generated from one Java recipe by tag expansion.
#: Bigger than any tag Create ships, small enough that one badly authored recipe
#: cannot flood the pack.
MAX_VARIANTS = 32


# ---------------------------------------------------------------------------
# ingredient resolution
# ---------------------------------------------------------------------------
def _tag_name(value: Any) -> str:
    if isinstance(value, dict):
        raw = value.get("tag")
        return str(raw) if isinstance(raw, str) else ""
    if isinstance(value, str) and value.startswith("#"):
        return value
    return ""


def _options(value: Any, tags: Any) -> tuple[list[str], str]:
    """Candidate Bedrock items for one Java ingredient, plus the tag it came from."""
    if isinstance(value, str):
        item, _note = map_block_id(value, is_item=True)
        return ([item] if item else []), ""
    if isinstance(value, dict):
        for key in ("item", "id", "name"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                item, _note = map_block_id(raw, is_item=True)
                return ([item] if item else []), ""
        tag = _tag_name(value)
        if tag:
            return _tag_options(tag, tags), tag
        # NeoForge wraps alternatives in `neoforge:compound` with a nested
        # `ingredients` list; reading only `items`/`choices` dropped them.
        for key in ("items", "choices", "ingredients"):
            nested = value.get(key)
            if isinstance(nested, list):
                return _merge([_options(entry, tags) for entry in nested])
        return [], ""
    if isinstance(value, list):
        if not value:
            return [], ""
        return _merge([_options(entry, tags) for entry in value])
    return [], ""


def _merge(pairs: list[tuple[list[str], str]]) -> tuple[list[str], str]:
    items: list[str] = []
    tag = ""
    for options, source_tag in pairs:
        tag = tag or source_tag
        for option in options:
            if option not in items:
                items.append(option)
    return items, tag


def _tag_options(tag: str, tags: Any) -> list[str]:
    members: list[str] = []
    if tags is not None:
        try:
            members = tags.members(tag)
        except Exception:  # pragma: no cover - defensive
            members = []
    resolved: list[str] = []
    for member in members:
        item, _note = map_block_id(member, is_item=True)
        if item and item not in resolved:
            resolved.append(item)
    if resolved:
        return resolved
    representative, matched = map_tag(tag)
    return [representative] if matched else []


def _known(item: str, ctx: ConversionContext) -> bool:
    """Only vanilla ids and ids this pack defines can appear in a recipe."""
    return item.startswith("minecraft:") or item in ctx.known_items


def _options_for(value: Any, tags: Any, ctx: ConversionContext) -> tuple[list[str], str]:
    """`_options` filtered to items the generated pack can actually accept.

    Create ships compat recipes for Biomes O' Plenty, Silent Gear and a dozen
    other mods. Those items are not in the jar, so writing them produced recipes
    that load but can never be crafted — a dead entry in the recipe book.
    """
    options, source_tag = _options(value, tags)
    return [option for option in options if _known(option, ctx)], source_tag


# ---------------------------------------------------------------------------
# output parsing
# ---------------------------------------------------------------------------
def _result(value: Any) -> tuple[str | None, int]:
    """Read a recipe output across every schema Java has used.

    ``1.20.5`` moved the output from ``result.item`` to ``result.id``; reading
    only the old key turned every modern recipe into ``minecraft:stone``.
    """
    if isinstance(value, str):
        item, _note = map_block_id(value, is_item=True)
        return item, 1
    if isinstance(value, dict):
        for key in ("id", "item", "name"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                item, _note = map_block_id(raw, is_item=True)
                count = value.get("count")
                amount = int(count) if isinstance(count, (int, float)) and count > 0 else 1
                return item, amount
        nested = value.get("result")
        if nested is not None:
            return _result(nested)
    if isinstance(value, list) and value:
        return _result(value[0])
    return None, 0


def _pattern_symbols(pattern: list[Any]) -> list[str]:
    symbols: list[str] = []
    for row in pattern:
        for char in str(row):
            if char.strip() and char not in symbols:
                symbols.append(char)
    return symbols


def _expanded(axes: list[list[str]]) -> tuple[list[tuple[str, ...]], bool]:
    """Cartesian product of the slot options, truncated at ``MAX_VARIANTS``.

    Returns the combinations and whether anything had to be dropped, so the
    caller can mark the recipe partial instead of quietly shrinking a tag.
    """
    if not axes:
        return [()], False
    combos = [tuple(combo) for combo in product(*axes)]
    if len(combos) <= MAX_VARIANTS:
        return combos, False
    return combos[:MAX_VARIANTS], True


def _identifier_for(identifier: str, index: int) -> str:
    if index == 0:
        return identifier
    namespace, name = split_id(identifier)
    return f"{namespace}:{name}_{index + 1}"


# ---------------------------------------------------------------------------
# converter
# ---------------------------------------------------------------------------
def convert_recipe(feature: Feature, ctx: ConversionContext) -> None:
    payload = feature.data.get("recipe") or {}
    recipe_type = str(payload.get("type") or feature.data.get("type") or "")
    identifier = str(feature.data.get("recipe_id") or feature.id)
    namespace, name = split_id(identifier)
    base_stem = slugify(f"{namespace}_{name}")
    tags = getattr(ctx, "tags", None)
    tag_losses: list[str] = []
    expansions: dict[str, int] = {}

    # -- Create-style machine recipes --------------------------------------
    if recipe_type == "create:mechanical_crafting":
        _convert_mechanical_crafting(feature, ctx, payload, identifier, base_stem, tags)
        return
    machine = station_for_type(recipe_type)
    if machine is not None:
        _convert_machine_recipe(feature, ctx, machine, payload, identifier, base_stem, tags)
        return

    # -- the type decides everything; check it before touching the result --
    handled = (
        recipe_type in CRAFTING_TYPES
        or recipe_type in COOKING_TYPES
        or recipe_type in STONECUTTING_TYPES
    )
    if not handled:
        feature.set_result("unsupported", 0.0, "recipe_manual")
        if recipe_type in UNSUPPORTED_TYPES:
            feature.add_issue(
                "warning",
                "RECIPE_TYPE_UNSUPPORTED",
                "Smithing recipes (template + base + addition) have no Bedrock recipe schema.",
                "Rebuild as a custom crafting-table recipe, or implement it with the Script API.",
            )
        else:
            feature.add_issue(
                "info",
                "RECIPE_TYPE_UNSUPPORTED",
                f"`{recipe_type}` is a custom recipe type; Bedrock has no schema for it.",
                "Recreate it as a custom block entity or via the Script API.",
            )
        ctx.count("recipes_unsupported")
        return

    result_item, count = _result(payload.get("result") if "result" in payload else payload.get("output"))
    if result_item is not None and not _known(result_item, ctx):
        feature.set_result("unsupported", 0.0, "recipe_foreign_result")
        feature.add_issue(
            "info",
            "RECIPE_FOREIGN_RESULT",
            f"The recipe produces `{result_item}`, which this pack does not define.",
            "It is a compat recipe for another mod; leaving it out keeps the recipe book free of "
            "entries that can never be crafted. Convert that mod as well to enable it.",
        )
        ctx.count("recipes_unsupported")
        ctx.count("recipes_foreign")
        return
    if result_item is None:
        feature.set_result("unsupported", 0.0, "recipe_no_result")
        feature.add_issue(
            "warning",
            "RECIPE_RESULT_UNRESOLVED",
            "The recipe output could not be read from `result`/`output`.",
            "No file was written: a recipe that produces the wrong item is worse than no recipe.",
        )
        ctx.count("recipes_unsupported")
        return

    documents: list[dict[str, Any]] = []
    block_name = "recipe"

    if recipe_type == "minecraft:crafting_shaped":
        pattern = payload.get("pattern") or []
        key = payload.get("key") or {}
        if not isinstance(pattern, list) or not isinstance(key, dict) or not pattern:
            feature.set_result("unsupported", 0.0, "recipe_invalid")
            feature.add_issue("error", "RECIPE_INVALID", "Shaped recipe is missing a pattern or key.")
            ctx.count("recipes_unsupported")
            return

        symbols = _pattern_symbols(pattern)
        axes: list[list[str]] = []
        for symbol in symbols:
            ingredient = key.get(symbol)
            if ingredient is None:
                feature.set_result("unsupported", 0.0, "recipe_pattern_incomplete")
                feature.add_issue(
                    "error",
                    "RECIPE_PATTERN_INCOMPLETE",
                    f"Pattern uses symbol `{symbol}` that has no entry in `key`.",
                    "The recipe was not written: Bedrock rejects a pattern whose symbol is absent from `key`.",
                )
                ctx.count("recipes_unsupported")
                return
            options, source_tag = _options_for(ingredient, tags, ctx)
            if source_tag:
                expansions[source_tag] = len(options)
                if len(options) <= 1:
                    tag_losses.append(source_tag)
            if not options:
                feature.set_result("unsupported", 0.0, "recipe_pattern_incomplete")
                feature.add_issue(
                    "warning",
                    "RECIPE_UNRESOLVED_INGREDIENT",
                    f"Recipe skipped: symbol `{symbol}` points at `{_tag_name(ingredient) or ingredient}`, "
                    "which has no counterpart in this pack, and no JSON was written.",
                    "A recipe with a missing ingredient would load as an uncraftable dead entry, "
                    "so nothing is emitted. Rebuild it by hand once the ingredient exists.",
                )
                ctx.count("recipes_unsupported")
                return
            axes.append(options)

        combos, truncated = _expanded(axes)
        if truncated:
            tag_losses.append(f"{len(axes)} tagged slots (only {MAX_VARIANTS} combinations kept)")
        for index, combo in enumerate(combos):
            bedrock_key = {symbol: {"item": item} for symbol, item in zip(symbols, combo)}
            documents.append(
                {
                    "format_version": "1.20.10",
                    "minecraft:recipe_shaped": {
                        "description": {"identifier": _identifier_for(identifier, index)},
                        "tags": ["crafting_table"],
                        "pattern": [str(row) for row in pattern],
                        "key": bedrock_key,
                        "result": {"item": result_item, "count": count},
                    },
                }
            )
        block_name = "recipe_shaped"

    elif recipe_type == "minecraft:crafting_shapeless":
        raw_ingredients = payload.get("ingredients") or []
        if not isinstance(raw_ingredients, list) or not raw_ingredients:
            feature.set_result("unsupported", 0.0, "recipe_invalid")
            feature.add_issue("error", "RECIPE_INVALID", "Shapeless recipe has no usable ingredients.")
            ctx.count("recipes_unsupported")
            return
        axes = []
        for slot, ingredient in enumerate(raw_ingredients):
            options, source_tag = _options_for(ingredient, tags, ctx)
            if source_tag:
                expansions[source_tag] = len(options)
                if len(options) <= 1:
                    tag_losses.append(source_tag)
            if not options:
                feature.set_result("unsupported", 0.0, "recipe_invalid")
                feature.add_issue(
                    "warning",
                    "RECIPE_UNRESOLVED_INGREDIENT",
                    f"Recipe skipped: shapeless ingredient {slot + 1} has no Bedrock counterpart, "
                    "and no XML was written.",
                    "The recipe was not written rather than shipped with a missing ingredient.",
                )
                ctx.count("recipes_unsupported")
                return
            axes.append(options)

        combos, truncated = _expanded(axes)
        if truncated:
            tag_losses.append(f"{len(axes)} tagged slots (only {MAX_VARIANTS} combinations kept)")
        for index, combo in enumerate(combos):
            documents.append(
                {
                    "format_version": "1.20.10",
                    "minecraft:recipe_shapeless": {
                        "description": {"identifier": _identifier_for(identifier, index)},
                        "tags": ["crafting_table"],
                        "ingredients": [{"item": item} for item in combo],
                        "result": {"item": result_item, "count": count},
                    },
                }
            )
        block_name = "recipe_shapeless"

    elif recipe_type in COOKING_TYPES:
        raw_input = payload.get("ingredient")
        options, source_tag = _options_for(raw_input, tags, ctx)
        if source_tag:
            expansions[source_tag] = len(options)
            if len(options) <= 1:
                tag_losses.append(source_tag)
        if not options:
            feature.set_result("unsupported", 0.0, "recipe_invalid")
            feature.add_issue(
                "error",
                "RECIPE_INVALID",
                "Cooking recipe has no usable input ingredient.",
                "The recipe was not written rather than shipped with a missing ingredient.",
            )
            ctx.count("recipes_unsupported")
            return
        station_tags = ["furnace"]
        if recipe_type == "minecraft:blasting":
            station_tags.append("blast_furnace")
        elif recipe_type == "minecraft:smoking":
            station_tags.append("smoker")
        combos, truncated = _expanded([options])
        if truncated:
            feature.add_limitation(
                f"The input tag has {len(options)} members; only the first {MAX_VARIANTS} got a recipe."
            )
        for index, (item,) in enumerate(combos):
            documents.append(
                {
                    "format_version": "1.20.10",
                    "minecraft:recipe_furnace": {
                        "description": {"identifier": _identifier_for(identifier, index)},
                        "tags": station_tags,
                        "input": {"item": item},
                        "output": {"item": result_item, "count": count},
                    },
                }
            )
        feature.add_assumption(
            f"Java `{recipe_type.split(':')[-1]}` mapped to a Bedrock furnace recipe with the "
            f"{'/'.join(station_tags[1:]) or 'furnace'} station list; experience rewards are not represented."
        )
        block_name = "recipe_furnace"

    else:  # stonecutting
        options, source_tag = _options_for(payload.get("ingredient"), tags, ctx)
        if source_tag:
            expansions[source_tag] = len(options)
            if len(options) <= 1:
                tag_losses.append(source_tag)
        if not options:
            feature.set_result("unsupported", 0.0, "recipe_invalid")
            feature.add_issue(
                "error",
                "RECIPE_INVALID",
                "Stonecutting recipe has no usable input ingredient.",
                "The recipe was not written rather than shipped with a missing ingredient.",
            )
            ctx.count("recipes_unsupported")
            return
        combos, truncated = _expanded([options])
        if truncated:
            feature.add_limitation(
                f"The input tag has {len(options)} members; only the first {MAX_VARIANTS} got a recipe."
            )
        for index, (item,) in enumerate(combos):
            documents.append(
                {
                    "format_version": "1.20.10",
                    "minecraft:recipe_shapeless": {
                        "description": {"identifier": _identifier_for(identifier, index)},
                        "tags": ["stonecutter"],
                        "ingredients": [{"item": item}],
                        "result": {"item": result_item, "count": count},
                    },
                }
            )
        block_name = "recipe_stonecutter"

    # -- write ------------------------------------------------------------
    written: list[str] = []
    for index, doc in enumerate(documents):
        stem = base_stem if index == 0 else f"{base_stem}_{index + 1}"
        ctx.writer.write_bp(f"recipes/{stem}.json", doc)
        written.append(f"behavior_pack/recipes/{stem}.json")
    for path in written:
        feature.add_output(path)

    if len(written) > 1:
        detail = ", ".join(f"`{tag}` ({size} items)" for tag, size in sorted(expansions.items()) if size > 1)
        feature.add_assumption(
            f"Tag ingredients were expanded into {len(written)} separate Bedrock recipes"
            + (f" over {detail}" if detail else "")
            + ". Bedrock matches one item per slot, so each tag member needs its own recipe."
        )
        feature.add_issue(
            "info",
            "RECIPE_TAG_EXPANDED",
            f"{len(written)} recipes were written for one Java recipe to cover every tag member.",
            "All of them are required; deleting one removes that item's crafting path.",
        )

    unique_losses = sorted({loss for loss in tag_losses if loss})
    if unique_losses:
        feature.add_limitation(
            "Ingredient tags collapsed to one representative item: " + ", ".join(unique_losses)
            + ". Bedrock recipes accept a single item per slot, so other tag members no longer work."
        )
        feature.add_issue(
            "info",
            "RECIPE_TAG_COLLAPSED",
            "A tag ingredient was replaced by its representative item.",
            "Edit the generated recipe to change which item is accepted.",
        )

    status = "partial" if unique_losses else "converted"
    confidence = 0.9 if status == "converted" else 0.65
    if unique_losses:
        feature.set_result(status, confidence, block_name)
    elif len(written) > 1:
        feature.set_result(status, 0.85, block_name)
    else:
        feature.set_result(status, confidence, block_name)
    ctx.count("recipes")
    if len(written) > 1:
        ctx.count("recipe_variants", len(written) - 1)


# ---------------------------------------------------------------------------
# machine recipes
# ---------------------------------------------------------------------------
def _station_tag(machine: Machine, ctx: ConversionContext) -> str:
    """Where the recipe must be made: the machine's own block, or a workbench."""
    if machine.tag in ctx.stations:
        return machine.tag
    if ctx.options.machine_workbench:
        return "crafting_table"
    return ""


def _convert_machine_recipe(
    feature: Feature,
    ctx: ConversionContext,
    machine: Machine,
    payload: dict[str, Any],
    identifier: str,
    base_stem: str,
    tags: Any,
) -> None:
    station = _station_tag(machine, ctx)
    if not station:
        feature.set_result("manual", 0.15, "machine_station_missing")
        feature.add_issue(
            "warning",
            "MACHINE_STATION_MISSING",
            f"`{feature.display}` runs on `{machine.block_id}`, which is not in the generated pack.",
            f"Without that block there is nowhere for the recipe to run, so nothing was written. "
            f"Build the {machine.label} as a custom block, or convert again with"
            f" --machine-workbench to make it a plain crafting-table recipe.",
        )
        ctx.count("recipes_unsupported")
        return

    raw_ingredients = _ingredient_list(payload)
    if not raw_ingredients:
        feature.set_result("unsupported", 0.0, "recipe_invalid")
        feature.add_issue(
            "error",
            "RECIPE_INVALID",
            "The machine recipe has no item inputs (it may consume only fluid).",
            "No recipe was written: Bedrock cannot express a fluid-only craft.",
        )
        ctx.count("recipes_unsupported")
        return

    axes: list[list[str]] = []
    for slot, ingredient in enumerate(raw_ingredients):
        options, source_tag = _options_for(ingredient, tags, ctx)
        if not options:
            feature.set_result("unsupported", 0.0, "recipe_invalid")
            feature.add_issue(
                "warning",
                "RECIPE_UNRESOLVED_INGREDIENT",
                f"Machine ingredient {slot + 1} has no counterpart in this pack; nothing was written.",
                "Either the item belongs to a mod that is not installed, or it was not converted. "
                "A recipe with a missing ingredient loads as an uncraftable dead entry.",
            )
            ctx.count("recipes_unsupported")
            return
        axes.append(options)

    declared = _read_outputs(payload)
    outputs = [entry for entry in declared if _known(entry.item, ctx)]
    primary, promoted = primary_outputs(outputs)
    if not primary:
        if declared:
            feature.set_result("unsupported", 0.0, "recipe_foreign_result")
            feature.add_issue(
                "info",
                "RECIPE_FOREIGN_RESULT",
                f"The recipe only produces items this pack does not define "
                f"(`{declared[0].item}`).",
                "It is a compat recipe for another mod; nothing was written so the pack has no "
                "recipe that can never pay out.",
            )
        else:
            feature.set_result("unsupported", 0.0, "recipe_no_result")
            feature.add_issue(
                "warning",
                "RECIPE_RESULT_UNRESOLVED",
                "The machine recipe declares no readable result item.",
                "Nothing was written rather than guessing the output.",
            )
        ctx.count("recipes_unsupported")
        return

    dropped = [entry for entry in outputs if entry.chance < 1.0]
    combos, truncated = _expanded(axes)
    written: list[str] = []
    seen: set[str] = set()
    for combo in combos:
        for output in primary:
            if len(written) >= MAX_VARIANTS:
                truncated = True
                break
            key = "|".join(combo) + "->" + output.item
            if key in seen:
                continue
            seen.add(key)
            index = len(written)
            stem = base_stem if index == 0 else f"{base_stem}_{index + 1}"
            document = {
                "format_version": "1.20.10",
                "minecraft:recipe_shapeless": {
                    "description": {"identifier": _identifier_for(identifier, index)},
                    "tags": [station],
                    "ingredients": [{"item": item} for item in combo],
                    "result": {"item": output.item, "count": output.count},
                },
            }
            ctx.writer.write_bp(f"recipes/{stem}.json", document)
            written.append(f"behavior_pack/recipes/{stem}.json")

    if not written:  # pragma: no cover - every path above needs a combo
        feature.set_result("unsupported", 0.0, "recipe_invalid")
        ctx.count("recipes_unsupported")
        return

    for path in written:
        feature.add_output(path)

    where = (
        f"the converted {machine.label} block (custom crafting station `{station}`)"
        if station != "crafting_table"
        else "the vanilla crafting table"
    )
    feature.add_assumption(
        f"Java `{machine.recipe_type.split(':')[-1]}` was written as a Bedrock shapeless recipe "
        f"in {where}: the same ingredients give the same item, but the craft is instant."
    )
    feature.add_limitation(
        f"The Java recipe runs on the {machine.label} with rotation, stress and a processing "
        f"time of {payload.get('processing_time', 'unspecified')} ticks; Bedrock runs it as an "
        f"instant hand craft, so machines are decorative-but-usable rather than kinetic."
    )
    if promoted:
        best = primary[0]
        feature.add_limitation(
            f"No result is guaranteed in the Java recipe; `{best.item}` "
            f"({round(best.chance * 100)} % chance) was promoted to the guaranteed output. "
            "The others remain unobtainable from this recipe."
        )
    if dropped:
        listing = ", ".join(f"{entry.item} ({round(entry.chance * 100)} %)" for entry in dropped[:4])
        feature.add_limitation(
            f"Chance-based byproducts cannot be expressed: {listing} no longer drop."
            + (" …" if len(dropped) > 4 else "")
        )
    fluids = [
        entry
        for key in ("targets", "ingredients", "ingredient")
        for entry in (
            payload.get(key) if isinstance(payload.get(key), list)
            else [payload.get(key)] if payload.get(key) else []
        )
        if is_fluid(entry)
    ]
    if fluids:
        feature.add_limitation(
            f"{len(fluids)} fluid ingredient(s) were dropped; the craft only checks the items."
        )
    if truncated:
        feature.add_limitation(
            f"Only the first {MAX_VARIANTS} ingredient/output combinations were written; "
            "the remaining tag members craft nothing."
        )

    feature.add_issue(
        "info",
        "MACHINE_AS_STATION",
        f"Written as a shapeless recipe for the custom station `{station}`.",
        f"Place the {machine.label} block and use it: the Bedrock UI for a custom station only "
        f"lists the recipes tagged `{station}`.",
    )
    feature.set_result("partial", 0.6, "machine_station")
    ctx.count("recipes")
    ctx.count("machine_recipes")


def _convert_mechanical_crafting(
    feature: Feature,
    ctx: ConversionContext,
    payload: dict[str, Any],
    identifier: str,
    base_stem: str,
    tags: Any,
) -> None:
    """Mechanical crafting is a shaped recipe on a grid up to 9x9.

    A pattern that already fits a 3x3 crafting table is the *same* recipe, so it
    is written as one. Anything larger has no honest Bedrock equivalent and is
    listed for manual work by the knowledge base.
    """
    pattern = payload.get("pattern") or []
    key = payload.get("key") or {}
    fits = (
        isinstance(pattern, list)
        and 0 < len(pattern) <= 3
        and all(isinstance(row, str) and len(row) <= 3 for row in pattern)
    )
    if not fits or not isinstance(key, dict):
        feature.set_result("manual", 0.15, "mechanical_crafting_large")
        feature.add_issue(
            "warning",
            "MACHINE_MANUAL",
            INEXPRESSIBLE["create:mechanical_crafting"],
            "Keep the recipe in the manual checklist: the mechanical crafter needs a custom "
            "block with a multi-step grid, which is Script API work.",
        )
        ctx.count("recipes_unsupported")
        return

    result_item, count = _result(payload.get("result") or payload.get("output"))
    if result_item is None:
        feature.set_result("unsupported", 0.0, "recipe_no_result")
        ctx.count("recipes_unsupported")
        return

    symbols = _pattern_symbols(pattern)
    bedrock_key: dict[str, Any] = {}
    for symbol in symbols:
        options, _tag = _options_for(key.get(symbol), tags, ctx)
        if not options:
            feature.set_result("unsupported", 0.0, "recipe_pattern_incomplete")
            feature.add_issue(
                "warning",
                "RECIPE_UNRESOLVED_INGREDIENT",
                f"Mechanical crafting symbol `{symbol}` has no Bedrock counterpart.",
                "Nothing was written rather than shipping an uncraftable pattern.",
            )
            ctx.count("recipes_unsupported")
            return
        if len(options) > 1:
            feature.add_limitation(
                f"Symbol `{symbol}` accepted a tag; only `{options[0]}` is accepted in Bedrock."
            )
        bedrock_key[symbol] = {"item": options[0]}

    document = {
        "format_version": "1.20.10",
        "minecraft:recipe_shaped": {
            "description": {"identifier": identifier},
            "tags": ["crafting_table"],
            "pattern": [str(row) for row in pattern],
            "key": bedrock_key,
            "result": {"item": result_item, "count": count},
        },
    }
    ctx.writer.write_bp(f"recipes/{base_stem}.json", document)
    feature.add_output(f"behavior_pack/recipes/{base_stem}.json")
    feature.add_assumption(
        "The mechanical crafter's 3x3-or-smaller pattern was written as a normal shaped "
        "crafting recipe: same pattern, same result, made at a crafting table instead."
    )
    feature.set_result("partial", 0.6, "mechanical_crafting_small")
    ctx.count("recipes")
