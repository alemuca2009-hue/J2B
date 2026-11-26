"""Entity models: GeckoLib passthrough and Blockbench translation.

Two properties matter more than the rest. First, a GeckoLib model is *already*
Bedrock geometry, so the converter must not "improve" it -- any change to bones,
pivots or UVs is a bug. Second, a Blockbench project stores a flat element list
plus a group tree, while Bedrock wants bones that own cubes; losing geometry
while reshaping that tree is the failure mode worth pinning, because it is
invisible in a file listing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from j2b.converter import Converter
from j2b.converters.entity_models import (
    bbmodel_geometry,
    bone_count,
    convert_model,
    is_bbmodel,
    is_geometry_document,
)
from j2b.models import ConversionOptions

GECKOLIB = {
    "format_version": "1.12.0",
    "minecraft:geometry": [
        {
            "description": {"identifier": "geometry.other_mod.golem", "texture_width": 64, "texture_height": 64},
            "bones": [
                {
                    "name": "body",
                    "pivot": [0, 8, 0],
                    "cubes": [{"origin": [-4, 0, -4], "size": [8, 8, 8], "uv": [0, 0]}],
                },
                {"name": "head", "pivot": [0, 16, 0], "parent": "body"},
            ],
        }
    ],
}

FACES = {
    "north": {"uv": [0, 0, 8, 8]},
    "south": {"uv": [8, 0, 16, 8]},
    "east": {"uv": [16, 0, 24, 8]},
    "west": {"uv": [24, 0, 32, 8]},
    "up": {"uv": [8, 8, 16, 16]},
    "down": {"uv": [16, 8, 24, 16]},
}

BBMODEL = {
    "meta": {"format_version": "4.5", "model_format": "free"},
    "resolution": {"width": 64, "height": 64},
    "elements": [
        {"uuid": "head-uuid", "name": "head", "from": [-4, 8, -4], "to": [4, 16, 4], "faces": FACES},
        {
            "uuid": "leg-uuid",
            "name": "leg",
            "from": [1, 0, 1],
            "to": [3, 8, 3],
            "faces": {"north": {"uv": [0, 0, 2, 8]}},
        },
        {
            "uuid": "orphan-uuid",
            "name": "loose",
            "from": [6, 0, 6],
            "to": [8, 2, 8],
            "faces": {"north": {"uv": [0, 0, 2, 2]}},
        },
    ],
    "outliner": [
        {"name": "head group", "origin": [0, 16, 0], "rotation": [0, 15, 0], "children": ["head-uuid"]},
        {
            "name": "legs",
            "origin": [0, 0, 0],
            "children": ["leg-uuid", {"name": "empty group", "origin": [0, 0, 0], "children": []}],
        },
    ],
}


class GeckoLibTests(unittest.TestCase):
    def test_identifier_is_rewritten(self) -> None:
        document, _notes = convert_model(GECKOLIB, "geometry.testmod.golem")
        self.assertEqual(document["minecraft:geometry"][0]["description"]["identifier"], "geometry.testmod.golem")

    def test_bones_and_cubes_are_untouched(self) -> None:
        source = json.loads(json.dumps(GECKOLIB))
        document, _notes = convert_model(GECKOLIB, "geometry.testmod.golem")
        self.assertEqual(document["minecraft:geometry"][0]["bones"], source["minecraft:geometry"][0]["bones"])

    def test_description_defaults_fill_only_missing_keys(self) -> None:
        sparse = {
            "format_version": "1.12.0",
            "minecraft:geometry": [{"description": {"identifier": "x"}, "bones": []}],
        }
        document, _notes = convert_model(sparse, "geometry.testmod.x")
        description = document["minecraft:geometry"][0]["description"]
        self.assertEqual(description["texture_width"], 64)
        self.assertIn("visible_bounds_height", description)

    def test_geckolib2_singular_cube_key_is_renamed(self) -> None:
        legacy = {
            "format_version": "1.12.0",
            "minecraft:geometry": [
                {
                    "description": {"identifier": "geometry.x"},
                    "bones": [
                        {
                            "name": "b",
                            "pivot": [0, 0, 0],
                            "cube": [{"origin": [0, 0, 0], "size": [1, 1, 1], "uv": [0, 0]}],
                        }
                    ],
                }
            ],
        }
        document, notes = convert_model(legacy, "geometry.testmod.x")
        bone = document["minecraft:geometry"][0]["bones"][0]
        self.assertIn("cubes", bone)
        self.assertNotIn("cube", bone)
        self.assertTrue(any("singular" in note for note in notes))

    def test_detection(self) -> None:
        self.assertTrue(is_geometry_document(GECKOLIB))
        self.assertFalse(is_geometry_document(BBMODEL))
        self.assertTrue(is_bbmodel(BBMODEL))
        self.assertFalse(is_bbmodel(GECKOLIB))


class BlockbenchTests(unittest.TestCase):
    def test_groups_become_bones(self) -> None:
        document, _notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        names = [bone["name"] for bone in document["minecraft:geometry"][0]["bones"]]
        self.assertIn("head_group", names)
        self.assertIn("legs", names)

    def test_group_pivot_is_shifted_to_block_centre(self) -> None:
        document, _notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        bone = next(b for b in document["minecraft:geometry"][0]["bones"] if b["name"] == "head_group")
        self.assertEqual(bone["pivot"], [8.0, 16.0, -8.0])

    def test_group_rotation_carries_over(self) -> None:
        document, _notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        bone = next(b for b in document["minecraft:geometry"][0]["bones"] if b["name"] == "head_group")
        self.assertEqual(bone["rotation"], [0.0, 15.0, 0.0])

    def test_cubes_land_on_the_bone_that_owned_them(self) -> None:
        document, _notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        bones = {bone["name"]: bone for bone in document["minecraft:geometry"][0]["bones"]}
        self.assertEqual(len(bones["head_group"].get("cubes", [])), 1)
        self.assertAlmostEqual(bones["head_group"]["cubes"][0]["origin"][0], 4.0)
        self.assertEqual(len(bones["legs"].get("cubes", [])), 1)

    def test_nested_group_gets_a_parent(self) -> None:
        document, _notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        bones = {bone["name"]: bone for bone in document["minecraft:geometry"][0]["bones"]}
        self.assertIn("empty_group", bones)
        self.assertEqual(bones["empty_group"].get("parent"), "legs")

    def test_element_outside_the_outliner_is_not_lost(self) -> None:
        document, notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        root = next(b for b in document["minecraft:geometry"][0]["bones"] if b["name"] == "root")
        self.assertEqual(len(root["cubes"]), 1)
        self.assertTrue(any("root" in note for note in notes))

    def test_uvs_are_kept_in_project_resolution(self) -> None:
        document, _notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        description = document["minecraft:geometry"][0]["description"]
        self.assertEqual((description["texture_width"], description["texture_height"]), (64, 64))

    def test_bone_names_are_made_molang_safe(self) -> None:
        ugly = json.loads(json.dumps(BBMODEL))
        ugly["outliner"][0]["name"] = "head group!"
        ugly["outliner"][1]["name"] = "1 legs"
        document, _notes, _cubes = bbmodel_geometry(ugly, "geometry.testmod.golem")
        names = [bone["name"] for bone in document["minecraft:geometry"][0]["bones"]]
        # Punctuation becomes an underscore, and trailing ones are trimmed.
        self.assertIn("head_group", names)
        self.assertIn("b_1_legs", names)

    def test_duplicate_names_are_disambiguated(self) -> None:
        twin = json.loads(json.dumps(BBMODEL))
        twin["outliner"].append({"name": "legs", "origin": [0, 0, 0], "children": []})
        document, _notes, _cubes = bbmodel_geometry(twin, "geometry.testmod.golem")
        names = [bone["name"] for bone in document["minecraft:geometry"][0]["bones"]]
        self.assertEqual(len(names), len(set(names)))

    def test_bone_count(self) -> None:
        document, _notes, _cubes = bbmodel_geometry(BBMODEL, "geometry.testmod.golem")
        self.assertEqual(bone_count(document), 4)


def _jar_with_entity_model(path: Path) -> Path:
    """A mod whose only entity ships a GeckoLib model and a texture."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "fabric.mod.json",
            json.dumps({"id": "golemmod", "name": "Golem Mod", "version": "1.0.0"}),
        )
        archive.writestr(
            "assets/golemmod/lang/en_us.json",
            json.dumps({"entity.golemmod.ruby_golem": "Ruby Golem"}),
        )
        archive.writestr("assets/golemmod/textures/entity/ruby_golem.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        archive.writestr("assets/golemmod/geo/ruby_golem.geo.json", json.dumps(GECKOLIB))
    return path


class EntityPipelineTests(unittest.TestCase):
    def test_entity_with_a_geckolib_model_becomes_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jar = _jar_with_entity_model(Path(tmp) / "golem.jar")
            out = Path(tmp) / "out"
            result = Converter(
                ConversionOptions(output_dir=str(out), record_learning=False, report_formats=("json",))
            ).convert(jar)

            entity = next(f for f in result.features if f.kind == "entity")
            self.assertEqual(entity.status, "partial", entity.limitations)
            self.assertEqual(entity.strategy, "entity_geometry")

            # Use the writer's own paths instead of guessing the slug directory.
            geometry_file = result.packs.rp / "models" / "entity" / "ruby_golem.geo.json"
            self.assertTrue(geometry_file.is_file(), "the geometry was not written to the resource pack")
            document = json.loads(geometry_file.read_text(encoding="utf-8"))
            self.assertEqual(
                document["minecraft:geometry"][0]["description"]["identifier"],
                "geometry.golemmod.ruby_golem",
            )
            self.assertEqual(bone_count(document), 2)

    def test_entity_without_a_model_stays_manual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / "plain.jar"
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("fabric.mod.json", json.dumps({"id": "plainmod", "name": "Plain", "version": "1"}))
                archive.writestr("assets/plainmod/lang/en_us.json", json.dumps({"entity.plainmod.blob": "Blob"}))
            out = Path(tmp) / "out"
            result = Converter(
                ConversionOptions(output_dir=str(out), record_learning=False, report_formats=("json",))
            ).convert(jar)
            entity = next(f for f in result.features if f.kind == "entity")
            self.assertEqual(entity.status, "manual")


if __name__ == "__main__":
    unittest.main()
