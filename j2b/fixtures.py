"""A synthetic Fabric mod jar, built from code.

Keeping the fixture as code means the test mod can never drift out of sync with
the scanner (or quietly disappear).

It lives in the package rather than in ``tests/`` for one reason: the frozen
executable's self-test converts this jar end to end. A packaged build that
imports every module but cannot write a pack is exactly the failure a
"tkinter imported" probe misses, and the only way to catch it is to run a
conversion inside the frozen process. Shipping the fixture is what makes the
test and the build check the *same* mod.
"""

from __future__ import annotations

import json
import struct
import zipfile
import zlib
from pathlib import Path


def _png(size: int = 16, colour: tuple[int, int, int] = (192, 32, 64)) -> bytes:
    raw = b"".join(b"\x00" + bytes(colour) * size for _ in range(size))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def build(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    png = _png()

    text_files = {
        "fabric.mod.json": json.dumps(
            {
                "id": "testmod",
                "name": "Test Mod",
                "version": "1.0.0",
                "description": "Synthetic fixture for the converter tests.",
                "authors": ["J2B"],
                "depends": {"minecraft": ">=1.20", "fabricloader": ">=0.15"},
            },
            indent=2,
        ),
        "assets/testmod/lang/en_us.json": json.dumps(
            {
                "block.testmod.ruby_ore": "Ruby Ore",
                "block.testmod.ruby_flower": "Ruby Flower",
                "item.testmod.ruby": "Ruby",
                "item.testmod.ruby_pickaxe": "Ruby Pickaxe",
                "entity.testmod.ruby_golem": "Ruby Golem",
            },
            indent=2,
        ),
        "assets/testmod/blockstates/ruby_ore.json": json.dumps(
            {"variants": {"": {"model": "testmod:block/ruby_ore"}}}
        ),
        "assets/testmod/models/block/ruby_ore.json": json.dumps(
            {"parent": "minecraft:block/cube_all", "textures": {"all": "testmod:block/ruby_ore"}}
        ),
        "assets/testmod/blockstates/ruby_flower.json": json.dumps(
            {"variants": {"": {"model": "testmod:block/ruby_flower"}}}
        ),
        "assets/testmod/models/block/ruby_flower.json": json.dumps(
            {"parent": "minecraft:block/cross", "textures": {"cross": "testmod:block/ruby_flower"}}
        ),
        "assets/testmod/models/item/ruby.json": json.dumps(
            {"parent": "minecraft:item/generated", "textures": {"layer0": "testmod:item/ruby"}}
        ),
        "assets/testmod/models/item/ruby_pickaxe.json": json.dumps(
            {"parent": "minecraft:item/handheld", "textures": {"layer0": "testmod:item/ruby_pickaxe"}}
        ),
        "data/testmod/recipes/ruby_block.json": json.dumps(
            {
                "type": "minecraft:crafting_shaped",
                "pattern": ["###", "###", "###"],
                "key": {"#": {"tag": "minecraft:planks"}},
                "result": {"item": "testmod:ruby", "count": 1},
            }
        ),
        "data/testmod/recipes/ruby_pickaxe.json": json.dumps(
            {
                "type": "minecraft:crafting_shaped",
                "pattern": ["###", " | ", " | "],
                "key": {"#": {"item": "testmod:ruby"}, "|": {"item": "minecraft:stick"}},
                "result": {"item": "testmod:ruby_pickaxe", "count": 1},
            }
        ),
        "data/testmod/recipes/ruby_smithing.json": json.dumps(
            {
                "type": "minecraft:smithing_transform",
                "template": {"item": "minecraft:netherite_upgrade_smithing_template"},
                "base": {"item": "testmod:ruby"},
                "addition": {"item": "minecraft:diamond"},
                "result": {"item": "testmod:ruby_pickaxe"},
            }
        ),
        "data/testmod/worldgen/configured_feature/ruby_ore.json": json.dumps(
            {
                "type": "minecraft:ore",
                "config": {
                    "size": 9,
                    "targets": [
                        {"target": {"block": "minecraft:stone"}, "state": {"Name": "testmod:ruby_ore"}}
                    ],
                },
            }
        ),
        "data/testmod/worldgen/placed_feature/ruby_ore_placed.json": json.dumps(
            {
                "feature": "testmod:ruby_ore",
                "placement": [
                    {"type": "minecraft:count", "count": 4},
                    {"type": "minecraft:in_square"},
                    {
                        "type": "minecraft:height_range",
                        "height": {
                            "type": "minecraft:trapezoid",
                            "min_inclusive": {"absolute": -60},
                            "max_inclusive": {"absolute": 40},
                        },
                    },
                ],
            }
        ),
        "data/testmod/worldgen/configured_feature/ruby_tree.json": json.dumps({"type": "minecraft:tree", "config": {}}),
        # Sound: one plain definition with two variants, one that points at
        # another *event* (no Bedrock form) and one on a Java category Bedrock
        # does not have.
        "assets/testmod/sounds.json": json.dumps(
            {
                "block.ruby_ore.chime": {
                    "category": "block",
                    "subtitle": "subtitles.testmod.chime",
                    "sounds": [
                        "testmod:block/ruby_ore_chime",
                        {
                            "name": "testmod:block/ruby_ore_chime2",
                            "volume": 0.7,
                            "pitch": 1.2,
                            "stream": True,
                            "weight": 3,
                        },
                    ],
                },
                "entity.ruby_golem.step": {
                    "category": "hostile",
                    "sounds": [{"type": "event", "name": "minecraft:entity.iron_golem.step"}],
                },
                "ui.ruby_click": {"category": "master", "sounds": ["testmod:ui/ruby_click"]},
            },
            indent=2,
        ),
        # Rotated *and* rescaled about an off-centre origin: the case where a
        # dropped rescale shows up as a part twice its authored size.
        "assets/testmod/blockstates/ruby_gear.json": json.dumps(
            {"variants": {"": {"model": "testmod:block/ruby_gear"}}}
        ),
        "assets/testmod/models/block/ruby_gear.json": json.dumps(
            {
                "textures": {"gear": "testmod:block/ruby_ore"},
                "elements": [
                    {
                        "from": [2, 4, 2],
                        "to": [14, 12, 10],
                        "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 22.5, "rescale": 0.5},
                        "faces": {
                            "north": {"texture": "#gear", "uv": [0, 0, 12, 8]},
                            "south": {"texture": "#gear", "uv": [0, 0, 12, 8]},
                            "up": {"texture": "#gear", "uv": [0, 8, 12, 12]},
                        },
                    }
                ],
            }
        ),
        "testmod.mixins.json": json.dumps({"required": True, "package": "com.test.mixin", "mixins": ["FooMixin"]}),
    }

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in text_files.items():
            archive.writestr(name, content)
        for texture in (
            "assets/testmod/textures/block/ruby_ore.png",
            "assets/testmod/textures/block/ruby_flower.png",
            "assets/testmod/textures/item/ruby.png",
            "assets/testmod/textures/item/ruby_pickaxe.png",
        ):
            archive.writestr(texture, png)
        # A real OGG is megabytes; the converter copies bytes and never decodes
        # them, so a four-byte header is enough to prove the file travels.
        for sound in (
            "assets/testmod/sounds/block/ruby_ore_chime.ogg",
            "assets/testmod/sounds/block/ruby_ore_chime2.ogg",
            "assets/testmod/sounds/ui/ruby_click.ogg",
        ):
            archive.writestr(sound, b"OggS")
        # Class files only carry names; the scanner must treat them as hints.
        for cls in ("com/test/FooScreen.class", "com/test/FooCommand.class", "com/test/FooKeyMapping.class"):
            archive.writestr(cls, b"\xca\xfe\xba\xbe" + b"\x00" * 64)
    return target
