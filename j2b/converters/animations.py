"""Convert GeckoLib bone clips into Bedrock resource-pack animation definitions.

GeckoLib 1.21.1, commit 94ccb576: BakedAnimationsAdapter.buildKeyframeStack
reads position components verbatim. RenderUtil.translateMatrixToBone applies
the model-unit-to-block conversion (/16) at render time. Both JSON formats use
model units, seconds and degrees. Renderer offsets/signs do not belong here.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any

from ..models import Feature
from .context import ConversionContext


# Shared single-expression MoLang. A mod can register arbitrary GeckoLib
# functions and queries, so recognizing a namespace alone is insufficient.
_FUNCTIONS = {"abs": 1, "sin": 1, "cos": 1, "floor": 1, "ceil": 1,
              "min": 2, "max": 2, "clamp": 3}
_QUERIES = {"anim_time", "distance_from_camera"}
_NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
_TOKEN = re.compile(rf"{_NUMBER}|[a-z]+\.[a-z_]+|[ +*/(),-]")


def _finite(value: Any) -> bool:
    if type(value) is int:
        return value.bit_length() < 1024
    return type(value) is float and math.isfinite(value)


def _shared_expression(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return _finite(node.value)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id == "query" and node.attr in _QUERIES
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub)) and _shared_expression(node.operand)
    if isinstance(node, ast.BinOp):
        return (isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div))
                and _shared_expression(node.left) and _shared_expression(node.right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        receiver = node.func.value
        return (isinstance(receiver, ast.Name) and receiver.id == "math"
                and len(node.args) == _FUNCTIONS.get(node.func.attr) and not node.keywords
                and all(_shared_expression(arg) for arg in node.args))
    return False


def _component(value: Any) -> int | float | str:
    if _finite(value):
        return value
    if isinstance(value, str):
        expression = re.sub(r"\bq\.", "query.", value.strip().lower())
        if 0 < len(expression) <= 512 and not _TOKEN.sub("", expression):
            try:
                if _shared_expression(ast.parse(expression, mode="eval").body):
                    return expression
            except (SyntaxError, RecursionError):
                pass
    raise ValueError(f"unsupported value or MoLang expression {value!r}")


def _vector(value: Any) -> list:
    if not isinstance(value, list):
        component = _component(value)
        return [component] * 3
    if len(value) != 3:
        raise ValueError("expected three vector components")
    return [_component(component) for component in value]


def _frame(value: Any, notes: set[str]) -> Any:
    if not isinstance(value, dict):
        return _vector(value)

    # GeckoLib wraps vectors with easing metadata. Bedrock uses a bare
    # vector for linear interpolation and pre/post for keyed interpolation.
    if "vector" in value:
        vector = _vector(value["vector"])
        easing = value.get("easing", "linear")
        if easing != "linear":
            notes.add(f"GeckoLib easing {easing!r} was replaced with linear interpolation.")
        if "easingArgs" in value:
            notes.add("GeckoLib easing arguments were omitted.")
        extra = value.keys() - {"vector", "easing", "easingArgs"}
        result = vector
    else:
        result = {}
        for side in ("pre", "post"):
            if side in value:
                point = value[side]
                if isinstance(point, dict) and set(point) == {"vector"}:
                    point = point["vector"]
                result[side] = _vector(point)
        if not result:
            raise ValueError("keyframe has no vector, pre or post value")
        if "lerp_mode" in value:
            mode = value["lerp_mode"]
            if mode in ("linear", "catmullrom"):
                result["lerp_mode"] = mode
            else:
                notes.add(f"Interpolation {mode!r} was replaced with linear interpolation.")
        extra = value.keys() - {"pre", "post", "lerp_mode"}
    for field in sorted(extra):
        notes.add(f"Keyframe field {field!r} was omitted.")
    return result


def _channel(value: Any, notes: set[str]) -> Any:
    if not isinstance(value, dict) or "vector" in value:
        return _frame(value, notes)
    if not value:
        raise ValueError("empty keyframe track")
    frames = {}
    times = set()
    for key, frame in value.items():
        if not re.fullmatch(_NUMBER, key) or not math.isfinite(time := float(key)) or time in times:
            raise ValueError(f"invalid or duplicate timestamp {key!r}")
        times.add(time)
        try:
            timestamp = f"0{key}" if key.startswith(".") else key
            frames[timestamp] = _frame(frame, notes)
        except ValueError as error:
            raise ValueError(f"at {key}s: {error}") from error
    return frames


def _convert_clip(clip: dict, feature: Feature) -> dict:
    output: dict[str, Any] = {}
    for field in sorted(clip.keys() - {"loop", "animation_length", "bones"}):
        feature.add_limitation(f"Clip field {field!r} was omitted.")
    if "loop" in clip:
        loop = clip["loop"]
        if isinstance(loop, bool) or loop == "hold_on_last_frame":
            output["loop"] = loop
        elif loop in ("true", "loop", "false", "play_once"):
            output["loop"] = loop in ("true", "loop")
        else:
            feature.add_limitation(f"Unknown loop mode {loop!r} was omitted.")
    if "animation_length" in clip:
        length = clip["animation_length"]
        if _finite(length) and length >= 0:
            output["animation_length"] = length
        else:
            feature.add_limitation("Invalid animation_length was omitted.")

    bones = {}
    source = clip.get("bones")
    if isinstance(source, dict):
        for name, bone in source.items():
            if not name or not isinstance(bone, dict):
                feature.add_limitation(f"Malformed bone {name!r} was omitted.")
                continue
            tracks = {}
            for channel, value in bone.items():
                if channel not in ("position", "rotation", "scale"):
                    feature.add_limitation(f"{name}: channel {channel!r} was omitted.")
                    continue
                notes: set[str] = set()
                try:
                    tracks[channel] = _channel(value, notes)
                except ValueError as error:
                    feature.add_limitation(f"{name}.{channel} was omitted: {error}.")
                    continue
                for note in sorted(notes):
                    feature.add_limitation(f"{name}.{channel}: {note}")
            if tracks:
                bones[name] = tracks
    if bones:
        output["bones"] = bones
    return output


def convert_animation(feature: Feature, ctx: ConversionContext) -> None:
    clip = feature.data.get("clip")
    if not feature.name or not isinstance(clip, dict):
        feature.add_limitation("Expected a named animation object inside an animations map.")
        feature.set_result("manual", 0.0, "animation_unreadable")
        return
    version = feature.data.get("format_version")
    if version not in (None, "1.8.0"):
        feature.add_limitation(f"Source format {version!r} was interpreted using the 1.8.0 track format.")
    converted = _convert_clip(clip, feature)
    if "bones" not in converted:
        if not feature.limitations and clip.get("bones", {}) == {}:
            feature.add_limitation("The source clip declares no bone movement or events.")
            feature.set_result("skipped", 1.0, "animation_empty")
            return
        feature.add_limitation("No usable bone track remains. Rebuild this clip manually.")
        feature.set_result("manual", 0.0, "animation_manual")
        return
    identifier = feature.data["identifier"]
    path = f"animations/{identifier}.animation.json"
    ctx.writer.write_rp(path, {"format_version": "1.8.0", "animations": {identifier: converted}})
    feature.add_output(f"resource_pack/{path}")
    feature.add_assumption(f"Bind {identifier!r} in the client entity. Playback conditions live in the mod's code.")
    if feature.limitations:
        feature.set_result("partial", 0.55, "animation_approximate")
    else:
        feature.set_result("converted", 1.0, "animation_exact")
    ctx.count("animation_clips_written")
