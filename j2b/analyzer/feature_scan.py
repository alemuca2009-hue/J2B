"""Resource scanning.

Everything here is evidence-driven: a feature exists because a file exists.
Class files are only used for *hints* (a name containing ``Screen`` says a GUI
probably lives there) and those hints are always reported as low confidence.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import Feature, Issue, ModMetadata, ScanResult
from ..utils import read_json, split_id
from .mod_archive import ModArchive

CLASS_HINTS = (
    ("screen", "gui", "Custom screen"),
    ("menu", "gui", "Custom menu"),
    ("command", "mechanic", "Custom command"),
    ("keymapping", "mechanic", "Key binding"),
    ("keybinding", "mechanic", "Key binding"),
    ("clientmodinitializer", "mechanic", "Client initializer"),
)


def _class_hint(simple_name: str) -> tuple[str, str] | None:
    lowered = simple_name.lower()
    for needle, kind, label in CLASS_HINTS:
        if needle in lowered:
            return kind, label
    if "particle" in lowered:
        return "mechanic", "Particle"
    if "dimension" in lowered:
        return "mechanic", "Dimension"
    return None


class ModScanner:
    def __init__(self, archive: ModArchive) -> None:
        self.archive = archive
        self.mod = archive.metadata
        self.features: list[Feature] = []
        self.issues: list[Issue] = []
        self._lang: dict[str, str] = {}
        self._block_ids: set[str] = set()
        self._item_ids: set[str] = set()

    # -- entry point ------------------------------------------------------
    def scan(self) -> ScanResult:
        self._load_lang()
        for namespace in self.archive.namespaces or [self.mod.mod_id]:
            self._scan_blocks(namespace)
            self._scan_items(namespace)
            self._scan_recipes(namespace)
            self._scan_worldgen(namespace)
            self._scan_entities(namespace)
        self._scan_classes()
        self._scan_pack_declaration()
        stats = self._stats()
        return ScanResult(
            mod=self.mod,
            namespaces=list(self.archive.namespaces),
            features=self.features,
            issues=self.issues,
            stats=stats,
        )

    # -- helpers ----------------------------------------------------------
    def _load_lang(self) -> None:
        for namespace in self.archive.namespaces:
            payload = self.archive.json(f"assets/{namespace}/lang/en_us.json")
            if payload:
                self._lang.update({str(k): str(v) for k, v in payload.items()})

    def _display(self, keys: list[str], fallback: str) -> str:
        for key in keys:
            if key in self._lang:
                return self._lang[key]
        return fallback.replace("_", " ").title()

    def _stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for feature in self.features:
            by_kind[feature.kind] = by_kind.get(feature.kind, 0) + 1
        return {
            "features_total": len(self.features),
            "features_by_kind": by_kind,
            "namespaces": self.archive.namespaces,
            "lang_keys": len(self._lang),
            "classes_scanned": len([name for name in self.archive.names() if name.endswith(".class")]),
        }

    # -- blocks -----------------------------------------------------------
    def _scan_blocks(self, namespace: str) -> None:
        for name in sorted(self.archive.iter_files(f"assets/{namespace}/blockstates/", ".json")):
            block_name = name.rsplit("/", 1)[-1][:-5]
            identifier = f"{namespace}:{block_name}"
            state = self.archive.json(name) or {}
            model_ref, variant_count = _variant_model(state)
            model = {}
            if model_ref:
                model = self.archive.json(f"assets/{namespace}/models/{model_ref.split(':', 1)[-1]}.json") or {}
            textures = model.get("textures") if isinstance(model.get("textures"), dict) else {}
            self.features.append(
                Feature(
                    id=identifier,
                    kind="block",
                    name=block_name,
                    display=self._display([f"block.{namespace}.{block_name}", f"tile.{identifier}.name"], block_name),
                    source=name,
                    data={
                        "blockstate": state,
                        "model": model,
                        "model_ref": model_ref,
                        "model_parent": model.get("parent") or "",
                        "textures": textures,
                        "variants": variant_count,
                    },
                )
            )
            self._block_ids.add(identifier)
            if variant_count > 1:
                self.issues.append(
                    Issue(
                        "info",
                        "BLOCK_MULTISTATE",
                        f"{identifier} has {variant_count} blockstate variants; only the base appearance converts.",
                        feature_id=identifier,
                    )
                )

    # -- items ------------------------------------------------------------
    def _scan_items(self, namespace: str) -> None:
        prefix = f"assets/{namespace}/models/item/"
        for name in sorted(self.archive.iter_files(prefix, ".json")):
            relative = name[len(prefix) : -5].replace("\\", "/")
            item_name = relative.replace("/", "_")
            identifier = f"{namespace}:{item_name}"
            if identifier in self._block_ids:
                continue  # block items are covered by the block itself
            model = self.archive.json(name) or {}
            model_ref = f"{namespace}:item/{relative}"
            textures = model.get("textures") if isinstance(model.get("textures"), dict) else {}
            self.features.append(
                Feature(
                    id=identifier,
                    kind="item",
                    name=item_name,
                    display=self._display([f"item.{namespace}.{item_name}", f"item.{identifier}"], item_name),
                    source=name,
                    data={
                        "model": model,
                        "model_ref": model_ref,
                        "model_parent": model.get("parent") or "",
                        "textures": textures,
                        "block_item": False,
                    },
                )
            )
            self._item_ids.add(identifier)

    # -- recipes ----------------------------------------------------------
    def _scan_recipes(self, namespace: str) -> None:
        for prefix in (f"data/{namespace}/recipes/", f"data/{namespace}/recipe/"):
            for name in sorted(self.archive.iter_files(prefix, ".json")):
                recipe_name = name[len(prefix) : -5].replace("\\", "/").replace("/", "_")
                payload = self.archive.json(name)
                if not isinstance(payload, dict):
                    self.issues.append(
                        Issue("warning", "RECIPE_UNREADABLE", f"{name} is not valid recipe JSON.", feature_id=name)
                    )
                    continue
                recipe_type = str(payload.get("type") or "unknown")
                self.features.append(
                    Feature(
                        id=f"{namespace}:recipe:{recipe_name}",
                        kind="recipe",
                        name=recipe_name,
                        display=recipe_name.replace("_", " ").title(),
                        source=name,
                        data={
                            "recipe": payload,
                            "type": recipe_type,
                            "path": name,
                            # The Bedrock recipe identifier stays in the mod namespace; the
                            # feature id carries a `recipe:` segment so it cannot collide
                            # with an item or block of the same name.
                            "recipe_id": f"{namespace}:{recipe_name}",
                        },
                    )
                )

    # -- worldgen ---------------------------------------------------------
    def _scan_worldgen(self, namespace: str) -> None:
        categories = ("configured_feature", "placed_feature", "structure", "biome", "noise_settings")
        for category in categories:
            for name in sorted(self.archive.iter_files(f"data/{namespace}/worldgen/{category}/", ".json")):
                feature_name = name.rsplit("/", 1)[-1][:-5]
                payload = self.archive.json(name)
                if not isinstance(payload, dict):
                    continue
                self.features.append(
                    Feature(
                        id=f"{namespace}:{category}:{feature_name}",
                        kind="worldgen",
                        name=feature_name,
                        display=feature_name.replace("_", " ").title(),
                        source=name,
                        data={
                            "category": category,
                            "json": payload,
                            "path": name,
                            "base_id": f"{namespace}:{feature_name}",
                        },
                    )
                )

    # -- entities ---------------------------------------------------------
    def _scan_entities(self, namespace: str) -> None:
        found: set[str] = set()
        for key in self._lang:
            if key.startswith(f"entity.{namespace}."):
                found.add(key.split(".", 2)[-1])
        for name in self.archive.iter_files(f"data/{namespace}/entity_type/", ".json"):
            found.add(name.rsplit("/", 1)[-1][:-5])
        for entity_name in sorted(found):
            candidates = [
                f"assets/{namespace}/textures/entity/{entity_name}.png",
                f"assets/{namespace}/textures/entity/{entity_name}/{entity_name}.png",
            ]
            textures = [candidate for candidate in candidates if self.archive.exists(candidate)]
            entity_type = self.archive.json(f"data/{namespace}/entity_type/{entity_name}.json")
            self.features.append(
                Feature(
                    id=f"{namespace}:entity:{entity_name}",
                    kind="entity",
                    name=entity_name,
                    display=self._display([f"entity.{namespace}.{entity_name}"], entity_name),
                    source=f"assets/{namespace}/lang",
                    data={
                        "texture_candidates": textures,
                        "entity_type_json": entity_type or {},
                    },
                )
            )

    # -- classes ----------------------------------------------------------
    def _scan_classes(self) -> None:
        seen: set[tuple[str, str]] = set()
        for name in self.archive.names(""):
            if not name.endswith(".class") or name.startswith(("META-INF/", "assets/", "data/")):
                continue
            simple = name.rsplit("/", 1)[-1][:-6]
            hint = _class_hint(simple)
            if hint is None:
                continue
            kind, label = hint
            key = (kind, simple)
            if key in seen:
                continue
            seen.add(key)
            self.features.append(
                Feature(
                    id=f"{kind}:{simple.lower()}",
                    kind=kind,
                    name=simple,
                    display=label,
                    source=name,
                    data={"classes": [name], "hint": label, "bytecode_only": True},
                )
            )
        if self.archive.exists("META-INF/") or any(
            name.endswith(".mixins.json") for name in self.archive.names("")
        ):
            self.issues.append(
                Issue(
                    "info",
                    "MIXINS_PRESENT",
                    "Mixins were detected. Mixin bytecode rewrites vanilla classes and has no Bedrock equivalent.",
                    "Behaviour added through mixins must be reimplemented with the Script API.",
                )
            )

    # -- declaration ------------------------------------------------------
    def _scan_pack_declaration(self) -> None:
        for name in ("fabric.mod.json", "META-INF/mods.toml", "META-INF/neoforge.mods.toml"):
            if self.archive.exists(name):
                return
        self.issues.append(
            Issue(
                "info",
                "NO_MOD_METADATA",
                "No known mod metadata file was found; resources were scanned by layout alone.",
            )
        )


def _variant_model(state: dict) -> tuple[str, int]:
    variants = state.get("variants")
    if isinstance(variants, dict) and variants:
        for value in variants.values():
            if isinstance(value, dict) and value.get("model"):
                return str(value["model"]), len(variants)
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict) and entry.get("model"):
                        return str(entry["model"]), len(variants)
    multipart = state.get("multipart")
    if isinstance(multipart, list):
        for part in multipart:
            apply = part.get("apply") if isinstance(part, dict) else None
            candidates = apply if isinstance(apply, list) else [apply]
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("model"):
                    return str(candidate["model"]), len(multipart)
    return "", 0
