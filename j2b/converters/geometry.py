"""Java ``elements`` -> Bedrock geometry.

Java model space puts the block corner at ``(0, 0, 0)`` and runs 0..16 on each
axis, with ``+x`` east, ``+y`` up and ``+z`` south. Bedrock block geometry puts
the origin at the centre of the block's bottom face *and mirrors X*: a Bedrock
cube at ``origin.x = 8 - to.x`` is the one Java authored at ``to.x``. Getting
that mirror wrong is invisible in a diff -- a symmetric pillar looks correct and
a stair, a pipe or a door hinge comes out flipped east to west.

The convention here is not inferred, it is copied from the four implementations
that agree with each other and with the game:

* Blockbench ``compileCube``/``compileGroup`` (``js/formats/bedrock/bedrock.js``):
  ``origin[0] = -(from[0] + size[0])`` after the ``-8`` centring shift,
  ``pivot[0] *= -1``, and rotation components X and Y negated with Z kept.
* GeyserMC ``PackConverter`` ``ModelConverter``: ``ELEMENT_OFFSET`` of
  ``[8, 0, 8]``, ``origin.x = 8 - to.x``, the same X/Y negation.
* Kas-tle ``java2bedrock.sh``: ``origin: [(-.to[0] + 8), from[1], from[2] - 8]``,
  ``x``/``y`` angles negated, ``z`` kept.
* ``mc-model-geo`` (EaseCation), which locks the convention against a
  game-verified ``cross`` golden.

So a rotation is not simply re-expressed: mirroring X conjugates it, which is
why Java's ``axis: x, angle: 22.5`` is Bedrock's ``[-22.5, 0, 0]`` and Java's
``axis: z, angle: -90`` stays ``[0, 0, -90]``.

Face names (``north``/``south``/``east``/``west``/``up``/``down``) are identical
in both formats, so they are copied, not translated.

Where Bedrock cannot express something, the cube is still emitted but the
reason is recorded — a block that quietly loses its shape is worse than a block
that reports it.

Three coordinates carry the whole conversion, and all three are exact:

* ``origin`` — Java's box corner minus 8 on the horizontal axes.
* ``pivot`` — Java's element rotation origin, shifted the same way. Bedrock
  rotates the cube about this point, just as Java does.
* ``uv`` / ``uv_size`` — same 0..16 space, same top-left origin, so the
  values carry over — except on ``up``/``down``, which Bedrock orients 180°
  the other way round.

Rotations are *not* limited to quarter turns: Bedrock geometry accepts any
float and Create builds much of its machinery out of 22.5° steps. What Bedrock
cannot reproduce is the shading — ambient occlusion is computed from the
unrotated box — so fractional angles are kept and flagged.

A Java face ``rotation`` turns the texture *inside* its own region, which a
UV rectangle alone cannot express, so it is written as Bedrock's per-face
``uv_rotation`` and pushes the document to the 1.16.0 schema.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

FACE_NAMES = ("north", "south", "east", "west", "up", "down")
#: Bedrock cube rotation only accepts quarter turns.
ROTATION_STEP = 90.0


@dataclass
class CubeResult:
    cubes: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    approximated: bool = False
    dropped_faces: int = 0
    #: Elements that asked Java for ``shade: false`` and are shaded on Bedrock.
    unshaded: int = 0


def _numbers(value: Any, length: int = 3) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _face_uv(entry: dict[str, Any], low: list[float], high: list[float], face: str) -> tuple[list[float], list[float]] | None:
    """Return ``([u, v], [du, dv])`` for one Java face."""
    raw = _numbers(entry.get("uv"), 4)
    if raw is None:
        return None
    u1, v1, u2, v2 = raw
    return [u1, v1], [u2 - u1, v2 - v1]


#: Face -> (u axis, v axis) of the box it is projected onto.
_FACE_AXES = {
    "north": (0, 1),
    "south": (0, 1),
    "east": (2, 1),
    "west": (2, 1),
    "up": (0, 2),
    "down": (0, 2),
}


def _auto_uv(low: list[float], high: list[float], face: str) -> tuple[list[float], list[float]]:
    """Java's implicit UV for a face that declares none.

    Java does not fall back to the whole texture: it unwraps the box, so each
    face samples a region starting at ``(0, 0)`` whose extent equals the face's
    own size in model units. A 4x12 detail therefore reads a 4x12 patch, not a
    squashed 16x16 one.
    """
    u_axis, v_axis = _FACE_AXES[face]
    return [0.0, 0.0], [abs(high[u_axis] - low[u_axis]), abs(high[v_axis] - low[v_axis])]


def _uv_rotation(entry: dict[str, Any]) -> float:
    """Java face ``rotation``: a quarter turn of the texture on the face."""
    try:
        value = float(entry.get("rotation") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value % 360.0


def _rotation(element: dict[str, Any], notes: list[str], index: int) -> tuple[list[float], list[float], bool, float] | None:
    """Translate Java element ``rotation`` into a Bedrock cube ``rotation``/``pivot``.

    Both formats rotate a whole cube about a single point, so this is exact for
    every angle — including the fractional ones modded models use constantly
    (Create alone builds most of its machinery out of 22.5° steps). The pivot
    needs the same ``−8`` centring *and* the same X mirror as the box, or a
    tilting part swings around a point one mirror away from the one the author
    picked.

    The third return value is ``True`` and the fourth is the angle when it is
    not a quarter turn:
    the shape is right, but Bedrock computes ambient occlusion for rotated
    cubes from the unrotated box, so the shading may look flat.
    """
    spec = element.get("rotation")
    if not isinstance(spec, dict):
        return None
    angle = spec.get("angle")
    axis = str(spec.get("axis") or "").lower()
    origin = _numbers(spec.get("origin")) or [8.0, 8.0, 8.0]
    try:
        angle_value = float(angle)
    except (TypeError, ValueError):
        return None
    if axis not in ("x", "y", "z"):
        notes.append(f"element {index}: rotation axis `{axis or 'none'}` is not one of x/y/z; rotation dropped.")
        return None
    if angle_value == 0.0:
        return None
    # Bedrock's geometry space is X-mirrored, so the angle is negated on X and Y
    # and kept on Z -- see the module docstring for the four sources that agree.
    rotation = [0.0, 0.0, 0.0]
    rotation["xyz".index(axis)] = -angle_value if axis in ("x", "y") else angle_value
    pivot = [8.0 - origin[0], origin[1], origin[2] - 8.0]
    return rotation, pivot, abs(angle_value % ROTATION_STEP) > 1e-6, angle_value


def element_rescale(element: dict[str, Any]) -> float:
    """Java's ``rescale`` factor for one element, or ``1.0`` when it has none.

    The field sits *inside* the ``rotation`` block and only ever applies to a
    rotated element: vanilla ``FaceBakery`` builds its matrix from the rotation
    and inserts the scale into that matrix, so a stray ``rescale`` on an
    unrotated element renders at full size.
    """
    spec = element.get("rotation")
    if not isinstance(spec, dict):
        return 1.0
    if not spec.get("angle"):
        return 1.0
    raw = spec.get("rescale")
    if raw is None:
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    return value


def apply_rescale(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold Java ``rescale`` into the element bounds.

    Java does not shrink a rotated element about its centre. ``FaceBakery``
    builds ``translate(origin) * scale(rescale) * rotate(angle) *
    translate(-origin)``, so the box contracts toward the *rotation origin* and
    the pivot itself does not move. Bedrock has no ``rescale`` field, but it
    does not need one: a cube is stored as bounds plus a pivot, so scaling the
    bounds about that pivot and reusing the pivot gives the same shape. Create's
    machine arms -- rotated, rescaled by 0.5 and otherwise oversized in the
    export -- are the models this recovers.

    UVs are deliberately left alone. Java keeps each face's texture region and
    lets it squash onto the smaller quad, which is what a Bedrock ``uv_size``
    does when the cube shrinks underneath it.

    Elements are copied, never mutated, and the ``rescale`` key is dropped so a
    later stage cannot apply the factor a second time.
    """
    out: list[dict[str, Any]] = []
    for element in elements:
        factor = element_rescale(element) if isinstance(element, dict) else 1.0
        if factor == 1.0:
            out.append(element)
            continue
        low = _numbers(element.get("from"))
        high = _numbers(element.get("to"))
        spec = element.get("rotation")
        spec = spec if isinstance(spec, dict) else {}
        pivot = _numbers(spec.get("origin")) or [8.0, 8.0, 8.0]
        if low is None or high is None:
            out.append(element)
            continue
        scaled = dict(element)
        scaled["from"] = [round(pivot[i] + factor * (low[i] - pivot[i]), 9) for i in range(3)]
        scaled["to"] = [round(pivot[i] + factor * (high[i] - pivot[i]), 9) for i in range(3)]
        scaled["rotation"] = {key: value for key, value in spec.items() if key != "rescale"}
        out.append(scaled)
    return out


