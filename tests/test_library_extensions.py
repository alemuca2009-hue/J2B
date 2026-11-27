"""Tests for the library extensions added after the first Create conversion.

Each test pins a defect that the Create run exposed in the shipped output, so a
regression is caught by the behaviour that failed, not by a snapshot:

* vanilla texture tiles that do not exist in Bedrock (``planks_oak``);
* convention tags under ``data/c/`` that the scanner never read;
* items that fell back to the vanilla ``stick`` icon;
* one PNG serving both atlases without the second atlas knowing about it.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from j2b.analyzer.mod_archive import ModArchive  # noqa: E402
from j2b.analyzer.tags import TagIndex  # noqa: E402
from j2b.converters.context import TextureManager  # noqa: E402
from j2b.converters.pack_writer import PackWriter  # noqa: E402
from j2b.id_map import (  # noqa: E402
    BEDROCK_VANILLA_TEXTURES,
    TAG_REPRESENTATIVES,
    VANILLA_TEXTURES,
    map_tag,
    official_tiles,
    vanilla_texture_key,
)
from j2b.models import ModMetadata  # noqa: E402


def _tiny_png(red: int = 10) -> bytes:
    import struct
    import zlib

    size = 2
    raw = b"".join(b"\x00" + bytes((red, 20, 30, 255)) * size for _ in range(size))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


class VanillaTileTests(unittest.TestCase):
    def test_official_atlas_is_loaded(self) -> None:
        tiles = official_tiles()
        self.assertGreater(len(tiles), 1000, "the extracted vanilla atlas should be large")
        self.assertIn("oak_planks", tiles)
        self.assertIn("stone", tiles)

    def test_every_mapping_exists_in_bedrock(self) -> None:
        tiles = official_tiles()
        broken = {j: b for j, b in VANILLA_TEXTURES.items() if b not in tiles}
        self.assertEqual(broken, {}, f"mappings that Bedrock does not define: {broken}")
        self.assertTrue(BEDROCK_VANILLA_TEXTURES <= tiles)

    def test_wood_names_use_the_bedrock_order(self) -> None:
        self.assertEqual(vanilla_texture_key("minecraft:block/oak_planks"), "oak_planks")
        self.assertEqual(vanilla_texture_key("minecraft:block/spruce_log"), "spruce_log_side")
        self.assertEqual(vanilla_texture_key("minecraft:block/oak_leaves"), "oak_leaves")
        self.assertNotEqual(vanilla_texture_key("minecraft:block/oak_planks"), "planks_oak")

    def test_unknown_texture_is_not_invented(self) -> None:
        self.assertIsNone(vanilla_texture_key("minecraft:block/not_a_real_block"))
        self.assertIsNone(vanilla_texture_key("create:block/andesite_casing"))


class ConventionTagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.jar = root / "Tags-1.0.jar"
        with zipfile.ZipFile(self.jar, "w") as archive:
            archive.writestr(
                "fabric.mod.json",
                json.dumps({"id": "tags", "name": "Tags", "version": "1.0.0"}),
            )
            # A convention tag: its namespace ships no assets at all.
            archive.writestr(
                "data/c/tags/item/plates.json",
                json.dumps({"values": ["tags:iron_sheet", "tags:brass_sheet"]}),
            )
            archive.writestr(
                "data/c/tags/item/dyes.json",
                json.dumps({"values": ["minecraft:red_dye"]}),
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_namespace_without_assets_is_indexed(self) -> None:
        archive = ModArchive(str(self.jar))
        self.assertNotIn("c", archive.namespaces)
        index = TagIndex(archive)
        self.assertEqual(index.members("c:plates"), ["tags:iron_sheet", "tags:brass_sheet"])

    def test_tag_lookup_reaches_the_convention_table(self) -> None:
        index = TagIndex(ModArchive(str(self.jar)))
        self.assertEqual(index.members("c:dyes"), ["minecraft:red_dye"])

    def test_unknown_tag_still_fails_loudly(self) -> None:
        item, matched = map_tag("c:something_nobody_defines")
        self.assertFalse(matched)
        self.assertEqual(item, "minecraft:air")

    def test_convention_representatives_are_single_vanilla_items(self) -> None:
        self.assertEqual(map_tag("c:dusts/redstone"), ("minecraft:redstone", True))
        self.assertEqual(map_tag("c:dyes/black"), ("minecraft:black_dye", True))
        for tag, item in TAG_REPRESENTATIVES.items():
            self.assertTrue(item.startswith("minecraft:"), f"{tag} -> {item}")


class TextureAtlasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.writer = PackWriter(
            self.tmp.name,
            ModMetadata(mod_id="demo", name="Demo", version="1.0.0"),
            make_mcaddon=False,
        )
        self.manager = TextureManager(archive=None, writer=self.writer)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _terrain(self) -> dict:
        return self.writer._terrain_textures  # noqa: SLF001 - test inspects the atlas

    def _items(self) -> dict:
        return self.writer._item_textures  # noqa: SLF001

    def test_vanilla_passthrough_declares_the_atlas_entry(self) -> None:
        key = self.manager.copy("minecraft:block/oak_planks", "block")
        self.assertEqual(key, "oak_planks")
        self.assertIn("oak_planks", self._terrain())
        self.assertEqual(self._terrain()["oak_planks"], "textures/blocks/planks_oak.png")
        # Borrowed, never copied: the pack must not redistribute Mojang art.
        self.assertFalse((self.writer.rp / "textures/blocks/oak_planks.png").exists())

    def test_same_png_serves_both_atlases(self) -> None:
        path = "assets/demo/textures/block/shared.png"
        self.manager.archive = _StubArchive({path: _tiny_png()})
        block_key = self.manager.copy("demo:block/shared", "block")
        item_key = self.manager.copy("demo:block/shared", "item")
        self.assertEqual(block_key, item_key)
        self.assertIn(block_key, self._terrain())
        self.assertIn(item_key, self._items())

    def test_placeholder_is_written_once(self) -> None:
        key = self.manager.ensure_placeholder("j2b_missing_item")
        again = self.manager.ensure_placeholder("j2b_missing_item")
        self.assertEqual(key, again)
        self.assertTrue((self.writer.rp / "textures/items/j2b_missing_item.png").is_file())
        self.assertIn("j2b_missing_item", self._items())

    def test_missing_texture_is_reported_not_substituted(self) -> None:
        self.assertIsNone(self.manager.copy("create:block/nope", "block"))
        self.assertEqual(self.manager.missing.get("create:block/nope"), 1)
        self.assertEqual(self._terrain(), {})


class _StubArchive:
    """The two methods TextureManager needs, over an in-memory file map."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def read(self, path: str) -> bytes | None:
        return self.files.get(path)

    def json(self, path: str):
        payload = self.files.get(path)
        if payload is None:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except ValueError:
            return None


if __name__ == "__main__":
    unittest.main()
