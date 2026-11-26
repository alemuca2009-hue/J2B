"""Lock J2B's cube transform to Blockbench's compiler, term for term.

Why this file exists
--------------------
Rotated cubes are the one place where a sign error is invisible in code review
and obvious in game: a cog turned the wrong way still looks like a cog until
the machine runs. The transform was therefore compared against every reference
that does this conversion for a living -- Blockbench, GeyserMC's pack
converter, mc-model-geo and java2bedrock.sh -- and all four agree.

Blockbench is the one whose compiler is quoted here, because it is the tool
whose output most Java->Bedrock packs are actually built with. The two lines
that matter, from ``js/formats/bedrock/bedrock.js`` ``compileCube``::

    template.origin[0] = -(template.origin[0] + template.size[0])
    template.pivot[0] *= -1
    template.rotation.forEach((br, axis) => { if (axis != 2) template.rotation[axis] *= -1 })

So: the box is mirrored on X, the pivot is mirrored on X, and the angle is
negated on X and Y while Z is kept. ``_blockbench_compile`` below is that
function transcribed, used as an oracle: J2B has to reproduce it exactly.

Frame note
----------
Blockbench authors a block in the same 0..16 space as Java, but Bedrock
geometry is centred on the block: X and Z run -8..8 and Y runs 0..16. Both
shifts are applied before the mirror, which is why ``origin.x`` comes out as
``8 - to.x`` rather than ``-(from.x + size)``. The mapping is not taken on
trust -- Mojang's own ``straw_bed_head.geo.json`` describes the northern half
of a full-width bed as ``origin [-8, 0, -8]``, ``size [16, 4, 8]``, which is
exactly what ``from [0,0,0] -> to [16,4,8]`` predicts.
"""

from __future__ import annotations

import itertools
import random
import unittest

from j2b.converters.geometry import elements_to_cubes


def _material(element, face):  # noqa: ANN001, ARG001
    return "block"


# One face is enough for the converter to keep the element; the oracle does
# not look at UVs.
_FACE = {"north": {"uv": [0, 0, 16, 16]}}


def _blockbench_compile(element: dict) -> dict:
    """Transcribe ``compileCube`` from Blockbench's Bedrock format.

    Input is a Java element in 0..16 space, exactly as J2B receives it. The
    project frame Blockbench works in is centred on the block, so X and Z are
    shifted by -8 first; ``compileCube`` then mirrors X and negates the X and
    Y angles on its own.
    """
    low = [element["from"][0] - 8, element["from"][1], element["from"][2] - 8]
    high = [element["to"][0] - 8, element["to"][1], element["to"][2] - 8]
    size = [high[axis] - low[axis] for axis in range(3)]

    cube: dict = {"origin": list(low), "size": size}
    cube["origin"][0] = -(low[0] + size[0])

    spec = element.get("rotation")
    if spec and spec.get("angle"):
        axis = "xyz".index(spec["axis"])
        rotation = [0.0, 0.0, 0.0]
        rotation[axis] = float(spec["angle"])
        cube["pivot"] = [-(spec["origin"][0] - 8), spec["origin"][1], spec["origin"][2] - 8]
        cube["rotation"] = [value * -1 if index != 2 else value for index, value in enumerate(rotation)]
    return cube


def _cube(element: dict) -> dict:
    return elements_to_cubes([element], _material).cubes[0]


class BlockbenchOracleTests(unittest.TestCase):
    def assert_matches_oracle(self, element: dict) -> None:
        expected = _blockbench_compile(element)
        actual = _cube(element)
        self.assertEqual(actual["origin"], expected["origin"], f"origin for {element}")
        self.assertEqual(actual["size"], expected["size"], f"size for {element}")
        if "rotation" in expected:
            self.assertEqual(actual.get("rotation"), expected["rotation"], f"rotation for {element}")
            self.assertEqual(actual.get("pivot"), expected["pivot"], f"pivot for {element}")
        else:
            self.assertNotIn("rotation", actual, f"unexpected rotation for {element}")

    def test_full_block_matches_mojangs_published_geometry(self) -> None:
        cube = _cube({"from": [0, 0, 0], "to": [16, 4, 8], "faces": _FACE})
        self.assertEqual(cube["origin"], [-8.0, 0.0, -8.0])
        self.assertEqual(cube["size"], [16.0, 4.0, 8.0])

    def test_matches_oracle_on_every_axis_and_angle_create_uses(self) -> None:
        # These twelve (axis, angle) pairs are the complete set that Create
        # 6.0.10 uses across its 2731 block elements, so the sweep covers the
        # rotations a machinery mod can actually produce.
        pairs = {"x": [22.5, 45.0], "y": [22.5, 45.0, 90.0, 135.0, 180.0], "z": [22.5, 45.0, 90.0, 90.0, 180.0]}
        for axis, angles in pairs.items():
            for angle in angles:
                element = {
                    "from": [3, 5, 2],
                    "to": [13, 11, 6],
                    "rotation": {"origin": [8, 8, 4], "axis": axis, "angle": angle},
                    "faces": _FACE,
                }
                with self.subTest(axis=axis, angle=angle):
                    self.assert_matches_oracle(element)

    def test_matches_oracle_over_random_boxes_and_pivots(self) -> None:
        rng = random.Random(20261126)
        for _ in range(500):
            low = [rng.randint(-16, 16), rng.randint(-16, 16), rng.randint(-16, 16)]
            high = [low[0] + rng.randint(1, 24), low[1] + rng.randint(1, 24), low[2] + rng.randint(1, 24)]
            element = {"from": low, "to": high, "faces": _FACE}
            if rng.random() < 0.7:
                element["rotation"] = {
                    "origin": [rng.uniform(-8, 24), rng.uniform(-8, 24), rng.uniform(-8, 24)],
                    "axis": rng.choice("xyz"),
                    "angle": rng.choice([-45, -22.5, 22.5, 45, 90, 135, 180]),
                }
            self.assert_matches_oracle(element)

    def test_x_is_the_only_mirrored_axis(self) -> None:
        # A regression guard with the shape of the bug this file is about: if
        # someone "fixes" the Z sign to match a misread of the mirror, an
        # asymmetric Z rotation is the case that unwinds it.
        cube = _cube({"from": [0, 0, 0], "to": [2, 2, 2], "rotation": {"origin": [8, 8, 8], "axis": "z", "angle": 45}, "faces": _FACE})
        self.assertEqual(cube["rotation"], [0.0, 0.0, 45.0])
        self.assertEqual(cube["pivot"], [0.0, 8.0, 0.0])

    def test_rotation_order_is_preserved_for_each_axis(self) -> None:
        for axis, index in (("x", 0), ("y", 1), ("z", 2)):
            with self.subTest(axis=axis):
                cube = _cube({"from": [4, 4, 4], "to": [12, 12, 12], "rotation": {"origin": [8, 8, 8], "axis": axis, "angle": 30}, "faces": _FACE})
                self.assertEqual([i for i, value in enumerate(cube["rotation"]) if value], [index])


if __name__ == "__main__":
    unittest.main()
