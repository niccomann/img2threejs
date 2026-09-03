#!/usr/bin/env python3
"""repetitionSystems[].placement.mode: linear and grid are real, unknown modes fail.

Before this change the generator read `placement.mode`, printed it in a comment, and then ran
an instance loop that was always radial -- a "linear" row of dock planks silently came out as
a ring. Now:

* `radial` (default) is unchanged;
* `linear` places instances at start + axis * spacing * i (optionally centred on start);
* `grid` places counts[0] x counts[1] instances along two axes and derives `count`;
* any other mode is a validation error and a codegen ValueError.

Two layers of test: pure-stdlib checks of validation + emitted TypeScript, and a REAL-RUN
check (tsc + node, skipped without IMG2THREEJS_SHOWCASE_ROOT) that reads back the executed
instance matrices.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if __package__:
    from .showcase_test_support import showcase_root
else:
    from showcase_test_support import showcase_root

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
generate = generator.generate
validate_spec = validator.validate_spec


PLACEMENT_SPEC = {
    "targetName": "Placement Modes Plate",
    "schemaVersion": "2.1",
    "suitability": "pass",
    "coordinateFrame": {},
    "silhouette": {},
    "proceduralStrategy": [],
    "materials": [{"id": "clay"}],
    "componentTree": [
        {
            "id": "plate",
            "name": "Plate",
            "level": "macro",
            "role": "body",
            "primitive": "box",
            "parent": None,
            "material": "clay",
            "transform": {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [4.0, 1.0, 0.3]},
        },
    ],
    "repetitionSystems": [
        {
            "id": "planks",
            "parent": "plate",
            "level": "macro",
            "count": 6,
            "primitive": "box",
            "material": "clay",
            "instanceScale": [0.25, 0.05, 1.0],
            "placement": {"mode": "linear", "axis": [1.0, 0.0, 0.0], "spacing": 0.3, "start": [0.0, 0.5, 0.0], "centered": True},
        },
        {
            "id": "bolts",
            "parent": "plate",
            "level": "macro",
            "primitive": "sphere",
            "material": "clay",
            "instanceScale": [0.05, 0.05, 0.05],
            "placement": {
                "mode": "grid",
                "axes": [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
                "counts": [2, 3],
                "spacing": [0.4, 0.5],
                "start": [1.0, 0.0, 0.0],
            },
        },
        {
            "id": "rivets",
            "parent": "plate",
            "level": "macro",
            "count": 8,
            "primitive": "sphere",
            "material": "clay",
            "instanceScale": [0.05, 0.05, 0.05],
            "placement": {"mode": "radial", "axis": [0.0, 1.0, 0.0], "radius": 1.0, "startAngleDeg": 0.0},
        },
    ],
}


def with_placement(system_id: str, **placement) -> dict:
    spec = copy.deepcopy(PLACEMENT_SPEC)
    for system in spec["repetitionSystems"]:
        if system["id"] == system_id:
            system["placement"] = placement
    return spec


class PlacementValidationTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        errors, _warnings = validate_spec(PLACEMENT_SPEC)
        self.assertEqual(errors, [])

    def test_unknown_mode_is_an_error(self) -> None:
        errors, _ = validate_spec(with_placement("planks", mode="spiral", spacing=0.3))
        self.assertTrue(any("placement.mode must be one of" in e for e in errors), errors)

    def test_linear_requires_positive_spacing(self) -> None:
        errors, _ = validate_spec(with_placement("planks", mode="linear", axis=[1, 0, 0]))
        self.assertTrue(any("positive numeric spacing" in e for e in errors), errors)
        errors, _ = validate_spec(with_placement("planks", mode="linear", spacing=0))
        self.assertTrue(any("positive numeric spacing" in e for e in errors), errors)

    def test_grid_requires_axes_counts_spacing(self) -> None:
        errors, _ = validate_spec(with_placement("bolts", mode="grid"))
        joined = "\n".join(errors)
        self.assertIn("axes: two 3-vectors", joined)
        self.assertIn("counts: two positive integers", joined)
        self.assertIn("spacing: two positive numbers", joined)

    def test_grid_count_must_match_counts_product(self) -> None:
        spec = copy.deepcopy(PLACEMENT_SPEC)
        spec["repetitionSystems"][1]["count"] = 5
        errors, _ = validate_spec(spec)
        self.assertTrue(any("does not equal counts product 6" in e for e in errors), errors)

    def test_prose_placement_is_left_alone(self) -> None:
        spec = copy.deepcopy(PLACEMENT_SPEC)
        spec["repetitionSystems"][0]["placement"] = "three per front paw at x offsets -0.040, 0.0, +0.040"
        errors, _ = validate_spec(spec)
        self.assertEqual(errors, [])

    def test_validator_mirrors_generator_modes(self) -> None:
        self.assertEqual(tuple(validator.REPETITION_PLACEMENT_MODES), tuple(generator.REPETITION_PLACEMENT_MODES))


class PlacementEmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = generate(PLACEMENT_SPEC, "blockout")

    def test_linear_loop_is_emitted(self) -> None:
        self.assertIn("(InstancedMesh, linear, count=6, level=macro)", self.generated)
        self.assertIn("normalize().multiplyScalar(0.3)", self.generated)
        self.assertIn("if (true) origin.addScaledVector(step, -(6 - 1) / 2);", self.generated)
        self.assertIn("_p.copy(origin).addScaledVector(step, i);", self.generated)

    def test_grid_loop_is_emitted_with_derived_count(self) -> None:
        self.assertIn("(InstancedMesh, grid, count=6, level=macro)", self.generated)
        self.assertIn("const a = i % 2;", self.generated)
        self.assertIn("const b = Math.floor(i / 2);", self.generated)
        self.assertIn("new THREE.InstancedMesh(geo, mat, 6)", self.generated)

    def test_radial_loop_unchanged(self) -> None:
        self.assertIn("(InstancedMesh, radial, count=8, level=macro)", self.generated)
        self.assertIn("_q.setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir);", self.generated)

    def test_unknown_mode_fails_closed_in_codegen(self) -> None:
        with self.assertRaises(ValueError):
            generate(with_placement("planks", mode="spiral", spacing=0.3), "blockout")


_EVAL_SCRIPT = """
import * as THREE from 'three';
import { createPlacementModesPlateModel } from './build/placement-modes.js';

