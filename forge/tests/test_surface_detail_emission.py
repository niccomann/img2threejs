#!/usr/bin/env python3
"""component.surfaceDetail reaches the emitted factory.

surfaceDetail was validated and gated the surface-pass, but `grep surfaceDetail
generate_threejs_factory.py` returned nothing: a component could declare micro roughness, a
bump amplitude and a "stepped strata bands" pattern and render exactly like its neighbour
sharing the same material. Now a component with a meaningful surfaceDetail gets its own
material instance, built from the host material merged with the override:

  microRoughness -> roughness.variation      macroRoughness -> roughness.base
  bumpAmplitude  -> normal.strength/amplitude preset | pattern prose -> surfaceFrequencyBands

Pure stdlib; no showcase root needed.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def import_forge_modules():
    module_names = ("generate_threejs_factory", "validate_sculpt_spec")
    original_modules = {name: sys.modules.pop(name, None) for name in module_names}
    original_path = sys.path[:]
    sys.path[:0] = [str(ROOT / "stage2_spec"), str(ROOT / "stage3_build")]
    try:
        import generate_threejs_factory as generator
        import validate_sculpt_spec as validator
    finally:
        sys.path[:] = original_path
        for name, module in original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return generator, validator


generator, validator = import_forge_modules()


SPEC = {
    "targetName": "Surface Detail Tower",
    "schemaVersion": "2.1",
    "suitability": "pass",
    "coordinateFrame": {},
    "silhouette": {},
    "proceduralStrategy": [],
    "materials": [
        {
            "id": "stone",
            "roughness": {"base": 0.8, "variation": 0.1},
            "normal": {"strength": 0.3},
            "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3}],
        }
    ],
    "componentTree": [
        {
            "id": "tower",
            "name": "Tower",
            "level": "macro",
            "role": "body",
            "primitive": "cylinder",
            "parent": None,
            "material": "stone",
            "transform": {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 3.0, 1.0]},
            "surfaceDetail": {
                "microRoughness": 0.35,
                "bumpAmplitude": 0.5,
                "displacementPattern": "stepped strata bands",
                "normalPattern": "horizontal rock strata ledges",
            },
        },
        {
            "id": "plinth",
            "name": "Plinth",
            "level": "macro",
            "role": "base",
            "primitive": "box",
            "parent": None,
            "material": "stone",
            "transform": {"position": [0.0, -1.5, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [2.0, 0.2, 2.0]},
            "surfaceDetail": {"macroRoughness": 0.0, "microRoughness": 0.0, "bumpAmplitude": 0.0, "displacementPattern": "none"},
        },
    ],
}


class SurfaceDetailMergeTest(unittest.TestCase):
    def test_numeric_fields_map_onto_material_layers(self) -> None:
        merged = generator.surface_detail_material(SPEC["materials"][0], SPEC["componentTree"][0]["surfaceDetail"])
        assert merged is not None
        self.assertEqual(merged["roughness"]["variation"], 0.35)
        self.assertEqual(merged["roughness"]["base"], 0.8)  # macroRoughness absent -> host base kept
        self.assertEqual(merged["normal"]["strength"], 0.5)
        self.assertEqual(merged["normal"]["amplitude"], 0.5)
        self.assertEqual(merged["surfaceDetailOverride"]["preset"], "stone")
        self.assertEqual([b["id"] for b in merged["surfaceFrequencyBands"]], ["macro", "meso", "micro"])

    def test_host_material_is_not_mutated(self) -> None:
        host = copy.deepcopy(SPEC["materials"][0])
        generator.surface_detail_material(host, SPEC["componentTree"][0]["surfaceDetail"])
        self.assertEqual(host, SPEC["materials"][0])

    def test_empty_detail_returns_none(self) -> None:
        self.assertIsNone(generator.surface_detail_material(SPEC["materials"][0], SPEC["componentTree"][1]["surfaceDetail"]))
        self.assertIsNone(generator.surface_detail_material(SPEC["materials"][0], None))
        self.assertIsNone(generator.surface_detail_material(None, {"microRoughness": 0.5}))

    def test_pattern_resolution(self) -> None:
        resolve = generator.resolve_surface_pattern
        self.assertEqual(resolve({"displacementPattern": "plank gaps"}), "plank")
        self.assertEqual(resolve({"normalPattern": "staggered slate tile rows"}), "shingle")
        self.assertEqual(resolve({"normalPattern": "troweled plaster grain"}), "plaster")
        self.assertEqual(resolve({"displacementPattern": "rope coil strands"}), "rope")
        self.assertEqual(resolve({"preset": "rope", "displacementPattern": "plank gaps"}), "rope")
        self.assertIsNone(resolve({"displacementPattern": "none"}))
        self.assertIsNone(resolve({"normalPattern": "paint micro-orange-peel"}))
        self.assertIsNone(resolve(None))

    def test_preset_table_snapshot(self) -> None:
        table = generator.SURFACE_DETAIL_PATTERN_BANDS
        self.assertEqual(tuple(table.keys()), tuple(validator.SURFACE_DETAIL_PRESETS))
        for name, bands in table.items():
            self.assertEqual([b["id"] for b in bands], ["macro", "meso", "micro"], name)
            frequencies = [b["frequency"] for b in bands]
            self.assertEqual(frequencies, sorted(frequencies), f"{name}: bands must go macro -> micro")
            for band in bands:
                self.assertGreater(band["frequency"], 0)
                self.assertGreater(band["amplitude"], 0)
                self.assertLessEqual(band["amplitude"], 0.5)


class SurfaceDetailEmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        errors, _ = validator.validate_spec(SPEC)
        if errors:
            raise RuntimeError(f"FAIL CLOSED: fixture did not validate: {errors}")
        cls.generated = generator.generate(SPEC, "surface-pass")

    def test_detailed_component_gets_its_own_material_instance(self) -> None:
        self.assertIn('createSculptMaterial("stone@tower"', self.generated)
        self.assertIn("/* surfaceDetail override: preset=stone */", self.generated)
        self.assertIn('"variation": 0.35', self.generated)
        self.assertIn('"strength": 0.5', self.generated)
        self.assertIn('"role": "block strata and ledges"', self.generated)

    def test_plain_component_keeps_sharing_material_map(self) -> None:
        self.assertNotIn('createSculptMaterial("stone@plinth"', self.generated)
        self.assertIn('materialMap["stone"]', self.generated)


class SurfaceDetailValidationTest(unittest.TestCase):
    def test_unknown_preset_rejected(self) -> None:
        spec = copy.deepcopy(SPEC)
        spec["componentTree"][0]["surfaceDetail"]["preset"] = "velvet"
        errors, _ = validator.validate_spec(spec)
        self.assertTrue(any("surfaceDetail.preset must be one of" in e for e in errors), errors)

    def test_out_of_range_amplitude_rejected(self) -> None:
        spec = copy.deepcopy(SPEC)
        spec["componentTree"][0]["surfaceDetail"]["bumpAmplitude"] = 1.5
        errors, _ = validator.validate_spec(spec)
        self.assertTrue(any("bumpAmplitude must be within 0..1" in e for e in errors), errors)

    def test_pattern_must_be_string(self) -> None:
        spec = copy.deepcopy(SPEC)
        spec["componentTree"][0]["surfaceDetail"]["displacementPattern"] = 3
        errors, _ = validator.validate_spec(spec)
        self.assertTrue(any("displacementPattern must be a string" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
