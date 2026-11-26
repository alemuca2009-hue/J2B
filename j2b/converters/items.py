"""Item conversion: icon + registration only.

An item's icon is whatever its model ultimately paints. Java models inherit, so
``item/foo`` may declare nothing and reach a block model three parents up; the
old code read only the item file's own ``textures`` map, found nothing, and
stamped the vanilla ``stick`` icon on every such item. The fallback below walks
the same inheritance chain the block converter uses and takes the first texture
the model actually resolves to.

A missing icon is still reported rather than hidden, and the placeholder is
declared in the pack's own atlas so it resolves instead of pointing at a key
nothing defines.
"""

from __future__ import annotations

from typing import Any

from ..models import Feature
from ..utils import slugify, split_id
from .context import ConversionContext

HANDHELD_PARENTS = ("item/handheld", "item/handheld_rod")
GENERATED_PARENTS = ("item/generated",)
PLACEHOLDER_KEY = "j2b_missing_item"

#: Texture variables consulted first when a model resolves to a block shape.
PREFERRED_KEYS = ("layer0", "layer1", "layer2", "texture", "all", "particle", "side", "top")


def _layer0(textures: dict[str, Any]) -> str | None:
    value = textures.get("layer0") or textures.get("layer1")
    if isinstance(value, str):
        return value
    for candidate in textures.values():
        if isinstance(candidate, str):
            return candidate
    return None


def _resolved_refs(feature: Feature, ctx: ConversionContext) -> list[str]:
    """Texture references reachable through the item's model chain."""
    resolver = getattr(ctx, "resolver", None)
    model_ref = str(feature.data.get("model_ref") or "")
    if resolver is None or not model_ref:
        return []
    namespace, _name = split_id(feature.id)
    try:
        model = resolver.resolve_for_block(model_ref, namespace)
    except Exception:  # pragma: no cover - resolver is defensive already
        return []
    ordered: list[str] = []
    for key in PREFERRED_KEYS:
        value = model.textures.get(key)
        if isinstance(value, str) and value and value not in ordered:
            ordered.append(value)
    for value in model.textures.values():
        if isinstance(value, str) and value and value not in ordered:
            ordered.append(value)
    return ordered


def _icon_key(feature: Feature, ctx: ConversionContext) -> tuple[str | None, str]:
    """Return ``(atlas_key, how)`` for the item icon."""
    namespace, name = split_id(feature.id)
    textures = feature.data.get("textures") or {}
    own = _layer0(textures)
    if own:
        key = ctx.textures.copy(own, "item", name)
        if key is not None:
            return key, "model textures"
    for ref in _resolved_refs(feature, ctx):
        key = ctx.textures.copy(ref, "item", name)
        if key is not None:
            return key, "inherited model texture"
    return None, ""


def convert_item(feature: Feature, ctx: ConversionContext) -> None:
    namespace, name = split_id(feature.id)
    stem = slugify(f"{namespace}_{name}")
    parent = str(feature.data.get("model_parent") or "").lower()

    texture_key, source = _icon_key(feature, ctx)
    missing_texture = texture_key is None
    if missing_texture:
        texture_key = PLACEHOLDER_KEY
        ctx.textures.ensure_placeholder(PLACEHOLDER_KEY)
        feature.add_limitation(
            "No texture could be resolved for this item through its model chain; the pack ships a "
            "checkerboard placeholder under its own atlas key so the gap is visible in-game."
        )
    elif source == "inherited model texture":
        feature.add_assumption(
            "The item declares no icon of its own; the first texture reached through its model "
            "parents is used as the icon."
        )

    lang_key = f"item.{feature.id}"
    doc = {
        "format_version": "1.20.10",
        "minecraft:item": {
            "description": {
                "identifier": feature.id,
                "menu_category": {"category": "equipment" if "handheld" in parent else "items"},
            },
            "components": {
                "minecraft:icon": {"texture": texture_key},
                "minecraft:display_name": {"value": lang_key},
                "minecraft:max_stack_size": 64,
            },
        },
    }
    ctx.writer.write_bp(f"items/{stem}.json", doc)
    ctx.writer.add_rp_lang(lang_key, feature.display or name.replace("_", " ").title())
    feature.add_output(f"behavior_pack/items/{stem}.json")

    if "handheld" in parent:
        feature.add_assumption("Tool/weapon layout detected; the item is emitted as a plain item with default stats.")
    elif not any(candidate in parent for candidate in GENERATED_PARENTS):
        feature.add_limitation(
            f"Model parent `{parent or 'none'}` is a custom model; only the icon is reproduced."
        )

    feature.add_limitation(
        "Stack size (64), durability, food values, tool tiers and enchantability live in Java code and are not "
        "recovered from assets."
    )
    if missing_texture:
        ctx.count("items_without_icon")
    status = "partial" if (missing_texture or "handheld" in parent) else "converted"
    feature.set_result(status, 0.8 if status == "converted" else 0.6, "item_model")
    ctx.count("items")
