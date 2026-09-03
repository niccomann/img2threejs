"""Reviewed region selectors: a merged TRELLIS mesh gets per-component regions from an
authored, GLB-hash-bound selector file -- never from automatic labelling.

Needs numpy + trimesh (the extraction side of the bridge); skipped where they are absent so
the stdlib-only CI lane stays green. The contract side (check_dense_evidence, apply) is
covered by test_apply_dense_evidence_component.py without these dependencies.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import trimesh
except ImportError:  # pragma: no cover - exercised only on the stdlib CI lane
    np = None  # type: ignore[assignment]
    trimesh = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@unittest.skipUnless(np is not None and trimesh is not None, "numpy + trimesh are required")
class ReviewedRegionsTest(unittest.TestCase):
    def setUp(self) -> None:
        from integrations.mesh3d.dense_evidence.model import sha256_file

        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "source.png"
        self.source.write_bytes(b"image")
        self.out = root / "dense-evidence"
        run = root / "run"
        (run / "normalized").mkdir(parents=True)
        (run / "review").mkdir(parents=True)
        # ONE merged mesh: a tapered tower (radius 1.0 -> 0.6 over height 0..4) standing on a
        # wide islet disc (radius 3, height 0..0.5). Single node, so no candidate regions.
        # Revolved with 41 stations so the crop sees vertex rings all along the taper (a plain
        # cone mesh has vertices only at its base ring and apex).
        stations = np.linspace(0.0, 4.0, 41)
        linestring = np.column_stack([1.0 - 0.1 * stations, stations])  # [radius, z]: 1.0 -> 0.6
        tower = trimesh.creation.revolve(linestring, sections=96)
        tower.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))  # z-up -> y-up
        islet = trimesh.creation.cylinder(radius=3.0, height=0.5, sections=96)
        islet.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
        islet.apply_translation([0.0, -0.25, 0.0])
        merged = trimesh.util.concatenate([tower, islet])
        scene = trimesh.Scene()
        scene.add_geometry(merged, node_name="merged", geom_name="merged-mesh")
        glb = run / "normalized" / "reference.glb"
        obj = run / "normalized" / "reference.obj"
        glb.write_bytes(scene.export(file_type="glb"))
        obj.write_text(scene.export(file_type="obj"), encoding="utf-8")
        self.glb_sha = sha256_file(glb)
        _write_json(run / "provider-receipt.json", {
            "providerId": "hf-zerogpu-trellis",
            "sourceImageSha256": [sha256_file(self.source)],
            "normalizedGlbSha256": self.glb_sha,
            "normalizedObjSha256": sha256_file(obj),
        })
        _write_json(run / "review" / "admission.json", {
            "status": "pass", "glbSha256": self.glb_sha, "objSha256": sha256_file(obj),
            "probe": {"scene": {"meshCount": 1, "primitiveCount": 1}, "semanticStatus": "insufficient"},
        })
        _write_json(run / "review" / "visual-review.json", {
            "status": "reviewed", "verdict": "retain-as-generative-proxy-only", "glbSha256": self.glb_sha,
        })
        self.run = run
        self.alignment = {
            "schemaVersion": 1,
            "profileVersion": "source-view-alignment-v1",
            "sourceViewTransform": np.eye(4).reshape(-1).tolist(),
            "upAxis": "+Y", "forwardAxis": "+Z", "handedness": "right-handed",
            "axisOperationAudit": ["identity; no reflection applied"],
            "chiralityStatus": "reviewed",
            "sourceViewSilhouetteIou": 0.80,
            "projectedAspectRatioError": 0.05,
            "browserCaptures": [{"path": "review/preview.png", "sha256": "f" * 64, "view": "source"}],
        }
        self.selectors = {
            "schemaVersion": 1,
            "kind": "dense-evidence-region-selectors",
            "glbSha256": self.glb_sha,
            "selectors": [
                {
                    "regionId": "reviewed:tower",
                    "semanticLabel": "lighthouse tower shaft",
                    "box": {"min": [-1.5, 0.55, -1.5], "max": [1.5, 4.5, 1.5]},
                    "profileAxis": "y",
                    "observedSurface": True,
                    "reviewNote": "front and sides visible; rear inferred, radius only",
                },
                {
                    "regionId": "reviewed:islet",
                    "semanticLabel": "islet disc",
                    "box": {"min": [-3.5, -0.6, -3.5], "max": [3.5, 0.5, 3.5]},
                    "observedSurface": True,
                },
            ],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_merged_mesh_reaches_component_scope_with_reviewed_regions(self) -> None:
        from integrations.mesh3d.dense_evidence.extract import extract_run

        evidence = extract_run(self.run, (self.source,), self.alignment, self.out, region_selectors=self.selectors)
        self.assertEqual(evidence["admission"]["semanticStatus"], "reviewed-regions")
        self.assertEqual(evidence["admission"]["maximumInfluenceScope"], "component-measurements")
        self.assertEqual(evidence["admission"]["approvedInfluenceScope"], "none")
        regions = {item["regionId"]: item for item in evidence["regions"]}
        self.assertEqual(set(regions), {"reviewed:tower", "reviewed:islet"})
        tower = regions["reviewed:tower"]
        self.assertTrue(tower["reviewed"])
        self.assertFalse(tower["candidateOnly"])
        self.assertEqual(tower["semanticLabel"], "lighthouse tower shaft")
        self.assertGreaterEqual(tower["pointCount"], 64)
        self.assertEqual(evidence["extensions"]["reviewedRegions"]["count"], 2)
        self.assertEqual(evidence["extensions"]["reviewedRegions"]["glbSha256"], self.glb_sha)
        self.assertNotIn("profile", regions["reviewed:islet"])

    def test_profile_measures_the_taper_and_respects_the_station_cap(self) -> None:
        from integrations.mesh3d.dense_evidence.extract import extract_run

        evidence = extract_run(self.run, (self.source,), self.alignment, self.out, region_selectors=self.selectors)
        tower = {item["regionId"]: item for item in evidence["regions"]}["reviewed:tower"]
        profile = tower["profile"]
        self.assertLessEqual(len(profile), 24)
        self.assertGreaterEqual(len(profile), 8)
        positions = [station[0] for station in profile]
        self.assertEqual(positions, sorted(positions))
        low_radius = profile[0][1]
        high_radius = profile[-1][1]
        # cone radius 1.0 at y=0 down to 0.6 at y=4; the crop starts at 0.55 (radius ~0.98)
        self.assertGreater(low_radius, high_radius)
        self.assertAlmostEqual(low_radius, 0.96, delta=0.06)
        self.assertAlmostEqual(high_radius, 0.62, delta=0.06)

    def test_evidence_passes_the_stdlib_contract_validator(self) -> None:
        from forge.stage1_intake.check_dense_evidence import validate_dense_evidence
        from integrations.mesh3d.dense_evidence.extract import extract_run

        evidence = extract_run(self.run, (self.source,), self.alignment, self.out, region_selectors=self.selectors)
        report = validate_dense_evidence(json.loads(json.dumps(evidence)))
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["maximumInfluenceScope"], "component-measurements")

    def test_empty_crop_and_foreign_glb_fail_closed(self) -> None:
        from integrations.mesh3d.dense_evidence.extract import extract_run
        from integrations.mesh3d.dense_evidence.model import DenseEvidenceError

        empty = json.loads(json.dumps(self.selectors))
        empty["selectors"][0]["box"] = {"min": [10.0, 10.0, 10.0], "max": [11.0, 11.0, 11.0]}
        with self.assertRaisesRegex(DenseEvidenceError, "region_selector_empty"):
            extract_run(self.run, (self.source,), self.alignment, self.out, region_selectors=empty)
        foreign = json.loads(json.dumps(self.selectors))
        foreign["glbSha256"] = "0" * 64
        with self.assertRaisesRegex(DenseEvidenceError, "evidence_hash_mismatch"):
            extract_run(self.run, (self.source,), self.alignment, self.out, region_selectors=foreign)

    def test_without_selectors_the_merged_mesh_stays_at_global_massing(self) -> None:
        from integrations.mesh3d.dense_evidence.extract import extract_run

        evidence = extract_run(self.run, (self.source,), self.alignment, self.out)
        self.assertEqual(evidence["admission"]["maximumInfluenceScope"], "global-massing")
        self.assertEqual(evidence["regions"], [])
        self.assertNotIn("reviewedRegions", evidence["extensions"])

    def test_selectors_change_the_cache_identity(self) -> None:
        from integrations.mesh3d.dense_evidence.extract import extract_run

        plain = extract_run(self.run, (self.source,), self.alignment, self.out)
        reviewed = extract_run(self.run, (self.source,), self.alignment, self.out, region_selectors=self.selectors)
        self.assertNotEqual(plain["cache"]["baseExtractionKey"], reviewed["cache"]["baseExtractionKey"])


if __name__ == "__main__":
    unittest.main()
