"""Rotation conventions and vanilla-atlas resolution.

Two areas that are easy to get subtly wrong and impossible to notice from a JSON
diff, so they get pinned against *vanilla* behaviour rather than against whatever
the code happened to print the first time:

* Java blockstate ``x``/``y`` rotations. A sign error still produces a valid
  model; it just faces the wrong way. The cases below are taken from vanilla
  ``stairs`` (``y=0`` is ``facing=east``, the tall half on ``+x``) and vanilla
  ``end_rod`` (``x=90`` for ``facing=north``).
* Java texture names that resolve to a Bedrock atlas tile. Bedrock keeps some
  tiles under a different name (``oak_log`` -> ``oak_log_side``) and some under a
  subfolder (``warped_planks`` -> ``textures/blocks/huge_fungus/``), so both the
  key and the path have to be looked up, never rebuilt.
"""

from __future__ import annotations

import unittest

from j2b.converters.variants import _rotate_face, _rotate_point, rotate_elements
from j2b.id_map import (
    BEDROCK_VANILLA_TEXTURES,
    official_tiles,
    vanilla_texture_key,
    vanilla_tile_path,
)
from j2b.knowledge.base import derive_signals
from j2b.models import Feature


def feature(kind: str, name: str = "test", **data) -> Feature:
    return Feature(id=f"{kind}:{name}", kind=kind, name=name, display=name, data=data)


class RotationConventionTest(unittest.TestCase):
    """Java's rotations, in Java's axes, checked against vanilla blockstates."""

    def test_y_rotation_is_clockwise_from_above(self) -> None:
        # Vanilla stairs: the tall half sits on +x and uses y=0 for facing=east,
        # so a quarter turn must send +x (east) to +z (south).
        expected = {"north": "east", "east": "south", "south": "west", "west": "north"}
        for face, want in expected.items():
            with self.subTest(face=face):
                self.assertEqual(_rotate_face(face, 0, 90), want)

    def test_x_rotation_tilts_up_toward_north(self) -> None:
        # Vanilla end_rod points +y and uses x=90 for facing=north.
        self.assertEqual(_rotate_face("up", 90, 0), "north")
        self.assertEqual(_rotate_face("north", 90, 0), "down")
        self.assertEqual(_rotate_face("down", 180, 0), "up")

    def test_up_and_down_are_stable_under_y(self) -> None:
        for angle in (90, 180, 270):
            with self.subTest(angle=angle):
                self.assertEqual(_rotate_face("up", 0, angle), "up")
                self.assertEqual(_rotate_face("down", 0, angle), "down")

    def test_create_shaft_axes(self) -> None:
        """``axis=x`` is x=90,y=90 and ``axis=z`` is x=90,y=180 in Create's blockstate."""
        top = [8.0, 16.0, 8.0]
        axis_x = _rotate_point(top, 90, 90, (8.0, 8.0, 8.0))
        axis_z = _rotate_point(top, 90, 180, (8.0, 8.0, 8.0))
        # A +y model turned into the east-west axis ends up at x=16; along z at z=16.
        self.assertAlmostEqual(axis_x[0], 16.0, places=6)
        self.assertAlmostEqual(axis_z[2], 16.0, places=6)

    def test_asymmetric_box_moves_to_the_right_side(self) -> None:
        elements = [
            {
                "from": [8, 0, 0],
                "to": [16, 8, 16],
                "faces": {"north": {"texture": "#all"}, "up": {"texture": "#all"}},
            }
        ]
        rotated = rotate_elements(elements, 0, 90)
        self.assertEqual(rotated[0]["from"], [0.0, 0.0, 8.0])
        self.assertEqual(rotated[0]["to"], [16.0, 8.0, 16.0])
        # Faces travel with the box: the quad that faced north now faces east.
        self.assertEqual(set(rotated[0]["faces"]), {"east", "up"})

    def test_zero_rotation_is_identity(self) -> None:
        elements = [{"from": [1, 2, 3], "to": [4, 5, 6], "faces": {"west": {}}}]
        self.assertEqual(rotate_elements(elements, 0, 0), elements)


