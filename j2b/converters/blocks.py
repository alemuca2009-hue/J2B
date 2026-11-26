"""Block conversion.

A Java block is a model + textures + code. Only the first two are data, so a
converted block is a *decorative* block: it looks right, but nothing about its
behaviour is claimed unless it is re-declared (and the report says so).

The shape comes from the model's own ``elements``, resolved through the whole
inheritance chain. A model is only called a full cube when its boxes really span
0..16 on every axis; everything else is exported as Bedrock geometry.
"""

from __future__ import annotations

from typing import Any, Callable

from ..analyzer.model_resolver import EXACT_TEMPLATES, ResolvedModel
from ..models import Feature
from ..utils import slugify, split_id
from .context import ConversionContext
from .geometry import FACE_NAMES, build_geometry, collision_box, elements_to_cubes
from .machines import station_for_block
from .variants import BlockStatePlan, parse_blockstate, rotate_elements

FULL_BLOCK = "minecraft:geometry.full_block"
MAX_STATES = 16
MAX_PERMUTATION_SPACE = 64


def _sanitise_material(name: str, used: set[str]) -> str:
    candidate = slugify(name.strip("#"), "m")
    if candidate and candidate[0].isdigit():
        candidate = f"m_{candidate}"  # Bedrock material names cannot start with a digit
    candidate = candidate[:24] or "m"
    if candidate in used:
        index = 2
        while f"{candidate}{index}" in used:
            index += 1
        candidate = f"{candidate}{index}"
    used.add(candidate)
    return candidate


def _face_reference(model: ResolvedModel, element: dict[str, Any], face: str) -> tuple[str, str | None]:
    """Return ``(variable_used, concrete_texture_ref_or_None)`` for one face."""
    faces = element.get("faces") if isinstance(element.get("faces"), dict) else {}
    entry = faces.get(face)
    if not isinstance(entry, dict):
        return "", None
    variable = str(entry.get("texture") or "#particle")
    key = variable.lstrip("#")
    ref = model.textures.get(key)
    if ref is None:
        ref = model.textures.get("particle")
    if ref is None and model.textures:
        ref = next(iter(model.textures.values()))
    return variable, ref


class MaterialTable:
    """Turns Java texture variables into Bedrock ``material_instances`` entries."""

    def __init__(self, ctx: ConversionContext, identifier: str, name_hint: str, force_method: str = "") -> None:
        self.ctx = ctx
        self.identifier = identifier
        self.name_hint = name_hint
        self.force_method = force_method
        self.components: dict[str, dict[str, Any]] = {}
        self.by_reference: dict[str, str] = {}
        self.missing_references: list[str] = []
        self.used_names: set[str] = set()
        self.render_methods: dict[str, str] = {}

    def register(self, ref: str | None, hint: str = "") -> str | None:
        if not ref:
            return None
        if ref in self.by_reference:
            return self.by_reference[ref]
        key = self.ctx.textures.copy(ref, "block", self.name_hint)
        if key is None:
            if ref not in self.missing_references:
                self.missing_references.append(ref)
            return None
        record = self.ctx.textures.record_for_key(key)
        assert record is not None
        method = self.force_method or record.render_method(self.name_hint)
        material_name = _sanitise_material(hint or key, self.used_names)
        if not self.components:
            material_name = "*"
            self.used_names = {"*"}
        self.components[material_name] = {
            "texture": key,
            "render_method": method,
            "face_dimming": True,
            "ambient_occlusion": method == "opaque",
        }
        self.render_methods[material_name] = method
        self.by_reference[ref] = material_name
        return material_name

    def lookup(self, ref: str | None) -> str:
        if ref and ref in self.by_reference:
            return self.by_reference[ref]
        return "*" if "*" in self.components else next(iter(self.components), "*")


def _material_resolver(table: MaterialTable, model: ResolvedModel) -> Callable[[dict[str, Any], str], str]:
    def resolve(element: dict[str, Any], face: str) -> str:
        _variable, ref = _face_reference(model, element, face)
        return table.lookup(ref)

    return resolve


