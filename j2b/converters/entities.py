"""Entity conversion.

Java entities are implemented in code (class + model + renderer); Bedrock
entities need a behaviour definition, a geometry (Blockbench/GeckoLib) and a
texture. Only the texture can be carried across mechanically, so this engine
does exactly that and reports the entity as manual work instead of emitting a
placeholder mob that would behave like nothing.
"""

from __future__ import annotations

from ..models import Feature
from ..utils import split_id
from .context import ConversionContext


def convert_entity_feature(feature: Feature, ctx: ConversionContext) -> None:
    _namespace, name = split_id(feature.id)

    copied: list[str] = []
    for candidate in feature.data.get("texture_candidates") or []:
        key = ctx.textures.use_generic(candidate)
        if key:
            copied.append(key)

    feature.set_result("manual", 0.15, "entity_rebuild")
    feature.add_issue(
        "warning",
        "ENTITY_NEEDS_REBUILD",
        "Java entities cannot be translated mechanically: the model format, renderer and AI are code, not data.",
        "Bedrock needs a behaviour-pack entity definition, a Bedrock geometry (Blockbench or GeckoLib) "
        "and an animation controller; the Java model cannot be reused as-is.",
    )
    feature.add_limitation(
        "Health, hitbox, spawn rules, loot and AI goals live in Java code and were not recovered."
    )
    if copied:
        feature.add_assumption(
            "Entity textures were copied to the resource pack as reference art for the rebuild."
        )
        ctx.count("entity_textures", len(copied))
    else:
        feature.add_limitation("No entity texture was found in the jar for this entity.")

    if feature.data.get("entity_type_json"):
        feature.add_limitation(
            "The datapack entity_type JSON was detected, but Bedrock has no datapack entity type "
            "that can be registered from data alone."
        )
    ctx.count("entities_reported")
