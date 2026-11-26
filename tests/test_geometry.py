"""Java ``elements`` -> Bedrock cubes: the parts that are exact and the parts that are not.

Every assertion here is about a coordinate that a viewer would notice: an
eight-unit shift on the wrong axis puts a model half a block away from its
collision box, and a dropped rotation turns a cog back into a slab.
"""

from __future__ import annotations

import unittest

from j2b.converters.geometry import (
    CubeResult,
    apply_rescale,
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
        self.assertEqual(cube["rotation"], [0.0, -90.0, 0.0])
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
        self.assertEqual(cube["rotation"], [-22.5, 0.0, 0.0])
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
        self.assertEqual(result.cubes[0]["pivot"], [6.0, 14.0, 0.0])
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


class BedrockMirrorConventionTests(unittest.TestCase):
    """The X mirror and the rotation signs, pinned to a game-verified export.

    Bedrock geometry is defined in a space that mirrors X relative to Java's, so
    ``origin.x`` is ``8 - to.x`` and a rotation is negated on X and Y and kept on
    Z. Every one of those three signs was wrong before this test existed, and
    the only visible symptom was a model that loaded and looked plausible while
    being flipped east to west.

    The expected values below are vanilla ``block/cross`` as Blockbench exports
    it; the same output is the ``cross`` golden that ``mc-model-geo`` uses to
    lock its own converter, so it is verified in game rather than argued from
    first principles.
    """

    CROSS = [
        {"from": [0, 0, 8], "to": [16, 16, 8], "rotation": {"origin": [8, 0, 8], "axis": "y", "angle": 45}},
        {"from": [0, 0, 8], "to": [16, 16, 8], "rotation": {"origin": [8, 0, 8], "axis": "y", "angle": -45}},
    ]

    def test_vanilla_cross_matches_the_bedrock_export(self) -> None:
        result = elements_to_cubes(self.CROSS, _material)
        expected = [
            {"origin": [-8, 0, 0], "size": [16, 16, 0], "pivot": [0, 0, 0], "rotation": [0, 45, 0]},
            {"origin": [-8, 0, 0], "size": [16, 16, 0], "pivot": [0, 0, 0], "rotation": [0, -45, 0]},
        ]
        for cube, want in zip(result.cubes, expected):
            self.assertEqual(cube["origin"], [float(v) for v in want["origin"]])
            self.assertEqual(cube["size"], [float(v) for v in want["size"]])
            self.assertEqual(cube["pivot"], [float(v) for v in want["pivot"]])
            self.assertEqual(cube["rotation"], [float(v) for v in want["rotation"]])

    def test_an_asymmetric_box_is_mirrored_east_west(self) -> None:
        # Java authors this flush against the east edge; Bedrock's mirror puts
        # it flush against the west edge, which is the same wall.
        result = _one({"from": [12, 0, 0], "to": [16, 8, 16], "faces": {"up": {"uv": [0, 0, 4, 16]}}})
        self.assertEqual(result.cubes[0]["origin"], [-8.0, 0.0, -8.0])
        # Its mirror image, authored on the other side, is the one that lands
        # at the opposite corner -- so the pair cannot both be right.
        other = _one({"from": [0, 0, 0], "to": [4, 8, 16], "faces": {"up": {"uv": [0, 0, 4, 16]}}})
        self.assertEqual(other.cubes[0]["origin"], [4.0, 0.0, -8.0])

    def test_z_rotation_is_not_negated(self) -> None:
        # X is mirrored, so a turn about Y flips sign; a turn about Z shares the
        # mirror axis and therefore does not.
        result = _one(
            {
                "from": [4, 4, 4],
                "to": [12, 12, 12],
                "rotation": {"origin": [8, 8, 8], "axis": "z", "angle": 30},
                "faces": {"north": {"uv": [0, 0, 8, 8]}},
            }
        )
        self.assertEqual(result.cubes[0]["rotation"], [0.0, 0.0, 30.0])


class RescaleTests(unittest.TestCase):
    """Java ``rescale`` is not a limitation any more: it is a smaller box.

    ``FaceBakery`` scales a rotated element about the rotation origin before it
    rotates it, so on Bedrock -- bounds plus a pivot -- the same shape is a box
    contracted toward that pivot. Getting the centre wrong instead of the
    origin moves the part: a 0.5 arm anchored off-centre would end up eight
    units from where the machine expects it.
    """

    ELEMENT = {
        "from": [2, 4, 6],
        "to": [14, 12, 10],
        "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45, "rescale": 0.5},
        "faces": {
            "north": {"uv": [0, 0, 12, 8]},
            "up": {"uv": [0, 8, 12, 12]},
        },
    }

    def test_box_contracts_toward_the_rotation_origin(self) -> None:
        (cube,) = elements_to_cubes([apply_rescale([self.ELEMENT])[0]], _material).cubes
        # Every coordinate moves halfway to the pivot at (8, 8, 8):
        # (2,4,6)-(14,12,10) becomes (5,6,7)-(11,10,9).
        self.assertEqual(cube["origin"], [-3.0, 6.0, -1.0])
        self.assertEqual(cube["size"], [6.0, 4.0, 2.0])
        self.assertEqual(cube["pivot"], [0.0, 8.0, 0.0])

    def test_uvs_keep_their_authored_region(self) -> None:
        (cube,) = elements_to_cubes([apply_rescale([self.ELEMENT])[0]], _material).cubes
        # Java squashes the same texture region onto the smaller quad.
        self.assertEqual(cube["uv"]["north"]["uv"], [0.0, 0.0])
        self.assertEqual(cube["uv"]["north"]["uv_size"], [12.0, 8.0])

    def test_rescale_no_longer_produces_a_limitation(self) -> None:
        result = elements_to_cubes([apply_rescale([self.ELEMENT])[0]], _material)
        self.assertEqual([note for note in result.notes if "rescale" in note], [])

    def test_off_centre_origin_is_the_point_that_scales(self) -> None:
        element = {
            "from": [0, 0, 0],
            "to": [8, 8, 8],
            "rotation": {"origin": [0, 8, 8], "axis": "x", "angle": 22.5, "rescale": 0.25},
            "faces": {"north": {"uv": [0, 0, 8, 8]}},
        }
        (cube,) = elements_to_cubes([apply_rescale([element])[0]], _material).cubes
        self.assertEqual(cube["size"], [2.0, 2.0, 2.0])
        self.assertEqual(cube["pivot"], [8.0, 8.0, 0.0])

    def test_rescale_without_a_rotation_is_ignored_like_java(self) -> None:
        element = {
            "from": [0, 0, 0],
            "to": [16, 16, 16],
            "rotation": {"rescale": 0.5},
            "faces": {"north": {"uv": [0, 0, 16, 16]}},
        }
        self.assertEqual(apply_rescale([element])[0], element)

    def test_nonsense_factors_fall_back_to_full_size(self) -> None:
        for bad in (0, -1, "nope", None, float("nan")):
            element = {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45, "rescale": bad},
                "faces": {"north": {"uv": [0, 0, 16, 16]}},
            }
            self.assertEqual(apply_rescale([element])[0], element, msg=repr(bad))

    def test_factor_is_consumed_once(self) -> None:
        once = apply_rescale([self.ELEMENT])[0]
        twice = apply_rescale([once])[0]
        self.assertEqual(once, twice)

    def test_rescaled_element_survives_variant_baking(self) -> None:
        from j2b.converters.variants import rotate_elements

        element = {
            "from": [1, 4, 7],
            "to": [9, 12, 9],
            "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 22.5, "rescale": 0.5},
            "faces": {"north": {"uv": [0, 0, 8, 8]}},
        }
        (baked,) = rotate_elements(apply_rescale([element]), 0, 90)
        # Rescaled extents are 4 x 4 x 1; a quarter turn about the centre swaps
        # X and Z and must leave the sizes alone.
        extents = [round(baked["to"][axis] - baked["from"][axis], 6) for axis in range(3)]
        self.assertEqual(sorted(extents), [1.0, 4.0, 4.0])
        self.assertAlmostEqual(extents[1], 4.0, places=6)
        # And the fractional tilt still reaches Bedrock as a rotation.
        self.assertEqual(baked["rotation"]["axis"], "y")
        self.assertAlmostEqual(baked["rotation"]["angle"], 22.5, places=6)
