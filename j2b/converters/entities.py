"""Entity conversion.

Java entities are implemented in code (class + model + renderer); Bedrock
entities need a behaviour definition, a geometry (Blockbench/GeckoLib) and a
texture. The behaviour half is genuinely code and cannot be recovered, but the
*visible* half often can: mods ship GeckoLib ``.geo.json`` or Blockbench
``.bbmodel`` files, and both translate (see
:mod:`j2b.converters.entity_models`). When a model is found it is written into
the resource pack and the entity is reported as partial; when the model lives
only in code, the entity is reported as manual and nothing is invented.
"""

from __future__ import annotations

from ..models import Feature
from ..utils import split_id
from .context import ConversionContext
from .entity_models import bone_count, convert_model

#: Bedrock identifiers are ``[a-z0-9_.]``; a character outside this set makes the
#: geometry silently fail to load, so it is normalised here rather than hoped for.
_IDENTIFIER_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789_.")


def _slug(value: str) -> str:
    cleaned = "".join(char if char in _IDENTIFIER_SAFE else "_" for char in value.lower())
    return cleaned.strip("_") or "entity"


def convert_entity_feature(feature: Feature, ctx: ConversionContext) -> None:
    # ``feature.id`` is ``namespace:entity:name``, so the namespace is the first
    # segment and the entity name is everything after ``entity:`` -- not
    # ``split_id``'s tail, which would keep the ``entity:`` prefix and produce
    # ``geometry.ns.entity:name``, an identifier Bedrock refuses to load.
    namespace, _rest = split_id(feature.id)
    name = _slug(feature.name or feature.id.rsplit(":", 1)[-1])

    copied: list[str] = []
    for candidate in feature.data.get("texture_candidates") or []:
        key = ctx.textures.use_generic(candidate)
        if key:
            copied.append(key)

    geometries: list[tuple[str, int]] = []
    for index, path in enumerate(feature.data.get("model_candidates") or []):
        payload = ctx.archive.json(path)
        if not isinstance(payload, dict):
            feature.add_limitation(f"The entity model `{path}` is not readable JSON and was skipped.")
            continue
        # One entity gets one geometry identifier; extra models are kept as
        # variants rather than overwriting the first.
        identifier = f"geometry.{namespace}.{name}" if index == 0 else f"geometry.{namespace}.{name}_{index + 1}"
        try:
            document, notes = convert_model(payload, identifier)
        except (ValueError, TypeError, KeyError) as error:
            feature.add_issue(
                "warning",
                "ENTITY_MODEL_UNREADABLE",
                f"`{path}` looks like an entity model but could not be translated: {error}",
                "The entity is still reported as manual work; its texture (if any) was copied.",
            )
            continue
        for note in notes:
            feature.add_limitation(f"{path}: {note}")
        ctx.writer.write_rp(f"models/entity/{identifier.rsplit('.', 1)[-1]}.geo.json", document)
        geometries.append((identifier, bone_count(document)))

    if geometries:
        identifiers = ", ".join(identifier for identifier, _bones in geometries)
        bones = sum(count for _identifier, count in geometries)
        feature.add_assumption(
            f"Entity geometry was translated from the mod's own model file ({identifiers}), "
            f"{bones} bones. Pivots and UVs are the author's, not an approximation."
        )
        feature.add_limitation(
            "The entity definition is still missing: health, hitbox, spawn rules, loot and AI goals "
            "live in Java code. The geometry is real; the mob is not spawnable yet."
        )
    else:
        feature.add_limitation(
            "No GeckoLib or Blockbench model was shipped in the jar, so the model has to be rebuilt by hand."
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

    if geometries:
        # Half the work is done and provably correct; the behaviour half is not.
        feature.set_result("partial", 0.5, "entity_geometry")
        ctx.count("entity_geometry", len(geometries))
    else:
        feature.set_result("manual", 0.15, "entity_rebuild")
    feature.add_issue(
        "warning",
        "ENTITY_NEEDS_REBUILD",
        "Java entities cannot be translated mechanically: the renderer and AI are code, not data.",
        "Bedrock needs a behaviour-pack entity definition (health, hitbox, loot, AI goals). "
        "The model and texture are converted when the mod ships them.",
    )
    ctx.count("entities_reported")
