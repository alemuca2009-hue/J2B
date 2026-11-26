"""Entity model files -> Bedrock geometry.

Three shapes of model file turn up in mods, and only one of them needs real work:

* **GeckoLib** (`*.geo.json`) is *already* Bedrock geometry -- it was designed to
  look like it. Bones, pivots, cubes and UVs carry over untouched; only the
  identifier is rewritten, because a Bedrock pack cannot load a model whose
  description names another namespace.
* **Blockbench** (`*.bbmodel`) stores elements in exactly the schema Java block
  models use (`from`/`to`/`faces`/`rotation`), so the block cube converter does
  the geometry, and the only new work is turning the `outliner` group tree into
  Bedrock bones.
* **Bedrock geo shipped as-is** (`*.geo.json` with a `minecraft:geometry` list)
  is copied; the identifier is rewritten for the same reason.

Everything here is geometry. A Bedrock *entity* also needs a behaviour definition
-- health, hitbox, loot, AI goals -- and none of that lives in a model file, so
:mod:`j2b.converters.entities` still reports the entity as manual work. What
changes is that the visible half is now real instead of a note.
"""

from __future__ import annotations

from typing import Any

from .geometry import CubeResult, elements_to_cubes

#: Blockbench stores UVs against its own resolution; Bedrock wants the same numbers.
DEFAULT_RESOLUTION = 16


def _numbers(value: Any, length: int = 3) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _rename_identifier(document: dict[str, Any], identifier: str) -> dict[str, Any]:
    """Point a Bedrock-shaped geometry document at our identifier."""
    geometries = document.get("minecraft:geometry")
    if not isinstance(geometries, list) or not geometries:
        raise ValueError("a geometry document needs a non-empty `minecraft:geometry` list")
    first = dict(geometries[0])
    description = dict(first.get("description") or {})
    description["identifier"] = identifier
    description.setdefault("texture_width", 64)
    description.setdefault("texture_height", 64)
    description.setdefault("visible_bounds_width", 2)
    description.setdefault("visible_bounds_height", 3)
    description.setdefault("visible_bounds_offset", [0, 1.5, 0])
    first["description"] = description
    first.setdefault("bones", [])
    return {"format_version": str(document.get("format_version") or "1.12.0"), "minecraft:geometry": [first]}


def is_geometry_document(payload: Any) -> bool:
    """True for anything that already speaks Bedrock geometry.

    GeckoLib 3/4 and hand-written Bedrock models both qualify, which is why they
    share a path: there is nothing to translate, only to rename.
    """
    return isinstance(payload, dict) and isinstance(payload.get("minecraft:geometry"), list)


def is_bbmodel(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("elements"), list) and "outliner" in payload


def geckolib_geometry(payload: dict[str, Any], identifier: str) -> tuple[dict[str, Any], list[str]]:
    """GeckoLib / Bedrock geometry: rename, and rewrite any nested identifiers."""
    notes: list[str] = []
    document = _rename_identifier(payload, identifier)
    geometry = document["minecraft:geometry"][0]

    for bone in geometry.get("bones") or []:
        if not isinstance(bone, dict):
            continue
        # GeckoLib writes per-bone render hints Bedrock ignores harmlessly;
        # dropping them keeps the file diffable against a Blockbench export.
        for key in ("mirror", "inflate", "debug"):
            if key in bone and bone[key] in (None, "", 0, 0.0, False):
                bone.pop(key, None)
        if "cube" in bone and "cubes" not in bone:
            # GeckoLib 2 used the singular key.
            bone["cubes"] = bone.pop("cube")
            notes.append("bone used GeckoLib 2's singular `cube` key; renamed to `cubes`.")

    if payload.get("format_version") not in ("1.12.0", "1.16.0", 1.12, 1.16):
        notes.append(
            f"model declares format_version {payload.get('format_version')!r}; "
            "written as 1.12.0, which every Bedrock build reads."
        )
    return document, notes


def _bone_name(raw: Any, index: int, used: set[str]) -> str:
    """Bedrock bone names end up in animation molang, so keep them simple."""
    name = "".join(char if char.isalnum() or char == "_" else "_" for char in str(raw or f"bone_{index}"))
    name = name.strip("_") or f"bone_{index}"
    if name[0].isdigit():
        name = f"b_{name}"
    unique, suffix = name, 2
    while unique in used:
        unique = f"{name}_{suffix}"
        suffix += 1
    used.add(unique)
    return unique


