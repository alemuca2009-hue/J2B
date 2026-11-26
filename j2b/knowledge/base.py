"""Knowledge base + case memory.

Two layers:

* ``entries.py`` — curated, citable strategies (the converter's rules).
* user overlay — the same schema, loaded from ``J2B_DATA_DIR`` so operators can
  teach the tool without patching the package.

Case memory is separate: it stores what *actually happened* on previous
conversions, so new runs can point at precedent.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import case_memory_path, knowledge_overlay_path, knowledge_suggestions_path
from ..models import Feature
from ..utils import now_iso
from .entries import ENTRIES

VERIFICATION_BONUS = {"verified": 0.3, "community": 0.15, "hypothesis": 0.05, "unverified": 0.0}

FOOD_WORDS = (
    "food", "apple", "bread", "berry", "berries", "soup", "stew", "meat", "cooked",
    "pie", "cake", "cookie", "carrot", "potato", "beetroot", "fish", "cheese", "jerky",
    "potion", "drink", "juice", "tea", "coffee",
)

RECIPE_KINDS = {
    "minecraft:crafting_shaped": "shaped",
    "minecraft:crafting_shapeless": "shapeless",
    "minecraft:smelting": "furnace",
    "minecraft:blasting": "furnace",
    "minecraft:smoking": "furnace",
    "minecraft:campfire_cooking": "furnace",
    "minecraft:stonecutting": "stonecutter",
    "minecraft:smithing_transform": "smithing",
    "minecraft:smithing_trim": "smithing",
}


# A user overlay must win ties against shipped knowledge, and shipped JSONL
# against the hand-written fallback table: later layers are corrections.
ORIGIN_BONUS = {"overlay": 0.06, "bundled": 0.03, "builtin": 0.0}

VALID_KINDS = ("block", "item", "recipe", "entity", "worldgen", "gui", "mechanic")
VALID_OUTCOMES = ("converted", "partial", "manual", "unsupported")

# (token, needles in the Java model parent). The model parent is what decides
# whether a block survives the trip as geometry, as a flat cube, or not at all.
BLOCK_MODEL_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cube_all", ("cube_all",)),
    ("cube_column", ("cube_column",)),
    ("cube_bottom_top", ("cube_bottom_top",)),
    ("cube", ("cube", "block/block", "all_in_one")),
    ("cross_model", ("cross",)),
    ("orientable", ("orientable",)),
    ("custom_geometry", ("geo", "obj")),
    ("translucent", ("translucent", "tinted_cross")),
    ("shape_slab", ("slab",)),
    ("shape_stairs", ("stairs",)),
    ("shape_fence", ("fence",)),
    ("shape_wall", ("wall",)),
    ("shape_door", ("door",)),
    ("shape_trapdoor", ("trapdoor",)),
    ("shape_pane", ("pane",)),
    ("shape_carpet", ("carpet",)),
)

ITEM_MODEL_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("generated_model", ("item/generated", "generated")),
    ("handheld_model", ("handheld",)),
    ("item_model", ("item/",)),
)

# Keyword -> signal for human names (identifiers, display names, hints).
NAME_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("food_name", FOOD_WORDS),
    ("armor_name", ("helmet", "chestplate", "leggings", "boots", "armor", "armour")),
    ("tool_name", ("pickaxe", "axe", "shovel", "sword", "hoe", "shears")),
    ("bucket_name", ("bucket",)),
    ("spawn_egg", ("spawn_egg", "spawn egg")),
    ("music_disc", ("music_disc", "record")),
)

# Keyword -> signal for Java class names found in the jar.
CLASS_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("class:screen", ("screen",)),
    ("class:menu", ("menu", "container")),
    ("class:config", ("config", "options")),
    ("class:command", ("command",)),
    ("class:event", ("event", "listener", "callback")),
    ("class:mixin", ("mixin",)),
    ("class:network", ("network", "packet", "channel")),
    ("class:capability", ("capabilit",)),
    ("class:recipe_serializer", ("recipeserializer", "recipe_serializer")),
    ("class:gecko", ("geckolib", "gecko")),
    ("class:armor", ("armor", "armour")),
    ("class:tool", ("tier", "toolmaterial")),
    ("class:food", ("food", "edible")),
    ("block_entity", ("blockentity", "tileentity")),
)

# Keyword -> signal for non-visual mechanics, matched on the whole haystack.
MECHANIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pack", ("pack.mcmeta", "pack_format", "datapack")),
    ("lang", ("lang", "translation")),
    ("texture", ("texture", "sprite")),
    ("loot", ("loot",)),
    ("redstone", ("redstone", "comparator", "repeater")),
    ("sound", ("sound", "audio")),
    ("particle", ("particle",)),
    ("keybind", ("keybind", "keymapping", "key_mapping")),
    ("dependency", ("depend", "fabric.mod.json")),
    ("capability", ("capability",)),
)

RECIPE_TOKENS = {
    "minecraft:crafting_shaped": "recipe:crafting_shaped",
    "minecraft:crafting_shapeless": "recipe:crafting_shapeless",
    "minecraft:smelting": "recipe:smelting",
    "minecraft:blasting": "recipe:blasting",
    "minecraft:smoking": "recipe:smoking",
    "minecraft:campfire_cooking": "recipe:campfire_cooking",
    "minecraft:stonecutting": "recipe:stonecutting",
    "minecraft:smithing_transform": "recipe:smithing_transform",
    "minecraft:smithing_trim": "recipe:smithing_transform",
}

WORLDGEN_TOKENS = {
    "ore": "feature:ore",
    "tree": "feature:tree",
    "random_patch": "feature:random_patch",
    "vegetation_patch": "feature:vegetation_patch",
    "biome": "biome",
    "structure": "structure",
}

# Every token derive_signals can emit. Curated entries are audited against this
# so a typo cannot silently create an entry that never matches anything.
KNOWN_SIGNALS: frozenset[str] = frozenset(
    set(VALID_KINDS)
    | {token for token, _ in BLOCK_MODEL_SIGNALS}
    | {token for token, _ in ITEM_MODEL_SIGNALS}
    | {token for token, _ in NAME_SIGNALS}
    | {token for token, _ in CLASS_SIGNALS}
    | {token for token, _ in MECHANIC_KEYWORDS}
    | set(RECIPE_TOKENS.values())
    | set(WORLDGEN_TOKENS.values())
    | {
        "recipe:tags", "recipe:other", "recipe_smithing", "recipe_tag", "worldgen_ore",
        "block_multistate", "blockstate_variants", "block_entity_logic", "block_states",
        "block_render_type", "item_block", "item_food", "item_handheld", "durability",
        "multipart", "data_component", "hidden_item", "lang_only", "projectile", "boss",
        "loader:fabric", "loader:forge", "loader:neoforge", "gui_screen", "gui_menu",
        "mechanic_command", "mechanic_keybind", "mechanic_client", "mechanic_particle",
        "mechanic_dimension", "light_source_name",
        # Texture provenance: what a model points at, not what it is called.
        "texture:vanilla_ref", "texture:model_refs", "texture:item_slot",
        # Item model families, namespaced so a block called "handheld_thing" cannot match.
        "item_model:generated", "item_model:handheld",
        # Where a recipe ingredient's tag came from.
        "tag:convention", "tag:c", "tag:forge", "tag:neoforge",
        # Authoritative blockstate structure, read from the blockstate file.
        "blockstate:rotated", "blockstate:multipart",
        # Where an entity's model came from: the difference between "rebuild the
        # mob by hand" and "only the behaviour is missing".
        "entity:model_file", "entity:geckolib", "entity:bbmodel",
    }
)


def _known_signal(token: str) -> bool:
    """``worldgen_*`` carries the Java feature category, so it stays open-ended."""
    return token in KNOWN_SIGNALS or token.startswith("worldgen_")


def _haystack(feature: Feature, data: dict[str, Any]) -> str:
    classes = " ".join(str(cls) for cls in data.get("classes") or [])
    return f"{feature.name} {feature.display} {data.get('hint', '')} {classes}".lower()


def _texture_signals(data: dict[str, Any]) -> set[str]:
    """Signals read from the model's own ``textures`` map.

    A model that points at ``minecraft:block/stone`` borrows art that is not in
    the jar, which is a different conversion problem from a model that ships its
    own PNG. The distinction used to be invisible to the knowledge base because
    it only ever looked at the parent's name, never at the values.
    """
    textures = data.get("textures") or {}
    if not isinstance(textures, dict):
        return set()
    refs = [value for value in textures.values() if isinstance(value, str)]
    if not refs:
        return set()
    signals = {"texture:model_refs"}
    if any(ref.startswith("minecraft:") for ref in refs):
        signals.add("texture:vanilla_ref")
    if any(key in textures for key in ("layer0", "layer1", "icon")):
        signals.add("texture:item_slot")
    return signals


def _item_model_signals(parent: str) -> set[str]:
    """The two Java item model families that decide how Bedrock shows an icon."""
    signals: set[str] = set()
    if "generated" in parent:
        signals.add("item_model:generated")
    if "handheld" in parent:
        signals.add("item_model:handheld")
    return signals


def derive_signals(feature: Feature) -> set[str]:
    """Turn a feature into the signal set the knowledge base matches on.

    Signals are plain lowercase tokens. Two families are in use:

    * bare tokens from the first generation of entries (``block_multistate``),
    * namespaced tokens (``class:mixin``, ``recipe:smelting``, ``feature:ore``,
      ``loader:fabric``) that name *what* the signal came from, so an entry can
      never match on an accidental keyword collision.
    """
    signals: set[str] = {feature.kind}
    data = feature.data or {}
    hay = _haystack(feature, data)
    classes = " ".join(str(cls).lower() for cls in data.get("classes") or [])

    loader = str(data.get("loader") or data.get("platform") or "").lower()
    if loader in ("fabric", "quilt", "forge", "neoforge"):
        signals.add(f"loader:{'fabric' if loader == 'quilt' else loader}")

    for token, needles in CLASS_SIGNALS:
        if any(needle in classes for needle in needles):
            signals.add(token)

    if feature.kind == "block":
        parent = str(data.get("model_parent") or "").lower()
        for token, needles in BLOCK_MODEL_SIGNALS:
            if any(needle in parent for needle in needles):
                signals.add(token)
        if data.get("multipart"):
            signals.add("multipart")
        variants = int(data.get("variants") or 0)
        if data.get("multiblock") or variants > 1:
            signals.add("block_multistate")
            signals.add("blockstate_variants")
        if any("blockentity" in str(cls).lower() for cls in data.get("classes") or []):
            signals.add("block_entity_logic")
        if data.get("blockstate") or data.get("states"):
            signals.add("block_states")
        render = str(data.get("render_type") or "").lower()
        if render in ("translucent", "cutout", "cutout_mipped"):
            signals.add("block_render_type")
        if render == "translucent":
            signals.add("translucent")
        if any(needle in hay for needle in ("lamp", "lantern", "light", "glow", "torch")):
            signals.add("light_source_name")
        signals |= _texture_signals(data)
        state = data.get("blockstate") if isinstance(data.get("blockstate"), dict) else {}
        variants = state.get("variants")
        if isinstance(variants, dict):
            for entries in variants.values():
                for entry in entries if isinstance(entries, list) else [entries]:
                    if isinstance(entry, dict) and (entry.get("x") or entry.get("y")):
                        signals.add("blockstate:rotated")
        if isinstance(state.get("multipart"), list):
            signals.add("blockstate:multipart")

    elif feature.kind == "item":
        parent = str(data.get("model_parent") or "").lower()
        for token, needles in ITEM_MODEL_SIGNALS:
            if any(needle in parent for needle in needles):
                signals.add(token)
        if "handheld" in parent:
            signals.add("item_handheld")
        if data.get("block_item"):
            signals.add("item_block")
        for token, needles in NAME_SIGNALS:
            if any(needle in hay for needle in needles):
                signals.add(token)
        if any(word in hay for word in FOOD_WORDS):
            signals.add("item_food")
        if int(data.get("max_damage") or 0) > 0 or "durab" in hay:
            signals.add("durability")
        if data.get("components"):
            signals.add("data_component")
        if data.get("hidden") or str(data.get("creative_tab") or "").lower() in ("none", "hidden"):
            signals.add("hidden_item")
        if data.get("lang_only"):
            signals.add("lang_only")
        signals |= _texture_signals(data)
        signals |= _item_model_signals(parent)

    elif feature.kind == "recipe":
        recipe_type = str(data.get("type") or "")
        signals.add(RECIPE_TOKENS.get(recipe_type, "recipe:other"))
        signals.add(f"recipe_{RECIPE_KINDS.get(recipe_type, 'other')}")
        payload = data.get("recipe") or {}
        if isinstance(payload, dict):
            blob = json.dumps(payload)
            if '"tag"' in blob or '"item": "#"' in blob:
                signals.add("recipe:tags")
                signals.add("recipe_tag")
                signals.add("tag:convention")
                lowered = blob.lower()
                for loader in ("c:", "forge:", "neoforge:"):
                    if f'"{loader}' in lowered:
                        signals.add(f"tag:{loader[:-1]}")
            if "smithing" in recipe_type:
                signals.add("recipe_smithing")

    elif feature.kind == "worldgen":
        category = str(data.get("category") or "unknown")
        signals.add(f"worldgen_{category}")
        if category in WORLDGEN_TOKENS:
            signals.add(WORLDGEN_TOKENS[category])
        payload = data.get("json") or {}
        if isinstance(payload, dict) and payload.get("type") == "minecraft:ore":
            signals.add("worldgen_ore")
            signals.add("feature:ore")

    elif feature.kind == "entity":
        models = [str(path).lower() for path in data.get("model_candidates") or []]
        if models:
            # A shipped model file is the difference between "rebuild this mob
            # by hand" and "only the behaviour is missing".
            signals.add("entity:model_file")
            if any(path.endswith(".bbmodel") for path in models):
                signals.add("entity:bbmodel")
            if any(path.endswith(".geo.json") for path in models):
                signals.add("entity:geckolib")
        if any(needle in hay for needle in ("projectile", "arrow", "bolt", "fireball")):
            signals.add("projectile")
        if "boss" in hay:
            signals.add("boss")
        if "spawn_egg" in hay or "spawnegg" in hay:
            signals.add("spawn_egg")

    elif feature.kind in ("gui", "mechanic"):
        label = f"{feature.name} {feature.display} {data.get('hint', '')}".lower()
        if "screen" in label:
            signals.add("gui_screen")
        if "menu" in label or "container" in label:
            signals.add("gui_menu")
        for token, needle in (
            ("mechanic_command", "command"),
            ("mechanic_keybind", "keybind"),
            ("mechanic_client", "client"),
            ("mechanic_particle", "particle"),
            ("mechanic_dimension", "dimension"),
        ):
            if needle in label:
                signals.add(token)
        for token, needles in MECHANIC_KEYWORDS:
            if any(needle in hay for needle in needles):
                signals.add(token)

    return signals


@dataclass
class KnowledgeEntry:
    id: str
    title: str
    kind: str
    signals: tuple[str, ...]
    strategy: str
    outcome: str = "manual"
    rationale: str = ""
    limitations: list[str] = field(default_factory=list)
    refs: list[dict[str, str]] = field(default_factory=list)
    verification: str = "unverified"
    match_all: tuple[str, ...] = ()
    match_any: tuple[str, ...] = ()
    origin: str = "builtin"

    @classmethod
    def from_dict(cls, data: dict[str, Any], origin: str = "builtin") -> "KnowledgeEntry":
        match = data.get("match") if isinstance(data.get("match"), dict) else {}
        return cls(
            id=str(data.get("id") or "unnamed"),
            title=str(data.get("title") or data.get("id") or "Untitled"),
            kind=str(data.get("kind") or "mechanic"),
            signals=tuple(str(signal) for signal in data.get("signals") or ()),
            strategy=str(data.get("strategy") or "manual_review"),
            outcome=str(data.get("outcome") or "manual"),
            rationale=str(data.get("rationale") or ""),
            limitations=[str(item) for item in data.get("limitations") or []],
            refs=[dict(item) for item in data.get("refs") or [] if isinstance(item, dict)],
            verification=str(data.get("verification") or "unverified"),
            match_all=tuple(str(signal) for signal in match.get("all") or ()),
            match_any=tuple(str(signal) for signal in match.get("any") or ()),
            origin=origin,
        )

    # -- matching --------------------------------------------------------
    @property
    def required(self) -> tuple[str, ...]:
        """Signals that must all be present for the entry to apply."""
        return self.signals + self.match_all

    def applies(self, signals: set[str]) -> bool:
        if not self.required or not set(self.required).issubset(signals):
            return False
        if self.match_any and not (set(self.match_any) & signals):
            return False
        return True

    def reference(self, score: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "strategy": self.strategy,
            "outcome": self.outcome,
            "verification": self.verification,
            "score": round(score, 3),
            "refs": self.refs,
        }


class KnowledgeBase:
    def __init__(self, overlay_path: Path | None = None, suggestions_path: Path | None = None) -> None:
        self.overlay_path = Path(overlay_path) if overlay_path else knowledge_overlay_path()
        self.suggestions_path = Path(suggestions_path) if suggestions_path else knowledge_suggestions_path()
        self.load_errors: list[str] = []
        self.entries: list[KnowledgeEntry] = []
        self._load()

    # -- loading ---------------------------------------------------------
    def _bundled_entries(self) -> list[dict[str, Any]]:
        """Read the shipped JSONL (one documented case per line)."""
        try:
            from importlib import resources

            payload = resources.files("j2b.knowledge").joinpath("data/entries.jsonl").read_text(encoding="utf-8")
        except (ModuleNotFoundError, FileNotFoundError, OSError):
            fallback = Path(__file__).with_name("data") / "entries.jsonl"
            if not fallback.is_file():
                return []
            payload = fallback.read_text(encoding="utf-8")
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(payload.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                self.load_errors.append(f"entries.jsonl line {number} skipped ({exc.msg})")
                continue
            if isinstance(raw, dict):
                rows.append(raw)
        return rows

    def _load(self) -> None:
        by_id: dict[str, KnowledgeEntry] = {}
        for raw in ENTRIES:
            entry = KnowledgeEntry.from_dict(raw, origin="builtin")
            by_id[entry.id] = entry
        bundled = 0
        for raw in self._bundled_entries():
            entry = KnowledgeEntry.from_dict(raw, origin="bundled")
            if entry.id in by_id:
                self.load_errors.append(f"bundled entry '{entry.id}' duplicates a builtin id; builtin wins")
                continue
            by_id[entry.id] = entry
            bundled += 1
        self.bundled_loaded = bundled
        if self.overlay_path.is_file():
            try:
                payload = json.loads(self.overlay_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.load_errors.append(f"overlay ignored ({exc})")
                payload = []
            for raw in payload if isinstance(payload, list) else []:
                if not isinstance(raw, dict) or not raw.get("id"):
                    self.load_errors.append("overlay entry skipped: needs 'id'")
                    continue
                candidate = KnowledgeEntry.from_dict(raw, origin="overlay")
                if not candidate.required and not candidate.match_any:
                    self.load_errors.append(f"overlay entry '{candidate.id}' skipped: needs 'signals' or 'match'")
                    continue
                by_id[candidate.id] = candidate
        self.entries = list(by_id.values())

    # -- matching --------------------------------------------------------
    def match(self, feature: Feature, limit: int = 3) -> list[tuple[KnowledgeEntry, float]]:
        signals = derive_signals(feature)
        scored: list[tuple[KnowledgeEntry, float]] = []
        for entry in self.entries:
            if entry.kind != feature.kind:
                continue
            if not entry.applies(signals):
                continue
            # Specificity is the number of signals an entry *requires*. An
            # ``any`` group is only a gate, not evidence, so it adds a flat
            # bonus: a broad entry listing ten branches must not outrank a
            # narrower one that pins down two exact signals.
            score = len(entry.required) + (0.25 if entry.match_any else 0.0)
            score += VERIFICATION_BONUS.get(entry.verification, 0.0)
            score += ORIGIN_BONUS.get(entry.origin, 0.0)
            if entry.outcome == "converted":
                score += 0.05
            scored.append((entry, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].id))
        return scored[:limit]

    def best(self, feature: Feature) -> KnowledgeEntry | None:
        matches = self.match(feature, limit=1)
        return matches[0][0] if matches else None

    # -- stats / authoring ----------------------------------------------
    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        by_verification: dict[str, int] = {}
        by_origin: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        for entry in self.entries:
            by_kind[entry.kind] = by_kind.get(entry.kind, 0) + 1
            by_verification[entry.verification] = by_verification.get(entry.verification, 0) + 1
            by_origin[entry.origin] = by_origin.get(entry.origin, 0) + 1
            by_outcome[entry.outcome] = by_outcome.get(entry.outcome, 0) + 1
        return {
            "entries": len(self.entries),
            "by_kind": by_kind,
            "by_verification": by_verification,
            "by_origin": by_origin,
            "by_outcome": by_outcome,
            "overlay": str(self.overlay_path),
            "overlay_present": self.overlay_path.is_file(),
            "load_errors": list(self.load_errors),
        }

    def audit(self) -> dict[str, Any]:
        """Schema check for every loaded entry.

        The converter refuses to invent strategies, so a malformed entry is a
        correctness bug, not a cosmetic one: it can silently demote a feature to
        ``manual``. ``problems`` is therefore expected to be empty in a release.
        """
        problems: list[dict[str, str]] = []
        seen: set[str] = set()

        def flag(entry: KnowledgeEntry, field_name: str, message: str) -> None:
            problems.append({"id": entry.id, "origin": entry.origin, "field": field_name, "problem": message})

        for entry in self.entries:
            if entry.id in seen:
                flag(entry, "id", "duplicate id")
            seen.add(entry.id)
            if entry.kind not in VALID_KINDS:
                flag(entry, "kind", f"unknown kind '{entry.kind}'")
            if entry.outcome not in VALID_OUTCOMES:
                flag(entry, "outcome", f"unknown outcome '{entry.outcome}'")
            if entry.verification not in VERIFICATION_BONUS:
                flag(entry, "verification", f"unknown verification '{entry.verification}'")
            if not entry.required and not entry.match_any:
                flag(entry, "match", "no signals, so the entry can never match")
            if not entry.rationale.strip():
                flag(entry, "rationale", "missing rationale")
            if not entry.limitations:
                flag(entry, "limitations", "no limitations declared")
            if not entry.refs:
                flag(entry, "refs", "no references")
            for ref in entry.refs:
                if not ref.get("title") or not str(ref.get("url", "")).startswith("http"):
                    flag(entry, "refs", "reference needs a title and an http(s) url")
            if entry.strategy == "manual_review" and entry.outcome == "converted":
                flag(entry, "strategy", "converted outcome with the manual_review fallback strategy")
            # Prevent a death-match: an entry whose 'any' branch can never fire
            # because derive_signals has no producer for that token.
            for token in entry.match_any + entry.required:
                if not _known_signal(token):
                    flag(entry, "match", f"unknown signal '{token}'")
        return {
            "entries": len(self.entries),
            "problems": problems,
            "ok": not problems and not self.load_errors,
        }

    def suggest(self, payload: dict[str, Any]) -> None:
        """Record a pattern the KB could not explain, for later curation."""
        if not payload:
            return
        payload = {**payload, "at": now_iso()}
        data: list[dict[str, Any]] = []
        if self.suggestions_path.is_file():
            try:
                data = json.loads(self.suggestions_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = []
        marker = (payload.get("kind"), tuple(payload.get("signals") or ()))
        if any((item.get("kind"), tuple(item.get("signals") or ())) == marker for item in data if isinstance(item, dict)):
            return
        data.append(payload)
        self.suggestions_path.parent.mkdir(parents=True, exist_ok=True)
        self.suggestions_path.write_text(json.dumps(data[-200:], indent=2) + "\n", encoding="utf-8")

    def load_suggestions(self) -> list[dict[str, Any]]:
        if not self.suggestions_path.is_file():
            return []
        try:
            payload = json.loads(self.suggestions_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


class CaseMemory:
    """What happened on previous conversions, keyed by feature signature.

    One connection, opened on first use and reused: a conversion records a row
    per feature (2 890 of them for Create), and opening a connection each time
    was also *leaking* it — ``sqlite3.Connection.__exit__`` commits but does
    not close, so the run left one file handle per feature behind. Measured on
    Create 6.0.10, that was 3.2 s of an 18 s conversion spent in ``__exit__``
    alone, plus the per-statement fsync.

    Rows are buffered and written in one transaction by :meth:`flush`, which
    the converter calls once the feature loop ends. If a run dies half way the
    buffer is simply lost — case memory is a record of finished work, so a
    partial write is not worth an fsync per feature.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS cases (
        kind TEXT NOT NULL,
        signals TEXT NOT NULL,
        feature_id TEXT,
        strategy TEXT,
        status TEXT,
        mod_id TEXT,
        at TEXT,
        seen INTEGER DEFAULT 1,
        PRIMARY KEY (kind, signals)
    );
    """

    _UPSERT = """INSERT INTO cases (kind, signals, feature_id, strategy, status, mod_id, at, seen)
                  VALUES (?,?,?,?,?,?,?,1)
                  ON CONFLICT(kind, signals) DO UPDATE SET
                    seen = seen + 1,
                    status = excluded.status,
                    strategy = excluded.strategy,
                    mod_id = excluded.mod_id,
                    at = excluded.at"""

    #: Rows held before an automatic flush, so a long run never grows unbounded.
    FLUSH_EVERY = 500

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else case_memory_path()
        self.available = True
        self._conn: sqlite3.Connection | None = None
        self._pending: list[tuple[Any, ...]] = []
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = self._open()
            self._conn.executescript(self.SCHEMA)
            # WAL + relaxed sync: this is a local cache of past runs, not a
            # ledger. Losing the last few rows to a power cut costs a hint.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            self.available = False
            self._close_quietly()

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _connection(self) -> sqlite3.Connection | None:
        """The live connection, or ``None`` if case memory is off."""
        if not self.available:
            return None
        if self._conn is None:
            try:
                self._conn = self._open()
            except sqlite3.Error:
                self.available = False
                return None
        return self._conn

    def _close_quietly(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover - closing a dead handle
                pass
            self._conn = None

    def record(self, feature: Feature, mod_id: str) -> None:
        if not self.available or feature.status == "pending":
            return
        signals = ",".join(sorted(derive_signals(feature)))
        self._pending.append(
            (feature.kind, signals, feature.id, feature.strategy, feature.status, mod_id, now_iso())
        )
        if len(self._pending) >= self.FLUSH_EVERY:
            self.flush()

    def flush(self) -> int:
        """Write buffered rows in one transaction. Returns how many were written."""
        if not self._pending:
            return 0
        connection = self._connection()
        if connection is None:
            self._pending.clear()
            return 0
        rows, self._pending = self._pending, []
        try:
            with connection:
                connection.executemany(self._UPSERT, rows)
        except sqlite3.Error:
            self.available = False
            self._close_quietly()
            return 0
        return len(rows)

    def precedent(self, feature: Feature) -> dict[str, Any] | None:
        connection = self._connection()
        if connection is None:
            return None
        signals = derive_signals(feature)
        try:
            self.flush()
            rows = connection.execute(
                "SELECT * FROM cases WHERE kind = ? AND feature_id != ? ORDER BY seen DESC LIMIT 50",
                (feature.kind, feature.id),
            ).fetchall()
        except sqlite3.Error:
            return None
        best: tuple[float, dict[str, Any]] | None = None
        for row in rows:
            other = set(str(row["signals"]).split(","))
            union = signals | other
            overlap = len(signals & other) / len(union) if union else 0.0
            if overlap >= 0.6 and (best is None or overlap > best[0]):
                best = (overlap, dict(row))
        return {"overlap": round(best[0], 2), "record": best[1]} if best else None

    def stats(self) -> dict[str, Any]:
        connection = self._connection()
        if connection is None:
            return {"available": False, "cases": 0}
        try:
            self.flush()
            total = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        except sqlite3.Error:
            return {"available": False, "cases": 0}
        return {"available": True, "cases": int(total or 0), "path": str(self.path)}

    def close(self) -> None:
        """Flush what is buffered and release the handle."""
        self.flush()
        self._close_quietly()

    def __enter__(self) -> "CaseMemory":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - interpreter shutdown order
        try:
            self._close_quietly()
        except Exception:
            pass
