"""Worldgen conversion.

Only ore-style configured features are converted, because Bedrock has a
first-class ``minecraft:ore_feature``. Trees, structures, carvers and custom
noise features are reported as manual work: pretending to port them would
produce worlds that look nothing like the Java mod.
"""

from __future__ import annotations

from typing import Any

from ..id_map import map_block_id
from ..models import Feature
from ..utils import split_id
from .context import ConversionContext

MAX_RULE_ITERATIONS = 40


def _base_id(feature: Feature) -> str:
    return str(feature.data.get("base_id") or feature.id)


def _ore_config(feature: Feature) -> dict[str, Any] | None:
    data = feature.data.get("json") or {}
    if not isinstance(data, dict) or data.get("type") != "minecraft:ore":
        return None
    config = data.get("config") or {}
    return config if isinstance(config, dict) else None


def _placement(feature: Feature, ctx: ConversionContext) -> dict[str, Any]:
    """Find the placed_feature that references this configured feature."""
    target = _base_id(feature)
    for candidate in getattr(ctx, "features", []):
        if candidate.kind != "worldgen" or candidate.data.get("category") != "placed_feature":
            continue
        payload = candidate.data.get("json") or {}
        if str(payload.get("feature") or "") == target:
            return payload
    return {}


def _y_extent(placement: dict[str, Any]) -> tuple[int, int]:
    for step in placement.get("placement") or []:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "minecraft:height_range":
            height = step.get("height") or {}
            minimum = _height_value(height.get("min_inclusive"))
            maximum = _height_value(height.get("max_inclusive"))
            if minimum is not None and maximum is not None:
                return minimum, maximum
        if step.get("type") == "minecraft:heightmap":
            return -60, 60
    return -60, 60


def _height_value(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        absolute = value.get("absolute")
        if isinstance(absolute, (int, float)):
            return int(absolute)
    return None


def _count(placement: dict[str, Any], fallback: int) -> int:
    for step in placement.get("placement") or []:
        if isinstance(step, dict) and step.get("type") == "minecraft:count":
            count = step.get("count")
            if isinstance(count, (int, float)):
                return max(1, int(count))
            if isinstance(count, dict):
                low = count.get("min_inclusive") or count.get("min")
                high = count.get("max_inclusive") or count.get("max") or low
                if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                    return max(1, int(round((low + high) / 2)))
    return max(1, fallback)


def convert_worldgen(feature: Feature, ctx: ConversionContext) -> None:
    base_id = _base_id(feature)
    namespace, name = split_id(base_id)
    file_stem = f"{namespace}_{name}".replace("/", "_").replace(":", "_")
    category = feature.data.get("category")

    if category == "placed_feature":
        referenced = str((feature.data.get("json") or {}).get("feature") or "")
        for candidate in getattr(ctx, "features", []):
            if (
                candidate.kind == "worldgen"
                and candidate.data.get("category") == "configured_feature"
                and _base_id(candidate) == referenced
            ):
                feature.set_result("skipped", 1.0, "placement_used_by_configured_feature")
                feature.add_issue(
                    "info",
                    "PLACEMENT_FOLDED",
                    "Placement settings were applied to the converted ore feature rule.",
                )
                return
        feature.set_result("manual", 0.05, "worldgen_manual")
        feature.add_issue(
            "warning",
            "WORLDGEN_MANUAL",
            "Placed feature without a converted configured feature.",
            "Only ore features are generated automatically.",
        )
        return

    if category != "configured_feature":
        feature.set_result("manual", 0.05, "worldgen_manual")
        feature.add_issue(
            "warning",
            "WORLDGEN_MANUAL",
            f"`{category}` content has no automatic Bedrock equivalent.",
            "Structures, carvers, tree shapes and custom features must be rebuilt with Bedrock features "
            "or the Script API; a mechanical translation would not match the Java output.",
        )
        return

    config = _ore_config(feature)
    if config is None:
        feature.set_result("manual", 0.1, "worldgen_not_ore")
        feature.add_issue(
            "warning",
            "WORLDGEN_NOT_ORE",
            "Only `minecraft:ore` configured features are converted automatically.",
            "Other feature types (trees, flowers, geode, custom) need hand-built Bedrock features.",
        )
        return

    replace_rules: list[dict[str, Any]] = []
    for target in config.get("targets") or []:
        if not isinstance(target, dict):
            continue
        state = target.get("state") or {}
        block = state.get("Name") if isinstance(state, dict) else None
        if not block:
            continue
        bedrock_block, note = map_block_id(str(block))
        if note:
            feature.add_limitation(note)
        may_replace: list[str] = []
        target_block = (target.get("target") or {}).get("block")
        if target_block:
            mapped, _note = map_block_id(str(target_block))
            may_replace = [mapped]
        entry: dict[str, Any] = {"places_block": bedrock_block}
        if may_replace:
            entry["may_replace"] = may_replace
        replace_rules.append(entry)

    if not replace_rules:
        feature.set_result("manual", 0.1, "worldgen_no_targets")
        feature.add_issue("warning", "WORLDGEN_NO_TARGETS", "Ore configuration has no usable target states.")
        return

    size = config.get("size")
    count = int(size) if isinstance(size, (int, float)) and size > 0 else 8
    feature_doc = {
        "format_version": "1.13.0",
        "minecraft:ore_feature": {
            "description": {"identifier": base_id},
            "count": count,
            "replace_rules": replace_rules,
        },
    }
    ctx.writer.write_bp(f"features/{file_stem}.json", feature_doc)
    feature.add_output(f"behavior_pack/features/{file_stem}.json")

    placement = _placement(feature, ctx)
    iterations = min(MAX_RULE_ITERATIONS, _count(placement, 1))
    y_min, y_max = _y_extent(placement)
    rule_doc = {
        "format_version": "1.13.0",
        "minecraft:feature_rules": {
            "description": {
                "identifier": f"{base_id}_rule",
                "places_feature": base_id,
            },
            "conditions": {
                "placement_pass": "underground_pass",
                "minecraft:biome_filter": [{"test": "has_biome_tag", "operator": "==", "value": "overworld"}],
            },
            "distribution": {
                "iterations": iterations,
                "coordinate_eval_order": "zyx",
                "x": {"distribution": "uniform", "extent": [0, 16]},
                "z": {"distribution": "uniform", "extent": [0, 16]},
                "y": {"distribution": "uniform", "extent": [y_min, y_max]},
            },
        },
    }
    ctx.writer.write_bp(f"feature_rules/{file_stem}_rule.json", rule_doc)
    feature.add_output(f"behavior_pack/feature_rules/{file_stem}_rule.json")
    ctx.count("worldgen_features")

    feature.add_assumption(
        f"Ore size {count} from the configured feature; placement uses {iterations} iterations "
        f"between y={y_min} and y={y_max}."
    )
    if not placement:
        feature.add_limitation(
            "No placed feature was found, so placement (biome, height, count) had to be assumed."
        )
    feature.set_result("converted" if placement else "partial", 0.8 if placement else 0.55, "worldgen_ore")
