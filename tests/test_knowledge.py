"""Tests for the knowledge base: loading, matching and the entry schema.

The converter refuses to invent strategies, so the KB is part of the executable
contract: a broken entry silently degrades a feature to ``manual``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from j2b.knowledge.base import (
    KNOWN_SIGNALS,
    KnowledgeBase,
    KnowledgeEntry,
    derive_signals,
)
from j2b.models import Feature


def feature(kind: str, name: str = "test", **data) -> Feature:
    return Feature(id=f"{kind}:{name}", kind=kind, name=name, display=name, data=data)


def best_named(kb: KnowledgeBase, feat: Feature, entry_id: str):
    """Best match restricted to one entry id, so shipped knowledge cannot interfere."""
    for entry, _score in kb.match(feat, limit=len(kb.entries)):
        if entry.id == entry_id:
            return entry
    return None


class BundledEntriesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = KnowledgeBase(overlay_path=Path(self.tmp.name) / "absent.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bundled_jsonl_is_loaded(self) -> None:
        stats = self.kb.stats()
        self.assertEqual(stats["load_errors"], [])
        self.assertGreater(stats["by_origin"].get("bundled", 0), 40, "entries.jsonl was not loaded")
        self.assertGreaterEqual(stats["entries"], stats["by_origin"]["builtin"])

    def test_every_entry_passes_audit(self) -> None:
        report = self.kb.audit()
        self.assertEqual(report["problems"], [], f"KB schema defects: {report['problems']}")
        self.assertTrue(report["ok"])

    def test_ids_are_unique_across_layers(self) -> None:
        ids = [entry.id for entry in self.kb.entries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_entry_is_documented(self) -> None:
        for entry in self.kb.entries:
            with self.subTest(entry=entry.id):
                self.assertTrue(entry.rationale.strip(), "missing rationale")
                self.assertTrue(entry.limitations, "missing limitations")
                self.assertTrue(entry.refs, "missing references")
                for ref in entry.refs:
                    self.assertTrue(ref["url"].startswith("http"), ref)

    def test_signal_vocabulary_is_closed(self) -> None:
        """Every token an entry matches on must be emittable by derive_signals."""
        for entry in self.kb.entries:
            for token in entry.required + entry.match_any:
                with self.subTest(entry=entry.id, token=token):
                    self.assertTrue(
                        token in KNOWN_SIGNALS or token.startswith("worldgen_"),
                        f"signal '{token}' has no producer",
                    )

    def test_derive_signals_emits_model_families(self) -> None:
        cases = {
            "minecraft:block/cube_all": "cube_all",
            "minecraft:block/cross": "cross_model",
            "minecraft:block/orientable": "orientable",
            "minecraft:block/cube_column": "cube_column",
        }
        for parent, token in cases.items():
            with self.subTest(parent=parent):
                signals = derive_signals(feature("block", "b", model_parent=parent))
                self.assertIn(token, signals)
                self.assertIn("block", signals)

    def test_derive_signals_namespace_tokens(self) -> None:
        self.assertIn("class:mixin", derive_signals(feature("mechanic", "m", classes=["a.b.MixinThing"])))
        self.assertIn("loader:fabric", derive_signals(feature("mechanic", "m", loader="quilt")))
        self.assertIn(
            "recipe:stonecutting",
            derive_signals(feature("recipe", "r", type="minecraft:stonecutting", recipe={})),
        )
        self.assertIn(
            "feature:ore",
            derive_signals(feature("worldgen", "w", category="ore", json={"type": "minecraft:ore"})),
        )


class MatchSemanticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.overlay = self.dir / "overlay.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_overlay(self, entries: list[dict]) -> None:
        self.overlay.write_text(json.dumps(entries), encoding="utf-8")

    def base(self, **overrides) -> dict:
        entry = {
            "id": "user.test",
            "title": "Test",
            "kind": "block",
            "strategy": "block.full_cube",
            "outcome": "converted",
            "rationale": "because",
            "limitations": ["none"],
            "refs": [{"title": "Wiki", "url": "https://wiki.bedrock.dev/"}],
            "verification": "verified",
        }
        entry.update(overrides)
        return entry

    def test_all_requires_every_signal(self) -> None:
        self.write_overlay([self.base(match={"all": ["block", "cube_all"]})])
        kb = KnowledgeBase(overlay_path=self.overlay)
        hit = kb.best(feature("block", "b", model_parent="minecraft:block/cube_all"))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.id, "user.test")
        miss = kb.best(feature("block", "b", model_parent="minecraft:block/cross"))
        self.assertNotEqual(getattr(miss, "id", None), "user.test")

    def test_any_requires_one_branch(self) -> None:
        self.write_overlay([self.base(match={"all": ["block"], "any": ["orientable", "cross_model"]})])
        kb = KnowledgeBase(overlay_path=self.overlay)
        self.assertIsNotNone(best_named(kb, feature("block", "b", model_parent="minecraft:block/orientable"), "user.test"))
        self.assertIsNone(best_named(kb, feature("block", "b", model_parent="minecraft:block/cube_all"), "user.test"))

    def test_overlay_cannot_be_unmatchable(self) -> None:
        self.write_overlay([self.base(id="user.empty", match={"all": []})])
        kb = KnowledgeBase(overlay_path=self.overlay)
        self.assertTrue(kb.load_errors)
        self.assertNotIn("user.empty", [entry.id for entry in kb.entries])

    def test_overlay_beats_bundled_entry_with_same_signals(self) -> None:
        self.write_overlay([self.base(id="user.override", match={"all": ["block", "cube_all"]})])
        kb = KnowledgeBase(overlay_path=self.overlay)
        best = best_named(kb, feature("block", "b", model_parent="minecraft:block/cube_all"), "user.override")
        self.assertEqual(best.id, "user.override")

    def test_longer_match_wins_over_shorter(self) -> None:
        self.write_overlay(
            [
                self.base(id="user.broad", match={"all": ["block"]}),
                self.base(id="user.precise", match={"all": ["block", "cube_all"]}),
            ]
        )
        kb = KnowledgeBase(overlay_path=self.overlay)
        cube = feature("block", "b", model_parent="minecraft:block/cube_all")
        pane = feature("block", "b", model_parent="minecraft:block/pane")
        self.assertEqual(best_named(kb, cube, "user.precise").id, "user.precise")
        self.assertEqual(best_named(kb, pane, "user.broad").id, "user.broad")

    def test_unknown_signal_is_flagged_by_audit(self) -> None:
        self.write_overlay([self.base(id="user.typo", match={"all": ["block", "cubic_alll"]})])
        kb = KnowledgeBase(overlay_path=self.overlay)
        problems = [p for p in kb.audit()["problems"] if p["id"] == "user.typo"]
        self.assertTrue(any("unknown signal" in p["problem"] for p in problems))


class EntryTest(unittest.TestCase):
    def test_both_schemas_normalise(self) -> None:
        legacy = KnowledgeEntry.from_dict({"id": "a", "kind": "block", "signals": ["block"]})
        modern = KnowledgeEntry.from_dict({"id": "b", "kind": "block", "match": {"all": ["block"], "any": ["cube"]}})
        self.assertEqual(legacy.required, ("block",))
        self.assertEqual(modern.required, ("block",))
        self.assertEqual(modern.match_any, ("cube",))
        self.assertTrue(legacy.applies({"block"}))
        self.assertFalse(legacy.applies(set()))

    def test_hypothesis_outcome_scores_below_verified(self) -> None:
        from j2b.knowledge.base import VERIFICATION_BONUS

        self.assertIn("hypothesis", VERIFICATION_BONUS)
        self.assertLess(VERIFICATION_BONUS["hypothesis"], VERIFICATION_BONUS["verified"])


if __name__ == "__main__":
    unittest.main()
