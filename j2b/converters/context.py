"""Conversion context: shared writer, texture pipeline and counters.

Texture keys are derived from the **full** resource reference, never from a bare
file name. Two mods (or one mod with two namespaces) can both ship
``textures/block/shared.png``; deriving the key from ``shared`` made the second
one overwrite the first. When two *different* images still want the same key, the
second one gets a short digest suffix and the collision is reported.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from ..analyzer.mod_archive import ModArchive
from ..id_map import vanilla_texture_key, vanilla_tile_path
from ..models import ConversionOptions, Feature
from ..png import PngInfo, read_info
from ..utils import slugify
from .pack_writer import PackWriter

BLOCKS_DIR = "textures/blocks"
ITEMS_DIR = "textures/items"
ENTITY_DIR = "textures/entity"

#: Render methods that Bedrock understands; anything else is a schema error.
RENDER_METHODS = ("opaque", "alpha_test", "alpha_test_single_sided", "blend", "double_sided")

#: Blocks whose Java render type is genuinely translucent rather than cutout.
BLEND_HINTS = ("glass", "window", "pane", "ice", "water", "portal", "slime", "honey", "tinted", "translucent", "gel")


@dataclass
class TextureRecord:
    key: str
    path: str
    source: str
    category: str
    info: PngInfo = field(default_factory=PngInfo)
    digest: str = ""

    @property
    def has_transparency(self) -> bool:
        return self.info.has_transparency

    @property
    def frames(self) -> int:
        return self.info.frames

    def render_method(self, name_hint: str = "") -> str:
        if not self.info.valid:
            # A vanilla atlas tile has no PNG here to inspect; only names that are
            # known to be cut out get alpha_test.
            lowered = name_hint.lower()
            if any(hint in lowered for hint in ("glass", "pane", "bars", "leaves", "ladder", "torch", "flower", "sapling", "rail")):
                return "alpha_test"
            return "opaque"
        if not self.info.has_transparency:
            return "opaque"
        lowered = name_hint.lower()
        if any(hint in lowered for hint in BLEND_HINTS):
            return "blend"
        return "alpha_test"


class TextureManager:
    """Copies Java textures into the resource pack and returns atlas keys."""

    def __init__(self, archive: ModArchive, writer: PackWriter, reference: ModArchive | None = None) -> None:
        self.archive = archive
        self.reference = reference
        self._source_archives: dict[str, ModArchive] = {}
        self.writer = writer
        self.copied: dict[str, str] = {}
        self.records: dict[str, TextureRecord] = {}
        self.collisions: list[str] = []
        self.missing: dict[str, int] = {}
        self._animations: dict[str, dict[str, Any]] = {}
        self.vanilla: set[str] = set()
        self._info_cache: dict[str, PngInfo] = {}
        self._digest_cache: dict[str, str] = {}

    # -- low level --------------------------------------------------------
    def _candidates(self, ref: str) -> list[str]:
        if ref.startswith("assets/"):
            return [ref]
        if ":" not in ref:
            ref = f"minecraft:{ref}"
        namespace, rest = ref.split(":", 1)
        rest = rest.lstrip("/")
        if rest.startswith("textures/"):
            return [f"assets/{namespace}/{rest}.png"]
        return [
            f"assets/{namespace}/textures/{rest}.png",
            f"assets/{namespace}/textures/block/{rest}.png",
            f"assets/{namespace}/textures/item/{rest}.png",
        ]

    def _locate(self, ref: str) -> tuple[str, bytes] | None:
        for archive in (self.archive, self.reference):
            if archive is None:
                continue
            for path in self._candidates(ref):
                data = archive.read(path)
                if data:
                    self._source_archives[path] = archive
                    return path, data
        return None

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha1(data).hexdigest()

    def stable_key(self, ref: str) -> str:
        """``create:block/andesite_casing`` -> ``create_block_andesite_casing``."""
        clean = str(ref or "").strip()
        if clean.startswith("assets/"):
            clean = clean[len("assets/") :]
            if "/textures/" in clean:
                head, _, tail = clean.partition("/textures/")
                clean = f"{head}:{tail}"
        if clean.endswith(".png"):
            clean = clean[:-4]
        return slugify(clean.replace(":", "_").replace("/", "_"), "texture")

    # -- inspection -------------------------------------------------------
    def info_for(self, ref: str) -> PngInfo | None:
        located = self._locate(ref)
        if located is None:
            return None
        path, data = located
        cached = self._info_cache.get(path)
        if cached is None:
            cached = read_info(data)
            self._info_cache[path] = cached
            self._digest_cache[path] = self._digest(data)
        return cached

    def record_for_key(self, key: str) -> TextureRecord | None:
        return self.records.get(key)

    # -- copying ----------------------------------------------------------
    def copy(self, ref: str, category: str, name: str | None = None) -> str | None:
        """Copy ``ref`` into the pack; returns its atlas key (or ``None``)."""
        located = self._locate(ref) if ref else None
        if located is None:
            passthrough = vanilla_texture_key(ref) if ref else None
            if passthrough:
                # The art ships with Bedrock under its own atlas tile name.
                existing = self.records.get(passthrough)
                if existing is None:
                    self.records[passthrough] = TextureRecord(
                        key=passthrough, path="", source=str(ref), category="vanilla"
                    )
                    self.copied[passthrough] = ""
                self.vanilla.add(passthrough)
                self._register_vanilla_tile(passthrough, category)
                return passthrough
            if ref:
                self.missing[ref] = self.missing.get(ref, 0) + 1
            return None
        source, data = located
        digest = self._digest_cache.get(source) or self._digest(data)
        key = self.stable_key(ref)
        existing = self.records.get(key)
        if existing is not None:
            if existing.digest == digest:
                # Same image, already written. It may have been written for the
                # *other* atlas (a block texture reused as an item icon), so the
                # requested atlas still has to learn the key.
                self._ensure_atlas(key, category, existing)
                return key
            key = f"{key}_{digest[:6]}"
            self.collisions.append(
                f"`{ref}` wants the key `{existing.key}` already used by `{existing.source}`; "
                f"written as `{key}` instead."
            )
            if key in self.records:
                return key

        folder = BLOCKS_DIR if category == "block" else ITEMS_DIR if category == "item" else f"textures/{category}"
        path = f"{folder}/{key}.png"
        self.writer.write_rp_bytes(path, data)
        if category == "block":
            self.writer.add_terrain_texture(key, path)
        elif category == "item":
            self.writer.add_item_texture(key, path)

        info = read_info(data)
        self.records[key] = TextureRecord(
            key=key, path=path, source=source, category=category, info=info, digest=digest
        )
        self.copied[key] = path
        self._note_animation(ref, source, key, info)
        return key

    def _ensure_atlas(self, key: str, category: str, record: TextureRecord) -> None:
        """Make sure ``key`` is listed in the atlas ``category`` asks for.

        One PNG can legitimately serve both atlases; Bedrock resolves each atlas
        independently, so the key has to appear in both.
        """
        path = record.path
        if not path:
            self._register_vanilla_tile(key, category)
            return
        if category == "block":
            self.writer.add_terrain_texture(key, path)
        elif category == "item":
            self.writer.add_item_texture(key, path)

    def _register_vanilla_tile(self, key: str, category: str) -> None:
        """Declare a tile whose pixels come from the vanilla packs.

        Bedrock resolves atlas entries by path, so pointing at
        ``textures/blocks/planks_oak`` borrows the vanilla image without copying
        it. Nothing is invented: the key only exists because
        ``vanilla_texture_key`` recognised the reference.
        """
        reference = self.records[key].source
        clean = reference.removeprefix("minecraft:").removeprefix("textures/")
        source_category = "item" if clean.startswith(("item/", "items/")) else "block"
        path = vanilla_tile_path(key, source_category)
        if path is None:
            path = vanilla_tile_path(key, "block" if source_category == "item" else "item")
        if path is None:
            raise ValueError(f"Vanilla tile {key!r} has no documented texture path")
        if category == "item":
            self.writer.add_item_texture(key, path)
        else:
            self.writer.add_terrain_texture(key, path)

    def ensure_placeholder(self, key: str, category: str = "item", size: int = 8) -> str:
        """Write a checkerboard PNG and register it, once per key.

        The honest fallback: a magenta/black tile is instantly recognisable as
        "not converted", where a borrowed vanilla ``stick`` icon looked like a
        deliberate choice.
        """
        if key in self.records:
            self._ensure_atlas(key, category, self.records[key])
            return key
        import struct
        import zlib

        rows = []
        for y in range(size):
            row = bytearray(b"\x00")
            for x in range(size):
                on = (x // 2 + y // 2) % 2 == 0
                row += bytes((255, 0, 255, 255) if on else (0, 0, 0, 255))
            rows.append(bytes(row))

        def chunk(tag: bytes, payload: bytes) -> bytes:
            return (
                struct.pack(">I", len(payload))
                + tag
                + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
            )

        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b"")
        )
        folder = ITEMS_DIR if category == "item" else BLOCKS_DIR
        path = f"{folder}/{key}.png"
        self.writer.write_rp_bytes(path, png)
        if category == "item":
            self.writer.add_item_texture(key, path)
        else:
            self.writer.add_terrain_texture(key, path)
        self.records[key] = TextureRecord(
            key=key, path=path, source="<generated>", category=category, info=read_info(png)
        )
        self.copied[key] = path
        return key

    def _note_animation(self, ref: str, source: str, key: str, info: PngInfo) -> None:
        if not info.is_animated_strip or self.archive is None:
            return
        source_archive = self._source_archives.get(source, self.archive)
        meta = source_archive.json(f"{source}.mcmeta")
        ticks = 1
        frames: list[int] | None = None
        blend = True
        if isinstance(meta, dict) and isinstance(meta.get("animation"), dict):
            animation = meta["animation"]
            raw_ticks = animation.get("frametime")
            if isinstance(raw_ticks, (int, float)) and raw_ticks > 0:
                ticks = int(raw_ticks)
            blend = bool(animation.get("interpolate", False))
            raw_frames = animation.get("frames")
            if isinstance(raw_frames, list):
                resolved: list[int] = []
                for item in raw_frames:
                    index = item.get("index") if isinstance(item, dict) else item
                    if isinstance(index, (int, float)):
                        resolved.append(int(index))
                if resolved:
                    frames = resolved
        entry: dict[str, Any] = {
            "flipbook_texture": self.records[key].path.removesuffix(".png"),
            "atlas_tile": key,
            "ticks_per_frame": ticks,
            "blend_frames": blend,
            "replicate": info.frames,
        }
        if frames:
            entry["frames"] = frames
        self._animations[key] = entry

    def copy_entity(self, ref: str) -> str | None:
        located = self._locate(ref)
        if located is None:
            return None
        _source, data = located
        key = self.stable_key(ref)
        path = f"{ENTITY_DIR}/{key}.png"
        self.writer.write_rp_bytes(path, data)
        self.records.setdefault(key, TextureRecord(key=key, path=path, source=_source, category="entity", info=read_info(data), digest=self._digest(data)))
        self.copied[key] = path
        return key

    def use_generic(self, ref: str) -> str | None:
        if not ref:
            return None
        return self.copy_entity(ref)

    # -- finish -----------------------------------------------------------
    def flush_animations(self) -> int:
        if not self._animations:
            return 0
        self.writer.write_rp("textures/flipbook_textures.json", list(self._animations.values()))
        return len(self._animations)

    def summary(self) -> dict[str, Any]:
        return {
            "textures": len(self.records),
            "collisions": len(self.collisions),
            "missing": len(self.missing),
            "animations": len(self._animations),
            "vanilla_passthrough": len(self.vanilla),
        }


@dataclass
class ConversionContext:
    writer: PackWriter
    textures: TextureManager
    options: ConversionOptions
    mod_id: str
    archive: ModArchive | None = None
    features: list[Feature] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    resolver: Any = None
    tags: Any = None
    texture_namespace: dict[str, str] = field(default_factory=dict)
    #: Machine stations that actually made it into the pack: recipe tag -> block id.
    #: Filled by the block converter, read by the recipe converter, so a machine
    #: recipe is only written when its block exists to run it.
    stations: dict[str, str] = field(default_factory=dict)
    #: Item and block ids the generated pack really defines. A recipe may only
    #: refer to these or to `minecraft:`; anything else is another mod's id that
    #: would load as an uncraftable dead entry.
    known_items: set[str] = field(default_factory=set)

    def count(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def stats(self) -> dict[str, Any]:
        return dict(self.counters)
