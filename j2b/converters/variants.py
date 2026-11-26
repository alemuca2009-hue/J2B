"""Blockstate -> Bedrock states + permutations.

A Java blockstate is a table: each key names a combination of properties and
gives the model (plus rotation) used for it. Bedrock expresses the same thing
with ``description.states`` and ``permutations`` whose ``condition`` is a query.

Rotations are *baked into the geometry* instead of being handed to
``minecraft:transformation``. A quarter turn of an axis-aligned box is still an
axis-aligned box, so baking is exact, while Bedrock's transformation component
has its own axis conventions that are easy to get subtly wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any

FACE_NORMALS = {
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
}
NORMAL_FACES = {value: key for key, value in FACE_NORMALS.items()}
MAX_GEOMETRIES = 24


@dataclass
class Variant:
    model: str
    x: float = 0.0
    y: float = 0.0
    uvlock: bool = False
    weight: int = 1
    condition: dict[str, str] = field(default_factory=dict)


@dataclass
class StateProperty:
    name: str
    values: list[Any]
    kind: str  # "bool" | "int" | "string"


@dataclass
class BlockStatePlan:
    mode: str = "single"  # "single" | "variants" | "multipart"
    primary_model: str = ""
    variants: list[Variant] = field(default_factory=list)
    properties: list[StateProperty] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    supported: bool = True
    total_combinations: int = 0

    def state_query(self, name: str, value: Any) -> str:
        if isinstance(value, bool):
            return f"q.block_state('{name}') == {'true' if value else 'false'}"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"q.block_state('{name}') == {value:g}"
        return f"q.block_state('{name}') == '{value}'"


def _classify(values: list[str]) -> tuple[list[Any], str]:
    lowered = [value.strip().lower() for value in values]
    if set(lowered) <= {"true", "false"}:
        return [True, False] if "true" in lowered and "false" in lowered else (
            [True] if "true" in lowered else [False]
        ), "bool"
    if all(value.lstrip("-").isdigit() for value in lowered):
        numbers = sorted({int(value) for value in lowered})
        return numbers, "int"
    return sorted({value.strip() for value in values}), "string"


def _split_condition(key: str) -> dict[str, str]:
    condition: dict[str, str] = {}
    for chunk in str(key).split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        condition[name.strip()] = value.strip()
    return condition


def _entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def parse_blockstate(state: dict[str, Any]) -> BlockStatePlan:
    plan = BlockStatePlan()
    if not isinstance(state, dict) or not state:
        plan.supported = False
        plan.notes.append("The block has no blockstate file; nothing describes its variants.")
        return plan

    variants = state.get("variants")
    multipart = state.get("multipart")
    seen_properties: dict[str, set[str]] = {}

    if isinstance(variants, dict) and variants:
        plan.mode = "variants"
        for key, value in variants.items():
            condition = _split_condition(key)
            for name, raw in condition.items():
                seen_properties.setdefault(name, set()).add(str(raw))
            for entry in _entries(value):
                model = entry.get("model")
                if not isinstance(model, str) or not model:
                    continue
                plan.variants.append(
                    Variant(
                        model=model,
                        x=float(entry.get("x") or 0),
                        y=float(entry.get("y") or 0),
                        uvlock=bool(entry.get("uvlock")),
                        weight=int(entry.get("weight") or 1),
                        condition=condition,
                    )
                )
    elif isinstance(multipart, list) and multipart:
        plan.mode = "multipart"
        for part in multipart:
            if not isinstance(part, dict):
                continue
            when = part.get("when")
            if isinstance(when, dict):
                for name, raw in when.items():
                    if name in ("OR", "AND"):
                        continue
                    values = raw if isinstance(raw, list) else [raw]
                    for value in values:
                        if isinstance(value, str) and value.startswith("!"):
                            continue
                        seen_properties.setdefault(name, set()).add(str(value))
            for entry in _entries(part.get("apply")):
                model = entry.get("model")
                if not isinstance(model, str) or not model:
                    continue
                plan.variants.append(
                    Variant(
                        model=model,
                        x=float(entry.get("x") or 0),
                        y=float(entry.get("y") or 0),
                        uvlock=bool(entry.get("uvlock")),
                        weight=int(entry.get("weight") or 1),
                    )
                )
        if plan.variants:
            plan.notes.append(
                f"Multipart model with {len(plan.variants)} parts: Bedrock has one static shape per state, "
                "so only the parts that never conflict are combined."
            )

    if not plan.variants:
        plan.supported = False
        plan.primary_model = ""
        plan.notes.append("No usable model reference was found in the blockstate.")
        return plan

    plan.primary_model = plan.variants[0].model
    for name, values in sorted(seen_properties.items()):
        typed, kind = _classify(sorted(values))
        plan.properties.append(StateProperty(name=name, values=typed, kind=kind))

    combinations = 1
    for prop in plan.properties:
        combinations *= max(len(prop.values), 1)
    plan.total_combinations = combinations

    if plan.mode == "multipart":
        # Only the unconditional parts can be represented as a single static shape.
        plan.notes.append("Conditional multipart parts are reported for manual work rather than guessed.")
        plan.supported = bool(plan.variants)

    models = {variant.model for variant in plan.variants}
    if len(models) > MAX_GEOMETRIES:
        plan.supported = False
        plan.notes.append(
            f"{len(models)} distinct models in one blockstate exceeds the {MAX_GEOMETRIES} geometries "
            "J2B will generate for a single block."
        )
    return plan


# ---------------------------------------------------------------------------
# Rotation baking
# ---------------------------------------------------------------------------


"""Java's two blockstate rotations, in Java's own axes.

