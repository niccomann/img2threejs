#!/usr/bin/env python3
"""A material's `emissive` authored as a layer object {color, intensity} must reach the
emitted factory.

The material template (`new_sculpt_spec.py`) and every showcase lantern/window author
`"emissive": {"color": "#...", "intensity": n}`; codegen only accepted a colour string and
turned the object into black with intensity 1 -- the Lighthouse Cove lantern room, authored
with {color: '#FFB347', intensity: 1.6}, rendered as unlit glass through four build passes.

Pure stdlib: checks the emitted TypeScript, no showcase root needed."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def import_generate():
    module_names = ("generate_threejs_factory", "validate_sculpt_spec")
    original_modules = {name: sys.modules.pop(name, None) for name in module_names}
    original_path = sys.path[:]
    sys.path[:0] = [str(ROOT / "stage2_spec"), str(ROOT / "stage3_build")]
    try:
        from generate_threejs_factory import generate
    finally:
        sys.path[:] = original_path
        for name, module in original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return generate


generate = import_generate()

SPEC = {
    "targetName": "Glow Lamp",
    "schemaVersion": "2.1",
    "suitability": "pass",
    "coordinateFrame": {},
    "silhouette": {},
    "proceduralStrategy": [],
    "materials": [
        {"id": "glass", "emissive": {"color": "#FFB347", "intensity": 1.6}},
        {"id": "paint", "emissive": "#112233", "emissiveIntensity": 0.4},
    ],
    "componentTree": [
        {"id": "lamp", "name": "Lamp", "level": "macro", "role": "body", "primitive": "sphere", "parent": None, "material": "glass",
         "transform": {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}},
        {"id": "shade", "name": "Shade", "level": "macro", "role": "body", "primitive": "box", "parent": None, "material": "paint",
         "transform": {"position": [0.0, 1.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}},
    ],
}


class EmissiveLayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = generate(SPEC, "blockout")

    def test_runtime_reads_object_and_string_emissive(self) -> None:
        self.assertIn("function readLayerColor(value: unknown, fallback: string): string {", self.generated)
        self.assertIn("emissive: new THREE.Color(readLayerColor(spec.emissive, '#000000')),", self.generated)
        self.assertIn("emissiveIntensity: Math.max(0, readLayerNumber(spec.emissiveIntensity ?? spec.emissive, ['base', 'intensity'], 1.0)),", self.generated)

    def test_material_specs_keep_both_authoring_forms(self) -> None:
        self.assertIn('"emissive": {"color": "#FFB347", "intensity": 1.6}', self.generated)
        self.assertIn('"emissive": "#112233"', self.generated)
        self.assertIn('"emissiveIntensity": 0.4', self.generated)


if __name__ == "__main__":
    unittest.main(verbosity=2)
