"""End-to-end tests: build a fixture jar, convert it, assert on the output.

Run with ``python -m unittest discover -s tests`` from the project root.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from j2b.converter import ConversionError, Converter  # noqa: E402
from j2b.history import ConversionHistory  # noqa: E402
from j2b.knowledge import KnowledgeBase, derive_signals  # noqa: E402
from j2b.models import ConversionOptions, Feature  # noqa: E402
from j2b.validate import validate_packs  # noqa: E402

from make_test_jar import build  # noqa: E402


class ConversionFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.tmp.name) / "data"
        os.environ["J2B_DATA_DIR"] = str(cls.data_dir)
        cls.jar = build(Path(cls.tmp.name) / "TestMod-1.0.0.jar")
        cls.result = Converter(
            options=ConversionOptions(output_dir=str(Path(cls.tmp.name) / "out"), make_mcaddon=True),
            knowledge=KnowledgeBase(),
        ).convert(cls.jar)
        cls.by_id = {feature.id: feature for feature in cls.result.features}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    # -- scanning ---------------------------------------------------------
    def test_scan_finds_each_kind(self) -> None:
        kinds = {feature.kind for feature in self.result.features}
        self.assertEqual(kinds, {"block", "item", "recipe", "entity", "worldgen", "gui", "mechanic"})

    def test_metadata_read(self) -> None:
        self.assertEqual(self.result.mod.mod_id, "testmod")
        self.assertEqual(self.result.mod.loader, "fabric")
        self.assertEqual(self.result.mod.version, "1.0.0")

    # -- conversion -------------------------------------------------------
    def test_block_converted_with_texture(self) -> None:
        feature = self.by_id["testmod:ruby_ore"]
        self.assertEqual(feature.status, "converted")
        block = json.loads((self.result.packs.bp / "blocks" / "testmod_ruby_ore.json").read_text())
        material = block["minecraft:block"]["components"]["minecraft:material_instances"]["*"]
        self.assertEqual(material["render_method"], "opaque")
        texture = self.result.packs.rp / "textures" / "blocks" / f"{material['texture']}.png"
        self.assertTrue(texture.is_file())

    def test_cross_model_gets_geometry_and_alpha_test(self) -> None:
        block = json.loads((self.result.packs.bp / "blocks" / "testmod_ruby_flower.json").read_text())
        components = block["minecraft:block"]["components"]
        self.assertEqual(components["minecraft:material_instances"]["*"]["render_method"], "alpha_test")
        self.assertTrue((self.result.packs.rp / "models" / "blocks" / "testmod_ruby_flower.geo.json").is_file())

    def test_tool_is_downgraded_by_knowledge_base(self) -> None:
        feature = self.by_id["testmod:ruby_pickaxe"]
        self.assertEqual(feature.status, "partial")
        self.assertTrue(any("durability" in text.lower() for text in feature.limitations))

    def test_tag_recipe_is_partial_and_reports_loss(self) -> None:
        feature = self.by_id["testmod:recipe:ruby_block"]
        self.assertEqual(feature.status, "partial")
        recipe = json.loads((self.result.packs.bp / "recipes" / "testmod_ruby_block.json").read_text())
        key = recipe["minecraft:recipe_shaped"]["key"]["#"]
        self.assertEqual(key["item"], "minecraft:oak_planks")
        self.assertTrue(any("tag" in text.lower() for text in feature.limitations))

    def test_smithing_recipe_is_unsupported(self) -> None:
        feature = self.by_id["testmod:recipe:ruby_smithing"]
        self.assertEqual(feature.status, "unsupported")
        self.assertEqual(feature.outputs, [])

    def test_ore_feature_and_rule_written(self) -> None:
        feature = self.by_id["testmod:configured_feature:ruby_ore"]
        self.assertEqual(feature.status, "converted")
        rule = json.loads((self.result.packs.bp / "feature_rules" / "testmod_ruby_ore_rule.json").read_text())
        body = rule["minecraft:feature_rules"]
        self.assertEqual(body["description"]["places_feature"], "testmod:ruby_ore")
        self.assertEqual(body["distribution"]["y"]["extent"], [-60, 40])
        self.assertEqual(body["distribution"]["iterations"], 4)

    def test_placed_feature_folds_into_rule(self) -> None:
        feature = self.by_id["testmod:placed_feature:ruby_ore_placed"]
        self.assertEqual(feature.status, "skipped")
        self.assertTrue(any(issue.code == "PLACEMENT_FOLDED" for issue in feature.issues))

    def test_entity_is_manual_not_faked(self) -> None:
        feature = self.by_id["testmod:entity:ruby_golem"]
        self.assertEqual(feature.status, "manual")
        self.assertFalse(list(self.result.packs.bp.glob("entities/*.json")))
        self.assertTrue(any(issue.code == "ENTITY_NEEDS_REBUILD" for issue in feature.issues))

    def test_mechanic_features_are_reported_with_precedent(self) -> None:
        command = self.by_id["mechanic:foocommand"]
        self.assertEqual(command.strategy, "script_api")
        self.assertTrue(command.kb_refs)

    # -- pack integrity ---------------------------------------------------
    def test_validation_has_no_errors(self) -> None:
        errors = [check for check in self.result.validation if check.severity == "error"]
        self.assertEqual(errors, [], [check.message for check in errors])

    def test_standalone_validation_matches(self) -> None:
        checks = validate_packs(self.result.packs.bp, self.result.packs.rp)
        self.assertFalse([check for check in checks if check.severity == "error"])

    def test_manifests_use_distinct_uuids(self) -> None:
        bp = json.loads((self.result.packs.bp / "manifest.json").read_text())
        rp = json.loads((self.result.packs.rp / "manifest.json").read_text())
        self.assertNotEqual(bp["header"]["uuid"], rp["header"]["uuid"])
        self.assertEqual(bp["modules"][0]["type"], "data")
        self.assertEqual(rp["modules"][0]["type"], "resources")

    def test_mcaddon_contains_both_packs(self) -> None:
        import zipfile

        self.assertIsNotNone(self.result.packs.mcaddon)
        with zipfile.ZipFile(self.result.packs.mcaddon) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.startswith("behavior_pack/") for name in names))
        self.assertTrue(any(name.startswith("resource_pack/") for name in names))

    def test_reports_written(self) -> None:
        self.assertEqual(set(self.result.reports), {"json", "md", "html"})
        for path in self.result.reports.values():
            self.assertTrue(Path(path).is_file())
        markdown = Path(self.result.reports["md"]).read_text()
        self.assertIn("Manual work checklist", markdown)
        self.assertIn("testmod:entity:ruby_golem", markdown)

    # -- memory -----------------------------------------------------------
    def test_history_recorded(self) -> None:
        self.assertIsNotNone(self.result.history_id)
        stats = ConversionHistory().stats()
        self.assertTrue(stats["available"])
        self.assertGreaterEqual(stats["conversions"], 1)

    def test_deterministic_uuids(self) -> None:
        self.result.compute_stats()
        same = Converter(
            options=ConversionOptions(output_dir=str(Path(self.tmp.name) / "out2")),
            knowledge=KnowledgeBase(),
        ).convert(self.jar)
        bp1 = json.loads((self.result.packs.bp / "manifest.json").read_text())
        bp2 = json.loads((same.packs.bp / "manifest.json").read_text())
        self.assertEqual(bp1["header"]["uuid"], bp2["header"]["uuid"])


class KnowledgeBaseTests(unittest.TestCase):
    def test_more_specific_entry_wins(self) -> None:
        kb = KnowledgeBase()
        block = Feature(
            id="x:y",
            kind="block",
            name="y",
            data={"variants": 4, "model_parent": "minecraft:block/cube_all"},
        )
        best = kb.best(block)
        self.assertIsNotNone(best)
        # Either the builtin or the bundled entry may win, but both must say
        # "partial": a block with four variants never converts losslessly.
        self.assertEqual(best.outcome, "partial")
        self.assertIn("blockstate", " ".join([best.title.lower(), *[l.lower() for l in best.limitations]]))

    def test_signals_are_derived_from_assets(self) -> None:
        item = Feature(id="x:y", kind="item", name="ruby_pickaxe", data={"model_parent": "minecraft:item/handheld"})
        self.assertIn("item_handheld", derive_signals(item))

    def test_every_entry_is_citable(self) -> None:
        for entry in KnowledgeBase().entries:
            self.assertTrue(entry.required or entry.match_any, entry.id)
            self.assertTrue(entry.rationale, entry.id)


class FailureTests(unittest.TestCase):
    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ConversionError):
            Converter(options=ConversionOptions(output_dir=tempfile.mkdtemp())).convert("/nonexistent.jar")

    def test_garbage_archive_raises(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jar", delete=False) as handle:
            handle.write(b"not a zip")
            path = handle.name
        try:
            with self.assertRaises(ConversionError):
                Converter(options=ConversionOptions(output_dir=tempfile.mkdtemp())).convert(path)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