Both directions were pinned against vanilla blockstates rather than assumed,
because a sign error here quietly mirrors every directional block:

``x``
    Tilts the model so that ``+y`` (up) moves toward ``-z`` (north) at ``x=90``.
    Vanilla ``end_rod`` uses ``x=90`` for ``facing=north`` and ``x=90, y=180``
    for ``facing=south``, and ``x=180`` for ``facing=down``.
``y``
    Turns the model clockwise seen from above, so ``+x`` (east) moves toward
    ``+z`` (south) at ``y=90``. Vanilla ``stairs`` puts the tall half on ``+x``
    and uses ``y=0`` for ``facing=east``, ``y=90`` for ``facing=south``,
    ``y=180`` for ``facing=west``.

``x`` is applied first, then ``y``, which is what makes ``x=90, y=90`` point a
``+y`` model at ``+x`` (Create's ``axis=x`` shaft) and ``x=90, y=180`` point it
at ``+z`` (``axis=z``).
"""


def _rotate_point(point: list[float], x_deg: float, y_deg: float, centre: tuple[float, float, float]) -> list[float]:
    import math

    px, py, pz = point[0] - centre[0], point[1] - centre[1], point[2] - centre[2]
    if x_deg:
        angle = math.radians(x_deg)
        cos, sin = math.cos(angle), math.sin(angle)
        py, pz = py * cos + pz * sin, -py * sin + pz * cos
    if y_deg:
        angle = math.radians(y_deg)
        cos, sin = math.cos(angle), math.sin(angle)
        px, pz = px * cos - pz * sin, px * sin + pz * cos
    return [px + centre[0], py + centre[1], pz + centre[2]]


def _rotate_face(face: str, x_deg: float, y_deg: float) -> str:
    import math

    vector = FACE_NORMALS[face]
    x, y, z = vector
    if x_deg:
        angle = math.radians(x_deg)
        cos, sin = math.cos(angle), math.sin(angle)
        y, z = y * cos + z * sin, -y * sin + z * cos
    if y_deg:
        angle = math.radians(y_deg)
        cos, sin = math.cos(angle), math.sin(angle)
        x, z = x * cos - z * sin, x * sin + z * cos
    key = (round(x), round(y), round(z))
    return NORMAL_FACES.get(key, face)


def rotate_elements(elements: list[dict[str, Any]], x_deg: float, y_deg: float) -> list[dict[str, Any]]:
    """Bake a blockstate model rotation into the element list.

    The UVs travel with their face — the texture is glued to the quad, exactly
    as Java rotates it — so only the face names and the box bounds change.
    """
    if not x_deg and not y_deg:
        return elements
    centre = (8.0, 8.0, 8.0)
    rotated: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        low = element.get("from")
        high = element.get("to")
        if not isinstance(low, (list, tuple)) or not isinstance(high, (list, tuple)) or len(low) != 3 or len(high) != 3:
            rotated.append(element)
            continue
        corners = [
            _rotate_point([low[0], low[1], low[2]], x_deg, y_deg, centre),
            _rotate_point([high[0], low[1], low[2]], x_deg, y_deg, centre),
            _rotate_point([low[0], high[1], low[2]], x_deg, y_deg, centre),
            _rotate_point([low[0], low[1], high[2]], x_deg, y_deg, centre),
            _rotate_point([high[0], high[1], low[2]], x_deg, y_deg, centre),
            _rotate_point([high[0], low[1], high[2]], x_deg, y_deg, centre),
            _rotate_point([low[0], high[1], high[2]], x_deg, y_deg, centre),
            _rotate_point([high[0], high[1], high[2]], x_deg, y_deg, centre),
        ]
        new_low = [round(min(corner[axis] for corner in corners), 6) for axis in range(3)]
        new_high = [round(max(corner[axis] for corner in corners), 6) for axis in range(3)]
        faces = element.get("faces") if isinstance(element.get("faces"), dict) else {}
        new_faces: dict[str, Any] = {}
        for face, spec in faces.items():
            new_faces[_rotate_face(face, x_deg, y_deg)] = spec
        new_element = {key: value for key, value in element.items() if key not in ("from", "to", "faces")}
        new_element["from"] = new_low
        new_element["to"] = new_high
        new_element["faces"] = new_faces
        rotation = element.get("rotation")
        if isinstance(rotation, dict) and rotation.get("angle"):
            # An element-level rotation inside a rotated model is beyond what can be
            # re-derived safely; the element keeps its box and the caller reports it.
            new_element["j2b_element_rotation"] = rotation
            new_element.pop("rotation", None)
        rotated.append(new_element)
    return rotated


def variant_combinations(plan: BlockStatePlan) -> list[tuple[dict[str, str], list[Variant]]]:
    """Map every state combination to the variants that apply to it."""
    if not plan.properties:
        return [({}, plan.variants)]
    names = [prop.name for prop in plan.properties]
    values: list[list[str]] = []
    for prop in plan.properties:
        values.append([str(value).lower() if isinstance(value, bool) else str(value) for value in prop.values])
    out: list[tuple[dict[str, str], list[Variant]]] = []
    for combo in product(*values):
        assignment = dict(zip(names, combo))
        matching = [variant for variant in plan.variants if _variant_matches(variant, assignment)]
        if matching:
            out.append((assignment, matching))
    return out


def _variant_matches(variant: Variant, assignment: dict[str, str]) -> bool:
    for name, raw in variant.condition.items():
        actual = assignment.get(name)
        if actual is None:
            continue
        if str(actual).lower() != str(raw).lower():
            return False
    return True