class VanillaAtlasTest(unittest.TestCase):
    def test_wood_planks_resolve_by_their_bedrock_name(self) -> None:
        self.assertEqual(vanilla_texture_key("minecraft:block/mangrove_planks"), "mangrove_planks")
        self.assertEqual(vanilla_texture_key("minecraft:block/cherry_planks"), "cherry_planks")

    def test_log_side_is_renamed(self) -> None:
        # Java has one log texture; Bedrock splits it into _side and _top.
        self.assertEqual(vanilla_texture_key("minecraft:block/oak_log"), "oak_log_side")
        self.assertEqual(vanilla_texture_key("minecraft:block/oak_log_top"), "oak_log_top")

    def test_item_namespace_is_searched_in_the_item_atlas(self) -> None:
        self.assertEqual(vanilla_texture_key("minecraft:item/stick"), "stick")
        self.assertEqual(vanilla_texture_key("minecraft:item/iron_ingot"), "iron_ingot")

    def test_unknown_name_is_not_invented(self) -> None:
        self.assertIsNone(vanilla_texture_key("create:block/not_a_real_texture"))
        self.assertIsNone(vanilla_texture_key("minecraft:block/definitely_not_in_vanilla"))

    def test_paths_come_from_the_official_atlas(self) -> None:
        # The key is not the path: this tile lives in a subfolder.
        self.assertEqual(
            vanilla_tile_path("warped_planks", "block"),
            "textures/blocks/huge_fungus/warped_planks.png",
        )
        self.assertEqual(vanilla_tile_path("stripped_oak_log_side", "block"),
                         "textures/blocks/stripped_oak_log.png")
        self.assertIsNone(vanilla_tile_path("not_a_tile", "block"))

    def test_validator_indices_agree_with_the_atlas(self) -> None:
        tiles = official_tiles()
        self.assertGreater(len(tiles), 1500)
        # A pack may reuse these without shipping a PNG: resource packs merge
        # their atlas with vanilla's, so rejecting them was a false error.
        for key in ("stone", "stick", "mangrove_planks", "iron_bars"):
            with self.subTest(key=key):
                self.assertIn(key, BEDROCK_VANILLA_TEXTURES)
                self.assertIn(key, tiles)


class SignalTest(unittest.TestCase):
    def test_texture_provenance(self) -> None:
        borrowed = derive_signals(feature("block", "b", textures={"all": "minecraft:block/stone"}))
        self.assertIn("texture:vanilla_ref", borrowed)
        self.assertIn("texture:model_refs", borrowed)
        own = derive_signals(feature("block", "b", textures={"all": "create:block/thing"}))
        self.assertNotIn("texture:vanilla_ref", own)
        self.assertIn("texture:model_refs", own)

    def test_item_model_families(self) -> None:
        self.assertIn(
            "item_model:handheld",
            derive_signals(feature("item", "wrench", model_parent="item/handheld")),
        )
        self.assertIn(
            "item_model:generated",
            derive_signals(feature("item", "gear", model_parent="item/generated")),
        )

    def test_blockstate_structure(self) -> None:
        rotated = derive_signals(
            feature(
                "block",
                "shaft",
                blockstate={"variants": {"axis=x": {"model": "create:block/shaft", "x": 90, "y": 90}}},
            )
        )
        self.assertIn("blockstate:rotated", rotated)
        flat = derive_signals(
            feature("block", "casing", blockstate={"variants": {"": {"model": "create:block/casing"}}})
        )
        self.assertNotIn("blockstate:rotated", flat)

    def test_tag_loader(self) -> None:
        signals = derive_signals(
            feature(
                "recipe",
                "r",
                type="minecraft:crafting_shaped",
                recipe={"key": {"A": {"tag": "c:ingots/iron"}}},
            )
        )
        self.assertIn("tag:convention", signals)
        self.assertIn("tag:c", signals)


if __name__ == "__main__":
    unittest.main()
