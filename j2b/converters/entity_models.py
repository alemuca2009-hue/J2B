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


def is_java_model(payload: Any) -> bool:
    """A Blockbench "Modded Entity" / Java model: elements, no outliner, no parent.

    Create ships seven of these -- entity hats, blueprint boards, a minecart
    coupling ring -- and they are the one entity format that is pure data: the
    element schema is the same one Java block models use, which is why the block
    cube converter reads them unchanged.

    A model with a ``parent`` is excluded on purpose: its elements live in
    another file, and inventing them would put the wrong shape in the pack.
    """
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("elements"), list)
        and bool(payload["elements"])
        and "outliner" not in payload
        and "parent" not in payload
        and not is_geometry_document(payload)
    )


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
    if texture_size and not resolution:
        # Only a project that declares no resolution falls back to the PNG. A
        # Blockbench UV is measured in the project's resolution, so declaring
        # the size of an HD texture instead would rescale every face.
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
    converted = elements_to_cubes(elements, lambda _element, _face: "entity", honour_inflate=True)
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


def _scale_uvs(cubes: list[dict[str, Any]], width: int, height: int) -> None:
    """Move per-face UVs from Java's 0..16 space into texture pixels.

    A Java face UV always spans 0..16 whatever the texture's resolution, while a
    Bedrock UV is divided by ``texture_width``/``texture_height``. Declaring a
    64 px texture and leaving the numbers in 0..16 makes every face sample one
    sixteenth of the picture, so the two have to move together.
    """
    scale_u, scale_v = width / 16.0, height / 16.0
    if scale_u == 1.0 and scale_v == 1.0:
        return
    for cube in cubes:
        faces = cube.get("uv")
        if not isinstance(faces, dict):
            continue
        for face in faces.values():
            if not isinstance(face, dict):
                continue
            for key in ("uv", "uv_size"):
                pair = face.get(key)
                if isinstance(pair, list) and len(pair) == 2:
                    face[key] = [round(pair[0] * scale_u, 6), round(pair[1] * scale_v, 6)]


def java_model_geometry(
    payload: dict[str, Any],
    identifier: str,
    texture_size: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], list[str], CubeResult]:
    """Blockbench "Java Block/Item" model used for an entity -> Bedrock geometry.

    ``groups`` is optional in this format. When present it is a tree whose
    leaves are element *indices* (a full ``.bbmodel`` uses uuids instead) and
    whose branches are nested groups; each group becomes a bone and each nested
    group a child bone, which is what keeps a jaw hinged to a head. Elements no
    group claims are kept on a ``body`` bone rather than dropped.
    """
    notes: list[str] = []
    raw_elements = payload.get("elements") or []
    # Group children index the *original* list, so positions are tracked through
    # the elements the cube converter skips instead of assuming none are.
    converted = CubeResult()
    cube_at: dict[int, dict[str, Any]] = {}
    for position, element in enumerate(raw_elements):
        if not isinstance(element, dict):
            continue
        before = len(converted.cubes)
        elements_to_cubes([element], lambda _element, _face: "entity", converted)
        if len(converted.cubes) > before:
            cube_at[position] = converted.cubes[-1]
    notes.extend(converted.notes)
    if not converted.cubes:
        raise ValueError("the model contains no convertible elements")

    declared = payload.get("texture_size")
    width, height = (16, 16)
    if isinstance(declared, (list, tuple)) and len(declared) == 2:
        try:
            width, height = int(declared[0]), int(declared[1])
        except (TypeError, ValueError):
            pass
    elif texture_size:
        width, height = texture_size
    if width <= 0 or height <= 0:
        width, height = (16, 16)
    _scale_uvs(converted.cubes, width, height)

    bones: list[dict[str, Any]] = []
    used: set[str] = set()
    claimed: set[int] = set()

    def walk(group: Any, parent: str | None, depth: int) -> None:
        if not isinstance(group, dict):
            return
        if depth > 32:
            notes.append("group nesting exceeded 32 levels; deeper groups were flattened.")
            return
        pivot = _numbers(group.get("origin")) or [8.0, 0.0, 8.0]
        bone: dict[str, Any] = {
            "name": _bone_name(group.get("name"), len(bones), used),
            # Same centring shift and X mirror the cubes get.
            "pivot": [8.0 - pivot[0], pivot[1], pivot[2] - 8.0],
        }
        if parent:
            bone["parent"] = parent
        rotation = _numbers(group.get("rotation"))
        if rotation and any(abs(value) > 1e-6 for value in rotation):
            bone["rotation"] = [-rotation[0], -rotation[1], rotation[2]]
        bones.append(bone)  # parents first: Bedrock resolves `parent` by name
        cubes: list[dict[str, Any]] = []
        for child in group.get("children") or []:
            if isinstance(child, bool):
                continue
            if isinstance(child, int):
                if child in cube_at and child not in claimed:
                    claimed.add(child)
                    cubes.append(cube_at[child])
            elif isinstance(child, dict):
                walk(child, bone["name"], depth + 1)
        if cubes:
            bone["cubes"] = cubes

    groups = payload.get("groups")
    if isinstance(groups, list):
        for entry in groups:
            if isinstance(entry, dict):
                walk(entry, None, 0)
            elif isinstance(entry, int) and not isinstance(entry, bool):
                continue  # a bare index at the top level: an ungrouped element

    leftovers = [cube for position, cube in sorted(cube_at.items()) if position not in claimed]
    if leftovers:
        bones.append({"name": _bone_name("body", len(bones), used), "pivot": [0, 0, 0], "cubes": leftovers})

    document = {
        "format_version": "1.16.0",
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
    if is_java_model(payload):
        document, notes, _cubes = java_model_geometry(payload, identifier, texture_size)
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