def bbmodel_geometry(
    payload: dict[str, Any],
    identifier: str,
    texture_size: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], list[str], CubeResult]:
    """Blockbench project -> Bedrock geometry with bones from the outliner.

    Blockbench stores a project as a flat list of elements plus a group tree that
    refers to them by uuid. Bedrock wants the opposite: bones that own their
    cubes. This walks the tree once, converts each element where it finds it, and
    hangs the resulting cubes off the bone that owned them.

    Elements *not* reachable from the outliner are not dropped -- a project saved
    mid-edit often has them, and silently losing geometry is the worse failure.
    They go on a bone called ``root``.
    """
    notes: list[str] = []
    resolution = payload.get("resolution") if isinstance(payload.get("resolution"), dict) else {}
    width = int(resolution.get("width") or DEFAULT_RESOLUTION)
    height = int(resolution.get("height") or DEFAULT_RESOLUTION)
    if texture_size:
        width, height = texture_size

    elements = [element for element in payload.get("elements") or [] if isinstance(element, dict)]
    by_uuid: dict[str, dict[str, Any]] = {}
    order: list[str | None] = []
    for element in elements:
        uuid = element.get("uuid")
        by_uuid[str(uuid)] = element if uuid else element  # type: ignore[index]
        order.append(str(uuid) if uuid else None)

    # One conversion for the whole element list keeps the numbering in the notes
    # meaningful and lets a single material pass serve every cube.
    converted = elements_to_cubes(elements, lambda _element, _face: "entity")
    if converted.notes:
        notes.extend(converted.notes)

    # The converter skips elements it cannot parse, so pair the surviving cubes
    # with their source uuids by walking both in order.
    surviving: list[str | None] = []
    for index, element in enumerate(elements):
        low = _numbers(element.get("from"))
        high = _numbers(element.get("to"))
        faces = element.get("faces")
        if low is None or high is None or not isinstance(faces, dict) or not faces:
            continue
        surviving.append(order[index])

    cube_for: dict[str, dict[str, Any]] = {}
    for uuid, cube in zip(surviving, converted.cubes):
        if uuid:
            cube_for[uuid] = cube
    leftovers = [cube for uuid, cube in zip(surviving, converted.cubes) if uuid not in cube_for or uuid is None]

    bones: list[dict[str, Any]] = []
    used_names: set[str] = set()
    claimed: set[str] = set()

    def walk(node: Any, parent: str | None, depth: int) -> None:
        if depth > 32:
            notes.append("outliner nesting exceeded 32 levels; deeper groups were flattened.")
            return
        if not isinstance(node, dict):
            return
        if "uuid" in node and "children" not in node:
            # A bare element reference: its cube belongs to the enclosing bone.
            return
        pivot = _numbers(node.get("origin")) or [0.0, 0.0, 0.0]
        bone: dict[str, Any] = {
            "name": _bone_name(node.get("name"), len(bones), used_names),
            # Blockbench measures from the block corner; Bedrock from the centre,
            # X-mirrored -- the same two shifts the cubes get.
            "pivot": [8.0 - pivot[0], pivot[1], pivot[2] - 8.0],
        }
        rotation = _numbers(node.get("rotation"))
        if rotation and any(abs(value) > 1e-6 for value in rotation):
            bone["rotation"] = rotation
        if parent:
            bone["parent"] = parent
        cubes: list[dict[str, Any]] = []
        for child in node.get("children") or []:
            if isinstance(child, str):
                cube = cube_for.pop(child, None)
                if cube is not None:
                    claimed.add(child)
                    cubes.append(cube)
            elif isinstance(child, dict):
                walk(child, bone["name"], depth + 1)
        if cubes:
            bone["cubes"] = cubes
        bones.append(bone)

    for node in payload.get("outliner") or []:
        if isinstance(node, str):
            continue
        walk(node, None, 0)

    if leftovers or cube_for:
        root_cubes = list(leftovers) + list(cube_for.values())
        root_cubes = [cube for cube in root_cubes if cube]
        if root_cubes:
            bones.append({"name": _bone_name("root", len(bones), used_names), "pivot": [0, 0, 0], "cubes": root_cubes})
            notes.append(
                f"{len(root_cubes)} cubes were not referenced by the outliner and were placed on a `root` bone."
            )

    document = {
        "format_version": "1.12.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier": identifier,
                    "texture_width": width,
                    "texture_height": height,
                    "visible_bounds_width": 3,
                    "visible_bounds_height": 3,
                    "visible_bounds_offset": [0, 1.5, 0],
                },
                "bones": bones,
            }
        ],
    }
    if not bones:
        raise ValueError("the Blockbench project contains no convertible geometry")
    return document, notes, converted


def convert_model(
    payload: dict[str, Any],
    identifier: str,
    texture_size: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Pick the right reader and return a Bedrock geometry document."""
    if is_geometry_document(payload):
        return geckolib_geometry(payload, identifier)
    if is_bbmodel(payload):
        document, notes, _cubes = bbmodel_geometry(payload, identifier, texture_size)
        return document, notes
    raise ValueError(
        "the file is neither a Bedrock/GeckoLib geometry nor a Blockbench project"
    )


def bone_count(document: dict[str, Any]) -> int:
    """Bones in a geometry document -- the number that says whether it is usable."""
    try:
        return len(document["minecraft:geometry"][0].get("bones") or [])
    except (KeyError, IndexError, TypeError):
        return 0
