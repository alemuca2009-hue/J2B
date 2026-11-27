"""Exercise animation discovery, fidelity reports and the actual packaged resources."""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from j2b.converter import Converter
from j2b.models import ConversionOptions


def source(clips: dict, version: str = "1.8.0") -> dict:
    return {"format_version": version, "animations": clips}


class GeckoLibAnimationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def convert(self, files):
        jar = self.root / "test.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            for path, payload in files.items():
                archive.writestr("assets/" + path, json.dumps(payload) if not isinstance(payload, bytes) else payload)
        result = Converter(ConversionOptions(output_dir=str(self.root / "out"), record_learning=False)).convert(jar)
        self.assertFalse([c for c in result.validation if c.severity == "error"])
        self.result = result
        return [f for f in result.features if f.kind == "animation"]

    def one(self, clip):
        return self.convert({"example/animations/crane.animation.json": source({"action": clip})})[0]

    def output(self, feature):
        document = json.loads((self.result.packs.root / feature.outputs[0]).read_text(encoding="utf-8"))
        self.assertEqual(document["format_version"], "1.8.0")
        return document["animations"][feature.data["identifier"]]

    def test_units_timestamps_and_bone_case_survive_packaging(self):
        # GeckoLib divides translation by 16 only when applying the render matrix.
        # 16 model units must stay 16 in the exported JSON, on every axis.
        clip = {"animation_length": 1.25, "loop": "hold_on_last_frame", "bones": {"leftArm": {
            "position": {"0.0": [-16, 8, 32], "1.25": {"vector": [16, -32, 8], "easing": "linear"}},
            "rotation": [-90, 30, 45], "scale": [1, 2, 0.5],
        }}}
        feat = self.one(clip)
        self.assertEqual((feat.status, feat.strategy), ("converted", "animation_exact"))
        output = self.output(feat)
        self.assertEqual(output, {**clip, "bones": {"leftArm": {**clip["bones"]["leftArm"],
            "position": {"0.0": [-16, 8, 32], "1.25": [16, -32, 8]}}}})
        with zipfile.ZipFile(self.result.packs.mcaddon) as addon:
            packed = json.loads(addon.read(feat.outputs[0]))
        self.assertEqual(packed["animations"][feat.data["identifier"]], output)

    def test_native_discontinuous_keyframes_and_interpolation(self):
        frames = {"0.0": [1, 1, 1], "0.5": {"pre": [0, 1, 2], "post": [1, 2, 3], "lerp_mode": "catmullrom"}}
        feat = self.one({"bones": {"tail": {"scale": frames}}})
        self.assertEqual(feat.strategy, "animation_exact")
        self.assertEqual(self.output(feat)["bones"]["tail"]["scale"], frames)

    def test_molang_and_geckolib_loop_alias(self):
        feat = self.one({"loop": "loop", "bones": {"fin": {
            "rotation": ["Math.sin(q.anim_time * 360) * 20", 0, -45], "scale": 2}}})
        self.assertEqual(feat.strategy, "animation_exact")
        self.assertEqual(self.output(feat), {"loop": True, "bones": {"fin": {
            "rotation": ["math.sin(query.anim_time * 360) * 20", 0, -45], "scale": [2, 2, 2]}}})

    def test_custom_easing_preserves_endpoints_and_reports_loss(self):
        feat = self.one({"sound_effects": {"1": {"effect": "bell"}}, "bones": {
            "arm": {"rotation": {"0": [0, 0, 0], "1": {"vector": [90, 0, 0], "easing": "easeInQuad"}}}}})
        self.assertEqual((feat.status, feat.strategy), ("partial", "animation_approximate"))
        self.assertEqual(self.output(feat), {"bones": {"arm": {"rotation": {"0": [0, 0, 0], "1": [90, 0, 0]}}}})
        for lost in ("easeInQuad", "sound_effects"):
            self.assertIn(lost, " ".join(feat.limitations))

    def test_unknown_expressions_and_invalid_values_are_reported_per_channel(self):
        for value in ("query.mod_hook", "math.cos(0, 1)", "math.sin(", "0x12", float("nan"), True):
            with self.subTest(value=value):
                feat = self.one({"bones": {"head": {"position": {"0.5": [0, value, 0]}, "scale": 1}}})
                self.assertEqual(feat.status, "partial")
                self.assertEqual(self.output(feat)["bones"], {"head": {"scale": [1, 1, 1]}})
                self.assertIn("0.5s", " ".join(feat.limitations))

    def test_malformed_tracks_do_not_emit_empty_clips(self):
        for track in ({"-1": [0, 0, 0]}, {"NaN": [1, 0, 0]}, {"0": 0, "0.0": 1}, [], {}, {"0": {"easing": []}}):
            with self.subTest(track=track):
                feat = self.one({"bones": {"body": {"position": track}}})
                self.assertEqual((feat.strategy, feat.outputs), ("animation_manual", []))

    def test_empty_source_is_distinguished_from_unsupported_events(self):
        clips = {"placeholder": {"loop": True}, "event": {"timeline": {"0": "trigger"}}, "unreadable": None}
        features = self.convert({"m/animations/file.animation.json": source(clips)})
        self.assertEqual({f.name: (f.status, f.outputs) for f in features},
                         {"placeholder": ("skipped", []), "event": ("manual", []), "unreadable": ("manual", [])})

    def test_discovery_is_independent_of_entities_and_collision_safe(self):
        clips = {"move.walk": {"bones": {"body": {"position": [16, 0, 0]}}},
                 "move_walk": {"bones": {"body": {"position": [0, 16, 0]}}}}
        files = {f"{ns}/{folder}/bat.animation.json": source(clips) for ns in ("m", "n")
                 for folder in ("animations", "alt", "models/entity")}
        features = self.convert(files)
        self.assertEqual(len(features), 12)
        identifiers = [f.data["identifier"] for f in features]
        self.assertEqual(len(set(identifiers)), len(identifiers))
        self.assertEqual(len({f.outputs[0] for f in features}), len(features))
        for f in features:
            self.assertEqual(self.output(f), clips[f.name])
        self.assertEqual(identifiers, [f.data["identifier"] for f in self.convert(dict(reversed(files.items())))])
        report = json.loads(Path(self.result.reports["json"]).read_text(encoding="utf-8"))
        self.assertTrue(all(f["strategy"] == "animation_exact" and f["outputs"] for f in report["features"]))

    def test_invalid_file_is_visible_and_other_sources_still_convert(self):
        feats = self.convert({"m/bad.animation.json": b"{broken",
                              "m/good.animation.json": source({"idle": {"bones": {"body": {"scale": 1}}}}, "9.9.0")})
        self.assertEqual([f.strategy for f in feats], ["animation_unreadable", "animation_approximate"])
        self.assertTrue(any("9.9.0" in note for note in feats[1].limitations))

    def test_animation_in_entity_models_directory_is_not_a_geometry_candidate(self):
        path = "m/models/entity/bat.animation.json"
        self.convert({"m/lang/en_us.json": {"entity.m.bat": "Bat"},
                      path: source({"idle": {"bones": {"body": {"scale": 1}}}})})
        entity = next(f for f in self.result.features if f.kind == "entity")
        self.assertEqual(entity.data["model_candidates"], [])
