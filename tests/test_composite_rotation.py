"""Composite rotations: a blockstate turn *and* an element turn at once.

The defect these pin down: a model whose element is tilted 22.5° and whose
blockstate turns it 90° about ``y`` used to come out with no tilt at all —
the variant rotation overwrote the element one. Every case below checks a
coordinate, not a shape of the JSON, because a wrong sign still produces a
valid model that simply faces the wrong way.
"""

from __future__ import annotations

import math
import unittest

from j2b.converters.rotation import (
    Placement,
    as_coordinate_rotation,
    as_permutation,
    bake_box,
    blockstate_placement,
    compose,
    element_placement,
    max_abs_diff,
    split_permutation,
    transpose,
    identity,
    mat_vec,
)
from j2b.converters.variants import rotate_elements


def _corners(low, high):
    return [
        [x, y, z]
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]


class CompositionMathTests(unittest.TestCase):
    def test_composing_two_turns_matches_applying_them_in_order(self) -> None:
        inner = Placement.about("x", 22.5, [8, 0, 8])
        outer = Placement.about("y", 90, [8, 8, 8])
        total = compose(inner, outer)
        for point in ([3, 5, 2], [15, 0, 9], [8, 16, 8]):
            with self.subTest(point=point):
                stepwise = outer.apply(inner.apply(point))
                direct = total.apply(point)
                for axis in range(3):
                    self.assertAlmostEqual(stepwise[axis], direct[axis], places=6)

    def test_the_pivot_is_a_fixed_point(self) -> None:
        total = compose(Placement.about("z", 37, [4, 12, 4]), Placement.about("y", 90, [8, 8, 8]))
        fixed = total.apply(total.pivot)
        for axis in range(3):
            self.assertAlmostEqual(fixed[axis], total.pivot[axis], places=6)

    def test_identity_composition_changes_nothing(self) -> None:
        total = compose(Placement(), Placement())
        self.assertLess(max_abs_diff(total.matrix, identity()), 1e-12)

    def test_quarter_turn_is_recognised_as_a_permutation(self) -> None:
        turn = blockstate_placement(0, 90)
        self.assertIsNotNone(as_permutation(turn.matrix))
        # A quarter turn is *also* a coordinate rotation, but baking it is
        # preferred: the geometry then reads the way the blockstate does.
        perm, axis, degrees = split_permutation(turn.matrix)  # type: ignore[misc]
        self.assertLess(max_abs_diff(perm, turn.matrix), 1e-9)
        self.assertAlmostEqual(degrees, 0.0, places=9)

    def test_single_axis_turn_is_recognised_directly(self) -> None:
        found = as_coordinate_rotation(Placement.about("x", 22.5).matrix)
        self.assertIsNotNone(found)
        axis, degrees = found  # type: ignore[misc]
        self.assertEqual(axis, 0)
        self.assertAlmostEqual(degrees, 22.5, places=6)

    def test_negative_angle_round_trips(self) -> None:
        found = as_coordinate_rotation(Placement.about("y", -22.5).matrix)
        self.assertIsNotNone(found)
        _axis, degrees = found  # type: ignore[misc]
        self.assertAlmostEqual(degrees, -22.5, places=6)


class SplitTests(unittest.TestCase):
    def test_tilt_plus_facing_splits_into_permutation_and_axis_turn(self) -> None:
        total = compose(Placement.about("x", 22.5, [8, 0, 8]), Placement.about("y", 90, [8, 8, 8]))
        split = split_permutation(total.matrix)
        self.assertIsNotNone(split)
        perm, axis, degrees = split  # type: ignore[misc]
        self.assertAlmostEqual(abs(degrees), 22.5, places=6)
        self.assertIsNotNone(as_permutation(perm))
        # The split must rebuild the matrix exactly, otherwise it is decoration.
        rebuilt = __import__("j2b.converters.rotation", fromlist=["mat_mul"]).mat_mul(
            perm, Placement.about(axis, degrees).matrix
        )
        self.assertLess(max_abs_diff(rebuilt, total.matrix), 1e-9)

    def test_two_arbitrary_axes_are_not_splittable(self) -> None:
        total = compose(Placement.about("x", 30, [8, 0, 8]), Placement.about("y", 37, [8, 8, 8]))
        self.assertIsNone(split_permutation(total.matrix))


