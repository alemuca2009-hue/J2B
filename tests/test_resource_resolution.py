import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from j2b.analyzer.mod_archive import ModArchive
from j2b.analyzer.model_resolver import ModelResolver
from j2b.converter import Converter
from j2b.models import ConversionOptions
from j2b.cli import build_parser
from j2b.fixtures import _png


class ResourceResolutionTests(unittest.TestCase):
    def test_child_overrides_survive_alias_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / 'models.zip'
            with zipfile.ZipFile(jar, 'w') as z:
                z.writestr('assets/mod/models/block/child.json', json.dumps({
                    'parent': 'block/parent', 'textures': {'all': 'mod:block/red'},
                    'ambientocclusion': True, 'gui_light': 'front',
                    'display': {'gui': {'scale': [2, 2, 2]}}}))
                z.writestr('assets/minecraft/models/block/parent.json', json.dumps({
                    'parent': 'block/cube_all', 'textures': {'all': 'minecraft:block/stone', 'particle': '#all'},
                    'ambientocclusion': False, 'gui_light': 'side',
                    'display': {'gui': {'scale': [1, 1, 1]}, 'ground': {'scale': [1, 1, 1]}}}))
            with ModArchive(jar) as archive:
                model = ModelResolver(archive).resolve('mod:block/child')
                self.assertEqual(model.textures['particle'], 'mod:block/red')
                self.assertEqual(model.textures['all'], 'mod:block/red')
                self.assertTrue(model.elements)
                self.assertTrue(model.ambient_occlusion)
                self.assertEqual(model.gui_light, 'front')
                self.assertEqual(model.display['gui']['scale'], [2, 2, 2])
                self.assertIn('ground', model.display)

    def test_missing_mod_model_cannot_borrow_vanilla_shape(self):
        self.assertFalse(ModelResolver(None).resolve('mod:block/cube_all').resolved)
        self.assertTrue(ModelResolver(None).resolve('minecraft:block/cube_all').resolved)

    def test_reference_pixels_are_packaged_and_mod_pixels_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jar, reference = root / 'mod.jar', root / 'reference.zip'
            texture = 'assets/minecraft/textures/item/stick.png'
            expected = _png(colour=(100, 50, 10))
            with zipfile.ZipFile(reference, 'w') as z:
                z.writestr(texture, expected)
            for override in (False, True):
                with zipfile.ZipFile(jar, 'w') as z:
                    z.writestr('assets/mod/models/item/tool.json', json.dumps({
                        'parent': 'minecraft:item/generated', 'textures': {'layer0': 'minecraft:item/stick'}}))
                    if override:
                        expected = _png(colour=(5, 10, 200))
                        z.writestr(texture, expected)
                result = Converter(ConversionOptions(output_dir=str(root / 'out'), vanilla_path=str(reference),
                                                     record_learning=False)).convert(jar)
                copied = result.packs.rp / 'textures/items/minecraft_item_stick.png'
                self.assertEqual(copied.read_bytes(), expected)
                self.assertFalse([c for c in result.validation if c.severity == 'error'])
            args = build_parser().parse_args(['convert', str(jar), '--reference', str(reference)])
            self.assertEqual(args.reference, str(reference))

    def test_item_texture_on_block_uses_item_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jar = root / 'mod.jar'
            with zipfile.ZipFile(jar, 'w') as z:
                z.writestr('assets/mod/blockstates/box.json', json.dumps({'variants': {'': {'model': 'mod:block/box'}}}))
                z.writestr('assets/mod/models/block/box.json', json.dumps({
                    'parent': 'minecraft:block/cube_all', 'textures': {'all': 'minecraft:item/stick'}}))
            result = Converter(ConversionOptions(output_dir=str(root / 'out'), record_learning=False)).convert(jar)
            atlas = json.loads((result.packs.rp / 'textures/terrain_texture.json').read_text())
            self.assertEqual(atlas['texture_data']['stick']['textures'], 'textures/items/stick.png')