def _is_cross(model: ResolvedModel) -> bool:
    """A cross model is two intersecting planes; it must be cut out, not drawn solid."""
    if "cross" in (model.template or ""):
        return True
    elements = model.elements or []
    if len(elements) != 2:
        return False
    for element in elements:
        rotation = element.get("rotation") if isinstance(element, dict) else None
        if not isinstance(rotation, dict) or str(rotation.get("axis")) != "y":
            return False
        size = element.get("to"), element.get("from")
        if not all(isinstance(value, list) for value in size):
            return False
    return True


def _collect_materials(
    ctx: ConversionContext, identifier: str, models: list[ResolvedModel], name_hint: str
) -> MaterialTable:
    force = "alpha_test" if any(_is_cross(model) for model in models) else ""
    table = MaterialTable(ctx, identifier, name_hint, force)
    ordered: list[str] = []
    seen_faces: dict[str, str] = {}
    for model in models:
        for element in model.elements or []:
            if not isinstance(element, dict):
                continue
            for face in FACE_NAMES:
                _variable, ref = _face_reference(model, element, face)
                if ref and ref not in ordered:
                    ordered.append(ref)
                    seen_faces[ref] = _variable
    for index, ref in enumerate(ordered):
        hint = "*" if index == 0 else seen_faces.get(ref, "")
        table.register(ref, hint if hint != "#" else "")
    return table


def _resolve_variant_geometry(
    ctx: ConversionContext,
    identifier: str,
    stem: str,
    model: ResolvedModel,
    table: MaterialTable,
    x: float,
    y: float,
    suffix: str,
) -> tuple[str | None, list[dict[str, Any]], bool, list[str]]:
    """Build (or reuse) geometry for one (model, rotation) pair."""
    notes: list[str] = []
    if not model.elements:
        return None, [], False, notes

    if model.is_full_cube:
        return FULL_BLOCK, [], False, notes

    elements = rotate_elements(model.elements, x, y) if (x or y) else model.elements
    result = elements_to_cubes(elements, _material_resolver(table, model))
    if not result.cubes:
        notes.extend(result.notes)
        return None, [], True, notes
    notes.extend(result.notes)
    geometry_id = f"geometry.{slugify(identifier)}"
    if suffix:
        geometry_id = f"{geometry_id}.{suffix}"
    document = build_geometry(geometry_id, result.cubes)
    ctx.writer.write_rp(f"models/blocks/{stem}{suffix}.geo.json", document)
    return geometry_id, result.cubes, result.approximated, notes