def elements_to_cubes(
    elements: list[dict[str, Any]],
    material_for: Callable[[dict[str, Any], str], str],
    result: CubeResult | None = None,
    honour_inflate: bool = False,
) -> CubeResult:
    """Convert Java elements into Bedrock cubes.

    ``honour_inflate`` is for Blockbench projects, whose elements share this
    schema but add an ``inflate`` field the vanilla format does not have.
    """
    out = result or CubeResult()

    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            continue
        low = _numbers(element.get("from"))
        high = _numbers(element.get("to"))
        if low is None or high is None:
            out.notes.append(f"element {index}: `from`/`to` are not three numbers; element skipped.")
            continue

        mirrored = [axis for axis in range(3) if low[axis] > high[axis]]
        if mirrored:
            for axis in mirrored:
                low[axis], high[axis] = high[axis], low[axis]
            out.approximated = True
            out.notes.append(
                f"element {index}: negative size on {'/'.join('xyz'[a] for a in mirrored)} "
                "(Java mirrors it); the box is normalised and face UVs are flipped."
            )

        size = [high[axis] - low[axis] for axis in range(3)]
        if any(value <= 0 for value in size):
            out.notes.append(f"element {index}: zero-thickness axis ({size}); Bedrock renders it as a flat plane.")
            size = [max(value, 0.0) for value in size]

        # ``inflate`` is a Blockbench cube property, not part of the vanilla Java
        # model schema: the game ignores a stray one, so it is only honoured when
        # the caller says the elements came from a ``.bbmodel``. There it grows
        # the box on every side and Bedrock has the identical field.
        inflate_value = None
        if honour_inflate and element.get("inflate") is not None:
            try:
                inflate_value = float(element["inflate"])
            except (TypeError, ValueError):
                out.notes.append(f"element {index}: `inflate` is not a number and was ignored.")

        # ``shade: false`` asks Java to skip directional shading on this element
        # (glowing pipes, glass overlays). Bedrock has no per-cube switch -- the
        # nearest thing, ``face_dimming``, belongs to a whole material instance --
        # so the cube is emitted shaded and the difference is reported instead
        # of passing as honoured.
        if element.get("shade") is False:
            out.unshaded += 1
            out.notes.append(
                f"element {index}: Java `shade: false` has no per-cube Bedrock equivalent; "
                "the cube is shaded like the rest of the model."
            )

        # ``8 - high[0]`` is Java's ``low[0] - 8`` after the X mirror.
        origin = [8.0 - high[0], low[1], low[2] - 8.0]
        faces = element.get("faces") if isinstance(element.get("faces"), dict) else {}
        uv_map: dict[str, Any] = {}
        used_materials: set[str] = set()

        for face in FACE_NAMES:
            entry = faces.get(face)
            if not isinstance(entry, dict):
                continue
            uvs = _face_uv(entry, low, high, face)
            if uvs is None:
                uvs = _auto_uv(low, high, face)
                out.notes.append(
                    f"element {index}: face `{face}` declares no UV; Java's unwrapped region "
                    "was computed from the box size instead."
                )
            position, extent = uvs
            # Java and Bedrock both measure UV from the texture's top-left, in
            # the model's 0..16 texture space, so values carry over unchanged.
            if "x" in [("x", "y", "z")[axis] for axis in mirrored] and face in ("east", "west"):
                extent[0] = -extent[0]
            if "z" in [("x", "y", "z")[axis] for axis in mirrored] and face in ("north", "south"):
                extent[0] = -extent[0]
            material = material_for(element, face)
            used_materials.add(material)
            if face in ("up", "down"):
                # Bedrock orients the two horizontal faces the other way round
                # from Java: Blockbench's compiler and the mc-model-geo port
                # both move the rect's corner and negate both sizes, which is a
                # 180° turn of the sampling region. Without it every top
                # texture lands upside down.
                position = [position[0] + extent[0], position[1] + extent[1]]
                extent = [-extent[0], -extent[1]]
            face_json: dict[str, Any] = {"uv": position, "uv_size": extent, "material": material}
            spin = _uv_rotation(entry)
            if spin:
                # Rotating the sampling region cannot express a turned texture;
                # Bedrock geometry carries the angle per face instead.
                face_json["uv_rotation"] = spin
            uv_map[face] = face_json

        if not uv_map:
            out.dropped_faces += 1
            out.notes.append(f"element {index}: no faces declared; element skipped.")
            continue

        cube: dict[str, Any] = {
            "origin": origin,
            "size": size,
            "uv": uv_map,
        }
        rotation = _rotation(element, out.notes, index)
        if rotation:
            rot, pivot, fractional, angle_value = rotation
            cube["rotation"], cube["pivot"] = rot, pivot
            if fractional:
                out.approximated = True
                out.notes.append(
                    f"element {index}: {angle_value:g}° rotation is kept, "
                    "but Bedrock shades rotated cubes from their unrotated box, so lighting may look flat."
                )
        if len(used_materials) == 1:
            cube["material"] = next(iter(used_materials))
        if inflate_value:
            cube["inflate"] = inflate_value
        elif size[0] == 0 or size[2] == 0:
            cube["inflate"] = 0.0
        out.cubes.append(cube)

    return out