const model = createPlacementModesPlateModel();
const plate = model.userData.sculptRuntime.nodes['plate'];
model.updateMatrixWorld(true);

function positions(name) {
  const cluster = plate.children.find((child) => child.name === name);
  if (!cluster) throw new Error(`cluster ${name} not found`);
  const local = new THREE.Matrix4();
  const combined = new THREE.Matrix4();
  const pos = new THREE.Vector3();
  const quat = new THREE.Quaternion();
  const scl = new THREE.Vector3();
  const out = [];
  for (let i = 0; i < cluster.count; i += 1) {
    cluster.getMatrixAt(i, local);
    combined.multiplyMatrices(cluster.matrixWorld, local);
    combined.decompose(pos, quat, scl);
    out.push([pos.x, pos.y, pos.z].map((v) => Math.round(v * 1000) / 1000));
  }
  return out;
}

console.log(JSON.stringify({ planks: positions('planks'), bolts: positions('bolts') }));
"""


class PlacementRealRunTest(unittest.TestCase):
    result: dict

    @classmethod
    def setUpClass(cls) -> None:
        root = showcase_root()
        generated = generate(PLACEMENT_SPEC, "blockout")
        cls._tempdir_ctx = tempfile.TemporaryDirectory(dir=root)
        work_dir = Path(cls._tempdir_ctx.name)
        source = work_dir / "placement-modes.ts"
        source.write_text(generated, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "npx", "tsc", "--target", "ES2020", "--module", "NodeNext", "--moduleResolution", "NodeNext",
                "--strict", "--skipLibCheck", "--noUnusedLocals", "--noUnusedParameters",
                "--outDir", str(work_dir / "build"), str(source),
            ],
            cwd=root, capture_output=True, text=True,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(f"FAIL CLOSED: tsc did not compile the emitted module: {compile_result.stderr}")
        runtime = subprocess.run(
            ["node", "--input-type=module", "--eval", _EVAL_SCRIPT],
            cwd=work_dir, capture_output=True, text=True,
        )
        if runtime.returncode != 0:
            raise RuntimeError(f"FAIL CLOSED: node execution failed: {runtime.stderr}")
        cls.result = json.loads(runtime.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tempdir_ctx.cleanup()

    def test_linear_row_is_centred_on_start_with_authored_spacing(self) -> None:
        xs = sorted(p[0] for p in self.result["planks"])
        self.assertEqual(xs, [-0.75, -0.45, -0.15, 0.15, 0.45, 0.75])
        for p in self.result["planks"]:
            self.assertEqual(p[1], 0.5)
            self.assertEqual(p[2], 0.0)

    def test_grid_covers_counts_along_both_axes(self) -> None:
        cells = sorted((p[0], p[2]) for p in self.result["bolts"])
        expected = sorted((1.0 + 0.4 * a, 0.5 * b) for a in range(2) for b in range(3))
        self.assertEqual(cells, [(round(x, 3), round(z, 3)) for x, z in expected])
        for p in self.result["bolts"]:
            self.assertEqual(p[1], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