def convert_block(feature: Feature, ctx: ConversionContext) -> None:
    namespace, name = split_id(feature.id)
    stem = slugify(f"{namespace}_{name}")
    state = feature.data.get("blockstate") or {}
    plan = parse_blockstate(state)
    resolver = ctx.resolver

    model_ref = plan.primary_model or str(feature.data.get("model_ref") or "")
    model = resolver.resolve_for_block(model_ref, namespace) if resolver is not None else ResolvedModel(identifier=model_ref)

    for note in plan.notes:
        feature.add_limitation(note)
    for problem in model.problems:
        feature.add_limitation(problem)

    models_for_materials = [model]
    seen_models = {model.identifier}
    if resolver is not None:
        for variant in plan.variants:
            if variant.model == model_ref:
                continue
            candidate_model = resolver.resolve_for_block(variant.model, namespace)
            if candidate_model.identifier in seen_models or not candidate_model.elements:
                continue
            seen_models.add(candidate_model.identifier)
            models_for_materials.append(candidate_model)
    table = _collect_materials(ctx, feature.id, models_for_materials, name)
    if model.missing_parents:
        feature.add_issue(
            "warning",
            "MODEL_PARENT_MISSING",
            f"Model `{model.identifier}` inherits from `{model.missing_parents[0]}`, which is not in the jar.",
            "The block is exported as a full cube because its shape is unknown, not because it is one.",
        )

    # -- geometry ---------------------------------------------------------
    geometry, cubes, approximated, notes = _resolve_variant_geometry(
        ctx, feature.id, stem, model, table, 0.0, 0.0, ""
    )
    for note in notes:
        feature.add_limitation(note)

    permutations: list[dict[str, Any]] = []
    extra_geometries = 0
    if geometry and plan.variants and (plan.total_combinations <= MAX_PERMUTATION_SPACE):
        distinct: dict[tuple[float, float], str] = {(0.0, 0.0): geometry}
        for variant in plan.variants:
            rotation = (variant.x % 360.0, variant.y % 360.0)
            if rotation in distinct:
                continue
            variant_model = model if variant.model == model_ref else resolver.resolve_for_block(variant.model, namespace) if resolver else model
            suffix = f"_{int(rotation[0])}_{int(rotation[1])}"
            built, variant_cubes, _approx, variant_notes = _resolve_variant_geometry(
                ctx, feature.id, stem, variant_model, table, rotation[0], rotation[1], suffix
            )
            if built is None:
                continue
            distinct[rotation] = built
            extra_geometries += 1
            if built != FULL_BLOCK:
                feature.add_output(f"resource_pack/models/blocks/{stem}{suffix}.geo.json")
            cubes = cubes or variant_cubes
            for note in variant_notes:
                feature.add_limitation(note)

        if len(set(distinct.values())) > 1:
            permutations = _build_permutations(plan, distinct)

    if geometry is None and cubes:
        geometry = FULL_BLOCK

    if geometry is None:
        feature.add_limitation(
            f"Model `{model_ref or 'none'}` could not be resolved to any geometry; "
            "the block is exported as a full cube."
        )
        geometry = FULL_BLOCK
    elif geometry != FULL_BLOCK:
        feature.add_output(f"resource_pack/models/blocks/{stem}.geo.json")

    # -- block document ---------------------------------------------------
    components: dict[str, Any] = {}
    if table.components:
        components["minecraft:material_instances"] = table.components
    else:
        components["minecraft:material_instances"] = {
            "*": {
                "texture": "missing_texture",
                "render_method": "opaque",
                "face_dimming": True,
                "ambient_occlusion": True,
            }
        }
        feature.add_limitation(
            "No texture could be read from the jar for this block; the material points at a "
            "placeholder key so the omission is visible instead of hidden behind a vanilla texture."
        )
        _write_placeholder(ctx, feature)

    components["minecraft:geometry"] = geometry
    if geometry != FULL_BLOCK:
        box = collision_box(cubes)
        if box is not None:
            components["minecraft:collision_box"] = box
            components["minecraft:selection_box"] = box
        else:
            feature.add_limitation(
                "The geometry is not a single axis-aligned box, so no collision or selection box was "
                "declared; Bedrock falls back to the full block."
            )
    components["minecraft:destructible_by_mining"] = {"seconds_to_destroy": 3.0}
    components["minecraft:destructible_by_explosion"] = {"explosion_resistance": 3.0}
    components["minecraft:map_color"] = "#c0504d"

    # -- machine station --------------------------------------------------
    # Create's millstone, press, deployer… are useless as decoration. The one
    # behaviour Bedrock can carry without code is a custom crafting station, so
    # the block becomes the table its own recipes are tagged for.
    station = station_for_block(feature.id) if ctx.options.machine_stations else None
    if station is not None:
        components["minecraft:crafting_table"] = {
            "custom_description": station.label,
            "grid_size": station.grid,
            "crafting_tags": [station.tag],
        }
        ctx.stations[station.tag] = feature.id
        feature.add_assumption(
            f"`{station.label}` recipes were mapped onto this block as a custom crafting "
            f"station (`{station.tag}`): the ingredients are the same, the process is instant "
            "and needs no rotation or stress."
        )

    description: dict[str, Any] = {
        "identifier": feature.id,
        "menu_category": {"category": "construction"},
    }
    states, state_notes = _build_states(plan)
    for note in state_notes:
        feature.add_limitation(note)
    if states:
        description["states"] = states

    document: dict[str, Any] = {
        "format_version": "1.20.10",
        "minecraft:block": {
            "description": description,
            "components": components,
        },
    }
    if permutations:
        document["minecraft:block"]["permutations"] = permutations

    ctx.writer.write_bp(f"blocks/{stem}.json", document)
    feature.add_output(f"behavior_pack/blocks/{stem}.json")
    ctx.writer.add_rp_lang(f"tile.{feature.id}.name", feature.display or name.replace("_", " ").title())

    feature.add_assumption(
        "Hardness (3s), blast resistance (3) and the construction menu category are defaults: "
        "Java keeps those in code, not in assets."
    )
    if getattr(ctx.textures, "missing", None):
        pass

    # -- status -----------------------------------------------------------
    partial_reasons: list[str] = []
    if not model.elements:
        partial_reasons.append("geometry could not be resolved")
    if model.elements == []:
        partial_reasons.append("the model declares no geometry at all")
    if approximated:
        partial_reasons.append("geometry approximated")
    if plan.mode == "multipart":
        partial_reasons.append("multipart model")
    if model.template:
        feature.add_assumption(
            f"`{model.identifier}` inherits from `{model.template}`, which is not inside the jar; "
            "the template's documented box was used and its UVs are the vanilla ones."
        )
        if model.template.split(":", 1)[-1] not in EXACT_TEMPLATES:
            partial_reasons.append(f"shape taken from approximate vanilla template {model.template}")
    if plan.properties and not states:
        partial_reasons.append("blockstate properties were not exported")
    if state_notes:
        partial_reasons.append("state space too large")
    if len(permutations) and extra_geometries:
        partial_reasons.append("variant rotations baked into geometry")
    if table.missing_references:
        partial_reasons.append("some faces have no texture")

    for reason in partial_reasons:
        feature.add_issue("info", "BLOCK_PARTIAL", f"Exported with a limitation: {reason}.")

    if partial_reasons:
        feature.set_result("partial", 0.7, "block_model")
    else:
        feature.set_result("converted", 0.95, "block_model")
    ctx.count("blocks")
    if geometry != FULL_BLOCK:
        ctx.count("block_geometries")
    if "minecraft:collision_box" in components:
        ctx.count("block_collisions")
    if permutations:
        ctx.count("block_permutations", len(permutations))


