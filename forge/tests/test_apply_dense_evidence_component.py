"""component-measurements proposals from reviewed regions: radius, length, lathe-profile
radii and strut radii are applied (bounded, reversible), heights never move, unmapped
components are untouched, forbidden fields are refused, and transform.scale mirrors every
dimensional change so the number actually reaches the generated geometry.

Pure stdlib -- the evidence is a hand-written record shaped like the extractor's output."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest

from forge.stage1_intake.check_dense_evidence import validate_dense_evidence
from forge.stage2_spec.apply_dense_evidence import (
    COMPONENT_NUMERIC_FIELDS,
    apply_reverse_delta,
    build_proposal,
)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def lighthouse_spec() -> dict[str, object]:
    return {
        "schemaVersion": "2.1",
        "targetName": "Lighthouse",
        "qualityContract": {"denseEvidence": {"maxNumericDeltaFraction": 0.2}},
        "componentTree": [
            {
                "id": "islet-base",
                "primitive": "lathe",
                "dimensions": {"width": 10.0, "height": 2.2, "depth": 9.0},
                "transform": {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [10.0, 2.2, 9.0]},
                "geometryDescriptor": {
                    "latheProfile": {"points": [[0.5, -0.5], [0.48, -0.1], [0.42, 0.3], [0.38, 0.5]], "segments": 24}
                },
            },
            {
                "id": "lighthouse-tower",
                "primitive": "cylinder",
                "parent": "islet-base",
                "dimensions": {"width": 2.6, "height": 5.6, "depth": 2.6, "radius": 1.3},
                "transform": {"position": [0.0, 1.9, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [2.6, 5.6, 2.6]},
                "attachment": {"localStart": [0.0, 1.9, 0.0], "localEnd": [0.0, 7.5, 0.0], "baseRadius": 1.3, "endRadius": 1.0},
            },
            {
                "id": "dock-pier",
                "primitive": "box",
                "parent": "islet-base",
                "dimensions": {"width": 3.9, "height": 0.26, "depth": 1.5, "length": 3.9},
                "dominantAxis": "x",
                "transform": {"position": [-2.3, 1.0, 3.9], "rotation": [0.0, 0.28, 0.0], "scale": [3.9, 0.26, 1.5]},
            },
            {
                "id": "finial-orb",
                "primitive": "sphere",
                "parent": "lighthouse-tower",
                "dimensions": {"width": 0.5, "height": 0.5, "depth": 0.5},
                "transform": {"position": [0.0, 8.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [0.5, 0.5, 0.5]},
            },
        ],
    }


def reviewed_region(region_id: str, label: str, bounds: dict[str, list[float]], profile: list[list[float]] | None = None) -> dict[str, object]:
    record: dict[str, object] = {
        "regionId": region_id,
        "semanticLabel": label,
        "candidateOnly": False,
        "reviewed": True,
        "observedSurface": True,
        "bounds": bounds,
        "pointCount": 4096,
    }
    if profile is not None:
        record["profileAxis"] = "y"
        record["profile"] = profile
    return record


def bounds(min_xyz: list[float], max_xyz: list[float]) -> dict[str, list[float]]:
    return {"min": min_xyz, "max": max_xyz, "size": [max_xyz[i] - min_xyz[i] for i in range(3)]}


def lighthouse_evidence() -> dict[str, object]:
    selectors_sha = "5" * 64
    evidence: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "dense-evidence",
        "extractorVersion": "dense-evidence-extractor-v1",
        "createdAt": "2026-09-03T00:00:00+00:00",
        "provenance": {
            "providerId": "hf-zerogpu-trellis",
            "runPath": "/tmp/run",
            "glbPath": "/tmp/run/normalized/reference.glb",
            "glbSha256": "a" * 64,
            "objSha256": "b" * 64,
            "sourceImageSha256": ["c" * 64],
            "visualReviewStatus": "retain-as-generative-proxy-only",
            "alignmentProfileVersion": "source-view-alignment-v1",
            "alignmentSha256": "d" * 64,
        },
        "cache": {"baseExtractionKey": "e" * 64, "measurementConfigSha256": "f" * 64},
        "admission": {
            "structuralStatus": "pass",
            "semanticStatus": "reviewed-regions",
            "maximumInfluenceScope": "component-measurements",
            "approvedInfluenceScope": "none",
        },
        "alignment": {
            "schemaVersion": 1,
            "profileVersion": "source-view-alignment-v1",
            "sourceViewTransform": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            "upAxis": "+Y",
            "forwardAxis": "+Z",
            "handedness": "right-handed",
            "axisOperationAudit": ["identity"],
            "chiralityStatus": "reviewed",
            "sourceViewSilhouetteIou": 0.8,
            "projectedAspectRatioError": 0.05,
            "browserCaptures": [{"path": "review/preview.png", "sha256": "1" * 64, "view": "source"}],
        },
        "globalGeometry": {
            "bounds": bounds([-5.0, -1.0, -4.5], [5.0, 8.0, 4.5]),
            "principalAxes": [
                {"axis": [0.0, 1.0, 0.0], "variance": 3.0},
                {"axis": [1.0, 0.0, 0.0], "variance": 2.0},
                {"axis": [0.0, 0.0, 1.0], "variance": 1.0},
            ],
            "occupancyGrid": {"resolution": 24, "occupiedCells": [[0, 0, 0]], "occupiedCellCount": 1},
            "crossSections": [{"axis": "y", "position": 0.0, "profile": [[-1.0, -1.5], [1.0, 1.5]]}],
            "silhouetteViews": [{"view": "source", "path": "review/preview.png", "sha256": "1" * 64, "silhouetteIou": 0.8, "projectedAspectRatioError": 0.05}],
        },
        "regions": [
            # islet measured 10% wider than authored (10 -> 11), same depth; profile: fat bottom, narrower top
            reviewed_region("reviewed:islet", "islet rock base", bounds([-5.5, -1.1, -4.5], [5.5, 1.1, 4.5]),
                            profile=[[-1.1, 5.4], [-0.5, 5.3], [0.0, 4.9], [0.6, 4.1], [1.1, 3.4]]),
            # tower measured 15% wider and much taller (bounded to +20%); taper 1.5 -> 0.9
            reviewed_region("reviewed:tower", "lighthouse tower shaft", bounds([-1.5, 1.9, -1.5], [1.5, 9.9, 1.5]),
                            profile=[[1.9, 1.5], [4.0, 1.3], [6.0, 1.1], [7.5, 0.9]]),
            # dock measured 3.0 along x (authored length 3.9 -> bounded to -20%)
            reviewed_region("reviewed:dock", "plank dock", bounds([-3.8, 0.9, 3.1], [-0.8, 1.2, 4.7])),
        ],
        "uncertainty": {
            "sourceViewCount": 1,
            "hiddenSurfacePolicy": "non-authoritative",
            "rearConfidence": "low",
            "singleViewLimitations": ["rear is not observed"],
        },
        "extensions": {"reviewedRegions": {"selectorsSha256": selectors_sha, "glbSha256": "a" * 64, "count": 3}},
    }
    evidence["provenance"]["alignmentSha256"] = canonical_sha256(evidence["alignment"])  # type: ignore[index]
    return evidence


def component_map(evidence: dict[str, object], spec: dict[str, object]) -> dict[str, object]:
    def mapping(component_id: str, region_id: str, fields: list[str]) -> dict[str, object]:
        return {
            "componentId": component_id,
            "selectors": [{"regionId": region_id}],
            "mappingMethod": "human-reviewed-region-selector",
            "evidenceRefs": ["review/regions.png"],
            "confidence": 0.85,
            "permittedFields": fields,
            "observedSurface": True,
            "hiddenLimitations": ["rear is non-authoritative"],
        }

    return {
        "schemaVersion": 1,
        "kind": "component-evidence-map",
        "targetSpecSha256": canonical_sha256(spec),
        "evidenceSha256": canonical_sha256(evidence),
        "glbSha256": evidence["provenance"]["glbSha256"],  # type: ignore[index]
        "mappings": [
            mapping("islet-base", "reviewed:islet", ["dimensions.width", "geometryDescriptor.latheProfile.radii"]),
            mapping("lighthouse-tower", "reviewed:tower", ["dimensions.radius", "dimensions.height", "attachment.baseRadius", "attachment.endRadius"]),
            mapping("dock-pier", "reviewed:dock", ["dimensions.length"]),
        ],
        "extensions": {},
    }


def admission(spec: dict[str, object], evidence: dict[str, object], mapping: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "dense-influence-admission",
        "decision": "ALLOW",
        "approvedInfluenceScope": "component-measurements",
        "binding": {
            "glbSha256": evidence["provenance"]["glbSha256"],  # type: ignore[index]
            "evidenceSha256": canonical_sha256(evidence),
            "visualReviewSha256": "9" * 64,
            "scope": "component-measurements",
            "targetSpecSha256": canonical_sha256(spec),
            "componentMapSha256": canonical_sha256(mapping),
        },
    }


def by_component(spec: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(item["id"]): item for item in spec["componentTree"]}  # type: ignore[index]


class ContractValidationTest(unittest.TestCase):
    def test_reviewed_region_evidence_validates_alone_and_with_map(self) -> None:
        evidence = lighthouse_evidence()
        report = validate_dense_evidence(evidence)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["maximumInfluenceScope"], "component-measurements")
        spec = lighthouse_spec()
        report = validate_dense_evidence(evidence, spec, component_map(evidence, spec))
        self.assertTrue(report["passed"], report["errors"])

    def test_reviewed_regions_need_the_selectors_binding(self) -> None:
        evidence = lighthouse_evidence()
        evidence["extensions"] = {}
        report = validate_dense_evidence(evidence)
        self.assertIn("evidence_hash_mismatch", report["failureCategories"])

    def test_reviewed_status_without_regions_is_insufficient(self) -> None:
        evidence = lighthouse_evidence()
        evidence["regions"] = []
        evidence["extensions"] = {}
        report = validate_dense_evidence(evidence)
        self.assertIn("semantic_boundary_insufficient", report["failureCategories"])

    def test_profile_cap_and_point_floor_are_enforced(self) -> None:
        evidence = lighthouse_evidence()
        evidence["regions"][0]["profile"] = [[0.0, 1.0]] * 25  # type: ignore[index]
        evidence["regions"][2]["pointCount"] = 12  # type: ignore[index]
        report = validate_dense_evidence(evidence)
        self.assertIn("measurement_limit_exceeded", report["failureCategories"])
        self.assertIn("region_selector_empty", report["failureCategories"])

    def test_profile_fields_need_a_profiled_region(self) -> None:
        evidence = lighthouse_evidence()
        spec = lighthouse_spec()
        mapping = component_map(evidence, spec)
        mapping["mappings"][2]["permittedFields"] = ["attachment.baseRadius"]  # type: ignore[index]
        report = validate_dense_evidence(evidence, spec, mapping)
        self.assertIn("component_mapping_invalid", report["failureCategories"])
        self.assertTrue(any("profile" in error for error in report["errors"]), report["errors"])


class ComponentProposalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = lighthouse_spec()
        self.evidence = lighthouse_evidence()
        self.mapping = component_map(self.evidence, self.spec)
        self.before = copy.deepcopy(self.spec)
        self.proposal, self.delta, self.fit_plan = build_proposal(
            self.spec, self.evidence, admission(self.spec, self.evidence, self.mapping), self.mapping
        )
        self.changed = by_component(self.proposal)
        self.original = by_component(self.spec)

    def test_inputs_untouched_and_delta_reversible(self) -> None:
        self.assertEqual(self.spec, self.before)
        self.assertEqual(apply_reverse_delta(self.proposal, self.delta), self.spec)
        self.assertTrue(all(item["scope"] == "component-measurements" for item in self.delta["changes"]))
        self.assertTrue(all(item["field"] in COMPONENT_NUMERIC_FIELDS for item in self.delta["changes"]))

    def test_radius_and_height_applied_with_scale_mirror(self) -> None:
        tower = self.changed["lighthouse-tower"]
        dims = tower["dimensions"]
        self.assertAlmostEqual(dims["radius"], 1.3 * (1.5 / 1.3), places=9)  # measured 3.0/2 = 1.5, +15% within bound
        self.assertAlmostEqual(dims["height"], 5.6 * 1.2, places=9)  # measured 8.0 -> clamped to +20%
        self.assertAlmostEqual(tower["transform"]["scale"][0], 2.6 * (1.5 / 1.3), places=9)
        self.assertAlmostEqual(tower["transform"]["scale"][2], 2.6 * (1.5 / 1.3), places=9)
        self.assertAlmostEqual(tower["transform"]["scale"][1], 5.6 * 1.2, places=9)
        self.assertEqual(dims["width"], 2.6)  # not permitted -> untouched
        derived = [c for c in self.delta["changes"] if c.get("derivedFrom") == "dimensions.radius"]
        self.assertEqual({c["field"] for c in derived}, {"transform.scale.0", "transform.scale.2"})

    def test_strut_radii_come_from_profile_ends(self) -> None:
        attachment = self.changed["lighthouse-tower"]["attachment"]
        self.assertAlmostEqual(attachment["baseRadius"], 1.3 * (1.5 / 1.3), places=9)  # low station 1.5
        self.assertAlmostEqual(attachment["endRadius"], 1.0 * 0.9, places=9)  # high station 0.9
        self.assertEqual(attachment["localStart"], [0.0, 1.9, 0.0])
        self.assertEqual(attachment["localEnd"], [0.0, 7.5, 0.0])

    def test_length_uses_dominant_axis_and_is_bounded(self) -> None:
        dock = self.changed["dock-pier"]
        self.assertAlmostEqual(dock["dimensions"]["length"], 3.9 * 0.8, places=9)  # measured 3.0 -> -23% clamped to -20%
        self.assertAlmostEqual(dock["transform"]["scale"][0], 3.9 * 0.8, places=9)
        self.assertEqual(dock["dimensions"]["width"], 3.9)

    def test_lathe_radii_resampled_heights_untouched(self) -> None:
        islet = self.changed["islet-base"]
        points = islet["geometryDescriptor"]["latheProfile"]["points"]
        original = self.original["islet-base"]["geometryDescriptor"]["latheProfile"]["points"]
        self.assertEqual([p[1] for p in points], [p[1] for p in original])
        self.assertEqual(len(points), len(original))
        # width was permitted too: measured 11 vs 10 -> +10%, mirrored onto scale.x only
        self.assertAlmostEqual(islet["dimensions"]["width"], 11.0, places=9)
        self.assertAlmostEqual(islet["transform"]["scale"][0], 11.0, places=9)
        self.assertEqual(islet["transform"]["scale"][2], 9.0)
        # lateral scale for the radius conversion is the mean of the ORIGINAL x/z scale? No: the
        # proposal applies fields in permitted order, so width (and scale.x) moved first and the
        # profile sees the updated lateral scale (11 + 9) / 2 = 10. Measured world radii at the
        # authored stations -0.5..0.5 map onto region stations -1.1..1.1:
        #   station -0.5 -> 5.4/10 = 0.54 vs 0.50  (+8%)
        #   station  0.5 -> 3.4/10 = 0.34 vs 0.38  (-10.5%)
        self.assertAlmostEqual(points[0][0], 0.54, places=9)
        self.assertAlmostEqual(points[-1][0], 0.34, places=9)
        for new, old in zip(points, original):
            ratio = new[0] / old[0]
            self.assertGreaterEqual(ratio, 0.8 - 1e-9)
            self.assertLessEqual(ratio, 1.2 + 1e-9)
        stations = [c for c in self.delta["changes"] if c["field"] == "geometryDescriptor.latheProfile.radii"]
        self.assertEqual(len(stations), 4)
        # path = componentTree / i / geometryDescriptor / latheProfile / points / station / 0
        self.assertTrue(all(len(c["path"]) == 7 and c["path"][-1] == 0 for c in stations), stations)

    def test_unmapped_component_is_untouched(self) -> None:
        self.assertEqual(self.changed["finial-orb"], self.original["finial-orb"])

    def test_forbidden_field_is_rejected(self) -> None:
        mapping = component_map(self.evidence, self.spec)
        mapping["mappings"][0]["permittedFields"] = ["transform.scale.0"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "influence_scope_exceeded"):
            build_proposal(self.spec, self.evidence, admission(self.spec, self.evidence, mapping), mapping)
        mapping["mappings"][0]["permittedFields"] = ["geometryDescriptor.latheProfile.points"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "influence_scope_exceeded"):
            build_proposal(self.spec, self.evidence, admission(self.spec, self.evidence, mapping), mapping)


if __name__ == "__main__":
    unittest.main()