def build_geometry(
    identifier: str,
    cubes: list[dict[str, Any]],
    texture_size: tuple[int, int] = (16, 16),
    visible_height: float = 2.5,
) -> dict[str, Any]:
    """Wrap cubes in a Bedrock geometry document."""
    # ``uv_rotation`` on a face only exists from 1.16.0 on; everything else
    # stays on 1.12.0 so the widest range of Bedrock builds can load it.
    needs_116 = any(
        "uv_rotation" in face
        for cube in cubes
        for face in (cube.get("uv") or {}).values()
        if isinstance(face, dict)
    )
    return {
        "format_version": "1.16.0" if needs_116 else "1.12.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier": identifier,
                    "texture_width": texture_size[0],
                    "texture_height": texture_size[1],
                    "visible_bounds_width": 3,
                    "visible_bounds_height": visible_height,
                    "visible_bounds_offset": [0, visible_height / 2, 0],
                },
                "bones": [
                    {
                        "name": "block",
                        "pivot": [0, 0, 0],
                        "cubes": cubes,
                    }
                ],
            }
        ],
    }


def collision_box(cubes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A single axis-aligned box around every cube, in block units."""
    if not cubes:
        return None
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for cube in cubes:
        origin = cube.get("origin") or []
        size = cube.get("size") or []
        if len(origin) != 3 or len(size) != 3:
            continue
        if cube.get("rotation"):
            return None  # a rotated cube is not axis-aligned; do not claim a box
        for axis in range(3):
            low[axis] = min(low[axis], origin[axis])
            high[axis] = max(high[axis], origin[axis] + size[axis])
    if any(value == float("inf") for value in low):
        return None
    rounded = [round(value, 3) for value in low + high]
    return {
        "origin": [rounded[0], rounded[1], rounded[2]],
        "size": [rounded[3] - rounded[0], rounded[4] - rounded[1], rounded[5] - rounded[2]],
    }