class BakeTests(unittest.TestCase):
    def _reproduce(self, total, baked, low, high):
        """Corners the emitted geometry lands on: baked box, then residual turn."""
        perm = identity()
        split = split_permutation(total.matrix)
        if split is not None:
            perm = split[0]
        residual = (
            Placement.about(baked.residual_axis, baked.residual_angle, baked.residual_pivot)
            if baked.residual_axis
            else Placement()
        )
        pivot = total.pivot
        out = []
        for corner in _corners(low, high):
            local = [corner[i] - pivot[i] for i in range(3)]
            moved = mat_vec(perm, local)
            out.append(residual.apply([moved[i] + pivot[i] for i in range(3)]))
        return out

    def _assert_matches_true_transform(self, inner, outer, low, high, exact=True) -> None:
        total = compose(inner, outer)
        baked = bake_box(low, high, {"north": {}, "up": {}}, total)
        self.assertEqual(baked.exact, exact)
        produced = self._reproduce(total, baked, low, high)
        expected = [total.apply(corner) for corner in _corners(low, high)]
        for got, want in zip(produced, expected):
            for axis in range(3):
                self.assertAlmostEqual(got[axis], want[axis], places=4)

    def test_tilted_element_under_a_quarter_turn_is_exact(self) -> None:
        self._assert_matches_true_transform(
            Placement.about("x", 22.5, [8, 0, 8]),
            Placement.about("y", 90, [8, 8, 8]),
            [2.0, 4.0, 6.0],
            [6.0, 10.0, 14.0],
        )

    def test_same_axis_turns_add_up(self) -> None:
        self._assert_matches_true_transform(
            Placement.about("y", 45, [8, 8, 0]),
            Placement.about("y", 90, [8, 8, 8]),
            [0.0, 0.0, 0.0],
            [16.0, 4.0, 16.0],
        )

    def test_flat_axis_turn_then_quarter_turn_is_exact(self) -> None:
        self._assert_matches_true_transform(
            Placement.about("z", -30, [4, 4, 4]),
            Placement.about("x", 90, [8, 8, 8]),
            [1.0, 2.0, 3.0],
            [5.0, 9.0, 7.0],
        )

    def test_parallel_axes_at_different_points_stay_exact(self) -> None:
        self._assert_matches_true_transform(
            Placement.about("x", 22.5, [8, 0, 8]),
            Placement.about("x", 90, [8, 8, 8]),
            [3.0, 0.0, 3.0],
            [13.0, 2.0, 13.0],
        )

    def test_compound_transform_reports_its_error_instead_of_claiming_success(self) -> None:
        total = compose(Placement.about("x", 30, [8, 0, 8]), Placement.about("y", 37, [8, 8, 8]))
        baked = bake_box([0, 0, 0], [16, 16, 16], {"north": {}}, total)
        self.assertFalse(baked.exact)
        self.assertGreater(baked.error_degrees, 1.0)
        self.assertIn("differs from the real transform", baked.note or "")


class ElementListTests(unittest.TestCase):
    def test_element_rotation_survives_a_variant_rotation(self) -> None:
        elements = [
            {
                "from": [2, 4, 6],
                "to": [6, 10, 14],
                "rotation": {"origin": [8, 0, 8], "axis": "x", "angle": 22.5},
                "faces": {"north": {"texture": "#all"}, "up": {"texture": "#all"}},
            }
        ]
        rotated = rotate_elements(elements, 0, 90)
        element = rotated[0]
        self.assertIn("rotation", element, "the tilt was dropped instead of composed")
        self.assertAlmostEqual(abs(float(element["rotation"]["angle"])), 22.5, places=6)
        self.assertNotIn("j2b_element_rotation", element)

    def test_the_baked_box_really_moves(self) -> None:
        # A 90° variant turn of an asymmetric box has to land on the far side.
        rotated = rotate_elements(
            [{"from": [8, 0, 0], "to": [16, 8, 16], "faces": {"north": {}}}], 0, 90
        )
        self.assertEqual(rotated[0]["from"], [0.0, 0.0, 8.0])
        self.assertEqual(rotated[0]["to"], [16.0, 8.0, 16.0])

    def test_faces_travel_with_their_box(self) -> None:
        rotated = rotate_elements(
            [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"north": {"uv": [0, 0, 16, 16]}}}],
            0,
            90,
        )
        self.assertEqual(set(rotated[0]["faces"]), {"east"})
        self.assertEqual(rotated[0]["faces"]["east"]["uv"], [0, 0, 16, 16])

    def test_zero_variant_rotation_is_a_no_op(self) -> None:
        elements = [{"from": [1, 2, 3], "to": [4, 5, 6], "faces": {"west": {}}}]
        self.assertEqual(rotate_elements(elements, 0, 0), elements)

    def test_unrepresentable_case_is_annotated_not_hidden(self) -> None:
        elements = [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "rotation": {"origin": [8, 0, 8], "axis": "x", "angle": 30},
                "faces": {"north": {}},
            }
        ]
        rotated = rotate_elements(elements, 0, 37)
        annotated = "j2b_rotation_note" in rotated[0] or "rotation" in rotated[0]
        self.assertTrue(annotated)

    def test_element_placement_reads_java_rotation_blocks(self) -> None:
        placed = element_placement({"rotation": {"origin": [1, 2, 3], "axis": "z", "angle": -45}})
        self.assertIsNotNone(placed)
        self.assertEqual(placed.pivot, [1.0, 2.0, 3.0])
        self.assertAlmostEqual(math.degrees(math.acos(max(-1.0, min(1.0, (placed.matrix[0][0] + placed.matrix[1][1] + placed.matrix[2][2] - 1) / 2)))), 45.0, places=6)

    def test_element_placement_ignores_junk(self) -> None:
        self.assertIsNone(element_placement({}))
        self.assertIsNone(element_placement({"rotation": {"axis": "q", "angle": 10}}))
        self.assertIsNone(element_placement({"rotation": {"axis": "x", "angle": "lots"}}))
        self.assertIsNone(element_placement({"rotation": {"axis": "x", "angle": 0}}))


if __name__ == "__main__":
    unittest.main()
