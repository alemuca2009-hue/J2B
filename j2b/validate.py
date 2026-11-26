"""Structural validation of the generated packs.

These are the mistakes that actually break add-ons: a manifest that Minecraft
rejects, a texture atlas entry pointing at a missing file, a lang key that does
not exist, a feature rule referencing a feature that was never written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .id_map import BEDROCK_VANILLA_TEXTURES, official_tiles
from .models import Check, Feature

IDENTIFIER = "abcdefghijklmnopqrstuvwxyz0123456789_."
_VANILLA_TILES: frozenset[str] = official_tiles()
RESERVED_PREFIX = "minecraft:"


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON ({exc})"
    return (payload if isinstance(payload, dict) else None), None


def _valid_identifier(identifier: str) -> bool:
    if ":" not in identifier:
        return False
    namespace, name = identifier.split(":", 1)
    if not namespace or not name:
        return False
    if any(char not in IDENTIFIER and char != ":" for char in identifier):
        return False
    return True


def _lang_keys(rp_dir: Path, bp_dir: Path) -> set[str]:
    keys: set[str] = set()
    for base in (rp_dir, bp_dir):
        for lang_file in (base / "texts").glob("*.lang"):
            for line in lang_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line:
                    keys.add(line.split("=", 1)[0].strip())
    return keys


STATE_REFERENCE = __import__("re").compile(r"q\.block_state\('([^']+)'\)")


def _state_references(condition: str) -> list[str]:
    return STATE_REFERENCE.findall(condition or "")


def _atlas(rp_dir: Path, name: str, key: str) -> dict[str, Any]:
    payload, _error = _load_json(rp_dir / "textures" / name)
    if not payload:
        return {}
    data = payload.get(key)
    return data if isinstance(data, dict) else {}


def validate_packs(bp_dir: Path, rp_dir: Path, features: Iterable[Feature] = ()) -> list[Check]:
    bp_dir = Path(bp_dir)
    rp_dir = Path(rp_dir)
    checks: list[Check] = []

    def add(severity: str, check_id: str, message: str, detail: str = "") -> None:
        checks.append(Check(severity, check_id, message, detail))

    # -- manifests --------------------------------------------------------
    ids: dict[str, str] = {}
    for label, folder in (("behaviour", bp_dir), ("resource", rp_dir)):
        manifest, error = _load_json(folder / "manifest.json")
        if manifest is None:
            add("error", "MANIFEST_MISSING", f"The {label} pack has no readable manifest.json.", str(error))
            continue
        header = manifest.get("header") if isinstance(manifest.get("header"), dict) else {}
        uuid = str(header.get("uuid") or "")
        if not uuid:
            add("error", "MANIFEST_NO_UUID", f"The {label} pack manifest has no header uuid.")
        elif uuid in ids:
            add("error", "MANIFEST_DUPLICATE_UUID", f"The {label} pack reuses the {ids[uuid]} pack uuid.", uuid)
        else:
            ids[uuid] = label
        modules = manifest.get("modules")
        if not isinstance(modules, list) or not modules:
            add("error", "MANIFEST_NO_MODULE", f"The {label} pack manifest declares no modules.")
        expected = "data" if label == "behaviour" else "resources"
        if isinstance(modules, list) and modules and modules[0].get("type") != expected:
            add("warning", "MANIFEST_MODULE_TYPE", f"The {label} pack module type is not `{expected}`.")
        if not isinstance(header.get("min_engine_version"), list):
            add("warning", "MANIFEST_NO_ENGINE", f"The {label} pack manifest has no min_engine_version.")

    # -- textures ---------------------------------------------------------
    terrain = _atlas(rp_dir, "terrain_texture.json", "texture_data")
    items = _atlas(rp_dir, "item_texture.json", "texture_data")
    for atlas_name, data in (("terrain_texture.json", terrain), ("item_texture.json", items)):
        for key, entry in data.items():
            textures = entry.get("textures") if isinstance(entry, dict) else None
            first = textures[0] if isinstance(textures, list) and textures else textures
            if not isinstance(first, str):
                add("error", "ATLAS_BAD_ENTRY", f"{atlas_name} entry `{key}` has no texture path.")
                continue
            target = rp_dir / (first if first.endswith(".png") else f"{first}.png")
            if not target.is_file():
                # A tile the vanilla packs define is *borrowed*, not missing: the
                # pack declares the key and points at the path Mojang already
                # ships. Anything else is a real dangling reference.
                if key in _VANILLA_TILES and not str(first).startswith("assets/"):
                    add(
                        "info",
                        "ATLAS_VANILLA_TILE",
                        f"{atlas_name} entry `{key}` borrows the vanilla image at `{first}`.",
                        str(first),
                    )
                else:
                    add("error", "ATLAS_TEXTURE_MISSING", f"{atlas_name} entry `{key}` points at a missing file.", str(first))

    # -- geometry ---------------------------------------------------------
    geometries: dict[str, dict[str, Any]] = {}
    for geo_file in sorted((rp_dir / "models" / "blocks").glob("*.geo.json")):
        payload, error = _load_json(geo_file)
        if payload is None:
            add("error", "GEOMETRY_INVALID", f"{geo_file.name} could not be parsed.", str(error))
            continue
        entries = payload.get("minecraft:geometry")
        if not isinstance(entries, list) or not entries:
            add("error", "GEOMETRY_NO_DEFINITION", f"{geo_file.name} has no `minecraft:geometry` list.")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            description = entry.get("description") if isinstance(entry.get("description"), dict) else {}
            geometry_id = str(description.get("identifier") or "")
            if not geometry_id:
                add("error", "GEOMETRY_NO_IDENTIFIER", f"{geo_file.name} declares a geometry without an identifier.")
                continue
            if geometry_id in geometries:
                add("error", "GEOMETRY_DUPLICATE", f"Geometry `{geometry_id}` is declared more than once.")
            geometries[geometry_id] = entry
            for field_name in ("texture_width", "texture_height"):
                value = description.get(field_name)
                if not isinstance(value, (int, float)) or value <= 0:
                    add("error", "GEOMETRY_BAD_TEXTURE_SIZE",
                        f"Geometry `{geometry_id}` has {field_name}={value!r}; Bedrock needs a positive number.")
            for bone in entry.get("bones") or []:
                if not isinstance(bone, dict):
                    continue
                for cube in bone.get("cubes") or []:
                    if not isinstance(cube, dict):
                        continue
                    origin, size = cube.get("origin"), cube.get("size")
                    if not (isinstance(origin, list) and len(origin) == 3):
                        add("error", "GEOMETRY_BAD_CUBE", f"Geometry `{geometry_id}` has a cube without a 3-value origin.")
                        continue
                    if not (isinstance(size, list) and len(size) == 3 and all(isinstance(v, (int, float)) and v >= 0 for v in size)):
                        add("error", "GEOMETRY_BAD_CUBE", f"Geometry `{geometry_id}` has a cube without a valid size.")
                        continue
                    uv_map = cube.get("uv")
                    if isinstance(uv_map, dict):
                        for face, spec in uv_map.items():
                            if face not in ("north", "south", "east", "west", "up", "down"):
                                add("error", "GEOMETRY_BAD_FACE", f"Geometry `{geometry_id}` uses unknown face `{face}`.")
                            if not isinstance(spec, dict):
                                continue
                            uv = spec.get("uv")
                            extent = spec.get("uv_size")
                            if not (isinstance(uv, list) and len(uv) == 2):
                                add("error", "GEOMETRY_BAD_UV", f"Geometry `{geometry_id}` face `{face}` has a malformed uv.")
                            if not (isinstance(extent, list) and len(extent) == 2):
                                add("error", "GEOMETRY_BAD_UV", f"Geometry `{geometry_id}` face `{face}` has a malformed uv_size.")

    # -- blocks -----------------------------------------------------------
    lang = _lang_keys(rp_dir, bp_dir)
    seen_identifiers: dict[str, str] = {}
    for block_file in sorted((bp_dir / "blocks").glob("*.json")):
        payload, error = _load_json(block_file)
        if payload is None:
            add("error", "BLOCK_INVALID", f"{block_file.name} could not be parsed.", str(error))
            continue
        block = payload.get("minecraft:block")
        if not isinstance(block, dict):
            add("error", "BLOCK_NO_DEFINITION", f"{block_file.name} has no `minecraft:block` section.")
            continue
        identifier = str((block.get("description") or {}).get("identifier") or "")
        if not _valid_identifier(identifier):
            add("error", "BLOCK_BAD_IDENTIFIER", f"{block_file.name} has an invalid identifier.", identifier)
            continue
        if identifier in seen_identifiers:
            add("error", "BLOCK_DUPLICATE", f"Identifier {identifier} is declared twice.",
                f"{seen_identifiers[identifier]} and {block_file.name}")
        seen_identifiers[identifier] = block_file.name
        if identifier.startswith(RESERVED_PREFIX):
            add("error", "BLOCK_RESERVED_NAMESPACE", f"{identifier} uses the reserved minecraft namespace.")
        components = block.get("components") if isinstance(block.get("components"), dict) else {}
        material = components.get("minecraft:material_instances")
        if isinstance(material, dict):
            for face, settings in material.items():
                texture = settings.get("texture") if isinstance(settings, dict) else None
                if isinstance(texture, str) and texture not in terrain and texture not in BEDROCK_VANILLA_TEXTURES:
                    add("error", "BLOCK_TEXTURE_UNKNOWN",
                        f"{identifier} references texture `{texture}` which is not in terrain_texture.json.",
                        face)
        geometry_ref = components.get("minecraft:geometry")
        if isinstance(geometry_ref, str) and geometry_ref not in ("minecraft:geometry.full_block",):
            if geometry_ref not in geometries:
                add("error", "GEOMETRY_MISSING",
                    f"{identifier} references geometry `{geometry_ref}`, which no .geo.json declares.")
            else:
                declared_materials = set(material) if isinstance(material, dict) else set()
                for bone in (geometries[geometry_ref].get("bones") or []):
                    for cube in (bone.get("cubes") or []) if isinstance(bone, dict) else []:
                        for face, spec in ((cube.get("uv") or {}).items() if isinstance(cube, dict) else []):
                            used = spec.get("material") if isinstance(spec, dict) else None
                            if isinstance(used, str) and used not in declared_materials:
                                add("error", "GEOMETRY_MATERIAL_MISSING",
                                    f"{identifier} face `{face}` uses material `{used}`, which material_instances does not declare.")
        states = (block.get("description") or {}).get("states")
        state_names = set(states) if isinstance(states, dict) else set()
        for permutation in block.get("permutations") or []:
            if not isinstance(permutation, dict):
                add("error", "BLOCK_BAD_PERMUTATION", f"{identifier} has a permutation that is not an object.")
                continue
            condition = permutation.get("condition")
            if not isinstance(condition, str) or not condition.strip():
                add("error", "BLOCK_BAD_PERMUTATION", f"{identifier} has a permutation without a condition.")
                continue
            for referenced in _state_references(condition):
                if referenced not in state_names:
                    add("error", "BLOCK_STATE_UNDECLARED",
                        f"{identifier} permutation condition uses state `{referenced}`, which `states` does not declare.")
            components_override = permutation.get("components")
            if not isinstance(components_override, dict):
                add("error", "BLOCK_BAD_PERMUTATION", f"{identifier} permutation has no components object.")
                continue
            target = components_override.get("minecraft:geometry")
            if isinstance(target, str) and target not in ("minecraft:geometry.full_block",) and target not in geometries:
                add("error", "GEOMETRY_MISSING",
                    f"{identifier} permutation selects geometry `{target}`, which no .geo.json declares.")
        if f"tile.{identifier}.name" not in lang:
            add("warning", "BLOCK_LANG_MISSING", f"Block {identifier} has no lang entry (tile.{identifier}.name).")

    # -- items ------------------------------------------------------------
    for item_file in sorted((bp_dir / "items").glob("*.json")):
        payload, error = _load_json(item_file)
        if payload is None:
            add("error", "ITEM_INVALID", f"{item_file.name} could not be parsed.", str(error))
            continue
        item = payload.get("minecraft:item")
        if not isinstance(item, dict):
            add("error", "ITEM_NO_DEFINITION", f"{item_file.name} has no `minecraft:item` section.")
            continue
        identifier = str((item.get("description") or {}).get("identifier") or "")
        if not _valid_identifier(identifier):
            add("error", "ITEM_BAD_IDENTIFIER", f"{item_file.name} has an invalid identifier.", identifier)
            continue
        components = item.get("components") if isinstance(item.get("components"), dict) else {}
        icon = components.get("minecraft:icon")
        texture = icon.get("texture") if isinstance(icon, dict) else icon
        if isinstance(texture, str) and texture not in items and texture not in BEDROCK_VANILLA_TEXTURES:
            add("error", "ITEM_TEXTURE_UNKNOWN",
                f"{identifier} uses icon `{texture}` which is not in item_texture.json.")
        display = components.get("minecraft:display_name")
        key = display.get("value") if isinstance(display, dict) else None
        if isinstance(key, str) and key.startswith("item.") and key not in lang:
            add("warning", "ITEM_LANG_MISSING", f"Item {identifier} display_name key `{key}` is not in en_US.lang.")

    # -- recipes ----------------------------------------------------------
    for recipe_file in sorted((bp_dir / "recipes").glob("*.json")):
        payload, error = _load_json(recipe_file)
        if payload is None:
            add("error", "RECIPE_INVALID", f"{recipe_file.name} could not be parsed.", str(error))
            continue
        body = next((value for key, value in payload.items() if key.startswith("minecraft:recipe_")), None)
        if not isinstance(body, dict):
            add("error", "RECIPE_NO_DEFINITION", f"{recipe_file.name} has no recipe body.")
            continue
        identifier = str((body.get("description") or {}).get("identifier") or "")
        if not _valid_identifier(identifier):
            add("error", "RECIPE_BAD_IDENTIFIER", f"{recipe_file.name} has an invalid identifier.", identifier)
        if not body.get("tags"):
            add("warning", "RECIPE_NO_TAGS", f"Recipe {identifier} declares no station tags and will never be available.")
        pattern = body.get("pattern")
        key = body.get("key")
        if isinstance(pattern, list) and isinstance(key, dict):
            for symbol in sorted({char for row in pattern for char in str(row) if char.strip()}):
                if symbol not in key:
                    add("error", "RECIPE_PATTERN_SYMBOL_MISSING",
                        f"Recipe {identifier} pattern uses `{symbol}` but `key` does not define it.")


    # -- features ---------------------------------------------------------
    declared: set[str] = set()
    for feature_file in sorted((bp_dir / "features").glob("*.json")):
        payload, error = _load_json(feature_file)
        if payload is None:
            add("error", "FEATURE_INVALID", f"{feature_file.name} could not be parsed.", str(error))
            continue
        body = payload.get("minecraft:ore_feature")
        if isinstance(body, dict):
            identifier = str((body.get("description") or {}).get("identifier") or "")
            declared.add(identifier)
            if not _valid_identifier(identifier):
                add("error", "FEATURE_BAD_IDENTIFIER", f"{feature_file.name} has an invalid identifier.", identifier)
            for rule in body.get("replace_rules") or []:
                if not isinstance(rule, dict) or not rule.get("places_block"):
                    add("error", "FEATURE_BAD_RULE", f"{feature_file.name} has a replace rule without places_block.")

    for rule_file in sorted((bp_dir / "feature_rules").glob("*.json")):
        payload, error = _load_json(rule_file)
        if payload is None:
            add("error", "RULE_INVALID", f"{rule_file.name} could not be parsed.", str(error))
            continue
        body = payload.get("minecraft:feature_rules")
        if not isinstance(body, dict):
            add("error", "RULE_NO_DEFINITION", f"{rule_file.name} has no `minecraft:feature_rules` section.")
            continue
        places = str((body.get("description") or {}).get("places_feature") or "")
        if places and declared and places not in declared:
            add("error", "RULE_FEATURE_MISSING",
                f"{rule_file.name} places `{places}`, which no generated feature declares.")
        distribution = body.get("distribution") if isinstance(body.get("distribution"), dict) else {}
        iterations = distribution.get("iterations")
        if not isinstance(iterations, int) or iterations < 1:
            add("warning", "RULE_BAD_ITERATIONS", f"{rule_file.name} has iterations={iterations!r}.")

    # -- pack pairing ------------------------------------------------------
    bp_manifest, _error = _load_json(bp_dir / "manifest.json")
    rp_manifest, _error = _load_json(rp_dir / "manifest.json")
    if bp_manifest and rp_manifest:
        rp_uuid = str((rp_manifest.get("header") or {}).get("uuid") or "")
        declared = {
            str(entry.get("uuid"))
            for entry in (bp_manifest.get("dependencies") or [])
            if isinstance(entry, dict)
        }
        if rp_uuid and rp_uuid not in declared:
            add("warning", "MANIFEST_RP_NOT_DECLARED",
                "The behaviour pack does not depend on the resource pack; activating it alone leaves every "
                "block without textures or geometry.",
                rp_uuid)

    if not any(check.severity == "error" for check in checks):
        add("info", "PACK_VALID", "Structural validation found no blocking errors.")
    return checks
