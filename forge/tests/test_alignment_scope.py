"""Influence-scope ceiling: reviewed regions unlock component-measurements only together
with reviewed chirality and IoU >= 0.75; any one missing caps the run at global-massing."""

from __future__ import annotations

import unittest

from integrations.mesh3d.dense_evidence.alignment import validate_alignment
from integrations.mesh3d.dense_evidence.model import (
    COMPONENT_CAPABLE_SEMANTIC_STATUSES,
    DenseEvidenceError,
    InfluenceScope,
)


def alignment(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "profileVersion": "source-view-alignment-v1",
        "sourceViewTransform": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "upAxis": "+Y",
        "forwardAxis": "+Z",
        "handedness": "right-handed",
        "axisOperationAudit": ["identity"],
        "chiralityStatus": "reviewed",
        "sourceViewSilhouetteIou": 0.80,
        "projectedAspectRatioError": 0.05,
        "browserCaptures": [{"path": "review/preview.png", "sha256": "f" * 64, "view": "source"}],
    }
    value.update(overrides)
    return value


class AlignmentScopeTest(unittest.TestCase):
    def test_reviewed_regions_reach_component_scope(self) -> None:
        self.assertEqual(COMPONENT_CAPABLE_SEMANTIC_STATUSES, {"sufficient", "reviewed-regions"})
        result = validate_alignment(alignment(), "reviewed-regions")
        self.assertEqual(result.maximum_scope, InfluenceScope.COMPONENT_MEASUREMENTS)

    def test_multipart_sufficient_still_reaches_component_scope(self) -> None:
        result = validate_alignment(alignment(), "sufficient")
        self.assertEqual(result.maximum_scope, InfluenceScope.COMPONENT_MEASUREMENTS)

    def test_insufficient_semantics_cap_at_global(self) -> None:
        result = validate_alignment(alignment(), "insufficient")
        self.assertEqual(result.maximum_scope, InfluenceScope.GLOBAL_MASSING)

    def test_ambiguous_chirality_caps_reviewed_regions_at_global(self) -> None:
        result = validate_alignment(alignment(chiralityStatus="ambiguous"), "reviewed-regions")
        self.assertEqual(result.maximum_scope, InfluenceScope.GLOBAL_MASSING)

    def test_iou_below_component_threshold_caps_at_global(self) -> None:
        result = validate_alignment(alignment(sourceViewSilhouetteIou=0.74), "reviewed-regions")
        self.assertEqual(result.maximum_scope, InfluenceScope.GLOBAL_MASSING)

    def test_iou_below_global_threshold_denies(self) -> None:
        with self.assertRaisesRegex(DenseEvidenceError, "alignment_failed"):
            validate_alignment(alignment(sourceViewSilhouetteIou=0.64), "reviewed-regions")


if __name__ == "__main__":
    unittest.main()
