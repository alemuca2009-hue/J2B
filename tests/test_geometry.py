"""Java ``elements`` -> Bedrock cubes: the parts that are exact and the parts that are not.

Every assertion here is about a coordinate that a viewer would notice: an
eight-unit shift on the wrong axis puts a model half a block away from its
collision box, and a dropped rotation turns a cog back into a slab.
"""

from __future__ import annotations

import unittest

from j2b.converters.geometry import (
    CubeResult,
    build_geometry,
    collision_box,
    elements_to_cubes,
)


def _material(element, face):  # noqa: ANN001, ARG001
    return "block"


def _one(element: dict) -> CubeResult:
    return elements_to_cubes([element], _material)


class CubePlacementTests(unittest.TestCase):
    def test_origin_is_shifted_to_bedrocks_centre(self) -> None:
        result = _one({"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"north": {"uv": [0, 0, 16, 16]}}})
        cube = result.cubes[0]
        self.assertEqual(cube["origin"], [-8.0, 0.0, -8.0])
        self.assertEqual(cube["size"], [16.0, 16.0, 16.0])

    def test_off_centre_detail_keeps_its_vertical_offset(self) -> None:
        result = _one({"from": [4, 6, 4], "to": [12, 10, 12], "faces": {"up": {"uv": [0, 0, 8, 4]}}})
        self.assertEqual(result.cubes[0]["origin"], [-4.0, 6.0, -4.0])
        self.assertEqual(result.cubes[0]["size"], [8.0, 4.0, 8.0])

    def test_negative_size_is_normalised_and_reported(self) -> None:
        result = _one({"from": [12, 0, 0], "to": [4, 16, 16], "faces": {"north": {"uv": [0, 0, 8, 16]}}})
        self.assertEqual(result.cubes[0]["origin"], [-4.0, 0.0, -8.0])
        self.assertTrue(result.approximated)
        self.assertTrue(any("negative size" in note for note in result.notes))


class RotationTests(unittest.TestCase):
    def test_quarter_turn_is_exact_and_keeps_the_pivot(self) -> None:
        result = _one(
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 90},
                "faces": {"north": {"uv": [0, 0, 16, 16]}},
            }
        )
        cube = result.cubes[0]
        self.assertEqual(cube["rotation"], [0.0, 90.0, 0.0])
        self.assertEqual(cube["pivot"], [0.0, 8.0, 0.0])
        self.assertFalse(result.approximated)

    def test_fractional_angle_is_kept_not_dropped(self) -> None:
        result = _one(
            {
                "from": [7, 0, 7],
                "to": [9, 16, 9],
                "rotation": {"origin": [8, 0, 8], "axis": "x", "angle": 22.5},
                "faces": {"north": {"uv": [0, 0, 2, 16]}},
            }
        )
        cube = result.cubes[0]
        self.assertEqual(cube["rotation"], [22.5, 0.0, 0.0])
        self.assertEqual(cube["pivot"], [0.0, 0.0, 0.0])
        # Kept, but flagged: the shape is right while shading is not.
        self.assertTrue(result.approximated)
        self.assertTrue(any("22.5" in note for note in result.notes))

    def test_pivot_tracks_the_authored_origin(self) -> None:
        result = _one(
            {
                "from": [2, 2, 2],
                "to": [14, 14, 14],
                "rotation": {"origin": [2, 14, 8], "axis": "z", "angle": -90},
                "faces": {"up": {"uv": [0, 0, 12, 12]}},
            }
        )
        self.assertEqual(result.cubes[0]["pivot"], [-6.0, 14.0, 0.0])
        self.assertEqual(result.cubes[0]["rotation"], [0.0, 0.0, -90.0])

    def test_rotated_cube_claims_no_collision_box(self) -> None:
        result = _one(
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45},
                "faces": {"north": {"uv": [0, 0, 16, 16]}},
            }
        )
        self.assertIsNone(collision_box(result.cubes))


class UvTests(unittest.TestCase):
    def test_missing_uv_uses_the_box_size_not_the_whole_texture(self) -> None:
        result = _one({"from": [0, 0, 0], "to": [4, 12, 16], "faces": {"north": {}}})
        face = result.cubes[0]["uv"]["north"]
        self.assertEqual(face["uv"], [0.0, 0.0])
        self.assertEqual(face["uv_size"], [4.0, 12.0])

    def test_declared_uv_travels_unchanged(self) -> None:
        result = _one({"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"east": {"uv": [4, 2, 20, 18]}}})
        self.assertEqual(result.cubes[0]["uv"]["east"]["uv_size"], [16.0, 16.0])

    def test_up_and_down_faces_are_turned_180_degrees(self) -> None:
        result = _one(
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {"up": {"uv": [4, 8, 8, 12]}, "down": {"uv": [4, 8, 8, 12]}},
            }
        )
        uv = result.cubes[0]["uv"]
        for face in ("up", "down"):
            self.assertEqual(uv[face]["uv"], [8.0, 12.0])
            self.assertEqual(uv[face]["uv_size"], [-4.0, -4.0])

    def test_side_faces_keep_their_uv_as_authored(self) -> None:
        result = _one({"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"north": {"uv": [4, 8, 8, 12]}}})
        self.assertEqual(result.cubes[0]["uv"]["north"]["uv"], [4.0, 8.0])
        self.assertEqual(result.cubes[0]["uv"]["north"]["uv_size"], [4.0, 4.0])

    def test_face_rotation_becomes_uv_rotation(self) -> None:
        result = _one(
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {"up": {"uv": [0, 0, 16, 16], "rotation": 90}},
            }
        )
        face = result.cubes[0]["uv"]["up"]
        self.assertEqual(face["uv_rotation"], 90.0)
        document = build_geometry("geometry.test", result.cubes)
        # uv_rotation needs the 1.16.0 schema; plain models stay on 1.12.0.
        self.assertEqual(document["format_version"], "1.16.0")

    def test_plain_model_stays_on_the_1_12_schema(self) -> None:
        result = _one({"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"up": {"uv": [0, 0, 16, 16]}}})
        document = build_geometry("geometry.test", result.cubes)
        self.assertEqual(document["format_version"], "1.12.0")
        geometry = document["minecraft:geometry"][0]
        self.assertEqual(geometry["bones"][0]["cubes"][0]["origin"], [-8.0, 0.0, -8.0])


if __name__ == "__main__":
    unittest.main()