def _build_states(plan: BlockStatePlan) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    if not plan.properties:
        return {}, notes
    if len(plan.properties) > MAX_STATES:
        notes.append(
            f"{len(plan.properties)} blockstate properties exceed the {MAX_STATES} Bedrock allows on one block."
        )
        return {}, notes
    if plan.total_combinations > MAX_PERMUTATION_SPACE:
        notes.append(
            f"{plan.total_combinations} state combinations would need {plan.total_combinations} permutations; "
            "the states were left out rather than shipped half-done."
        )
        return {}, notes
    states: dict[str, Any] = {}
    for prop in plan.properties:
        values = prop.values
        if prop.kind == "bool":
            states[prop.name] = [bool(value) for value in values]
        elif prop.kind == "int":
            states[prop.name] = [int(value) for value in values]
        else:
            states[prop.name] = [str(value) for value in values]
    return states, notes


def _build_permutations(plan: BlockStatePlan, geometries: dict[tuple[float, float], str]) -> list[dict[str, Any]]:
    from .variants import variant_combinations

    permutations: list[dict[str, Any]] = []
    for assignment, variants in variant_combinations(plan):
        variant = variants[0]
        rotation = (variant.x % 360.0, variant.y % 360.0)
        geometry = geometries.get(rotation) or geometries.get((0.0, 0.0))
        if not geometry:
            continue
        condition = " && ".join(
            plan.state_query(name, _typed_value(plan, name, value)) for name, value in sorted(assignment.items())
        )
        if not condition:
            continue
        permutations.append({"condition": condition, "components": {"minecraft:geometry": geometry}})
    return permutations


def _typed_value(plan: BlockStatePlan, name: str, raw: str) -> Any:
    for prop in plan.properties:
        if prop.name != name:
            continue
        for value in prop.values:
            if str(value).lower() == str(raw).lower():
                return value
    return raw


def _write_placeholder(ctx: ConversionContext, feature: Feature) -> None:
    """A visibly checkerboarded texture, so a missing image is never mistaken for a real one."""
    size = 8
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")
        for x in range(size):
            on = (x // 2 + y // 2) % 2 == 0
            row += bytes((255, 0, 255, 255) if on else (0, 0, 0, 255))
        rows.append(bytes(row))
    import struct
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    raw = b"".join(rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    ctx.writer.write_rp_bytes("textures/blocks/missing_texture.png", png)
    ctx.writer.add_terrain_texture("missing_texture", "textures/blocks/missing_texture")
