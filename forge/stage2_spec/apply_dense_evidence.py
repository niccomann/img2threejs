#!/usr/bin/env python3
"""Create reversible, bounded ObjectSculptSpec proposals from admitted evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge.stage1_intake.check_dense_evidence import validate_dense_evidence


# The generator sizes a component from `transform.scale` when it is present and only falls
# back to `dimensions` otherwise (generate_threejs_factory.py: resolve_component_scale /
# scale_vector). A proposal that moved `dimensions` alone would therefore be cosmetic on every
# spec that carries both -- the measured number would sit in the JSON and never reach the
# geometry. Every dimensional change below is mirrored onto the matching `transform.scale`
# axis, recorded as its own derived change so the reverse delta restores both.
DERIVED_SCALE_FIELDS = ("transform.scale.0", "transform.scale.1", "transform.scale.2")
GLOBAL_NUMERIC_FIELDS = frozenset(
    {
        "dimensions.width",
        "dimensions.height",
        "dimensions.depth",
        "dimensions.radius",
        "dimensions.length",
        "transform.position.0",
        "transform.position.1",
        "transform.position.2",
        *DERIVED_SCALE_FIELDS,
    }
)
# Fields a component map may permit (mirror of check_dense_evidence.COMPONENT_FIELDS) plus the
# derived scale mirrors. The three profile-derived fields need a reviewed region carrying a
# radius-vs-station `profile`; heights/stations are never moved, only radii.
COMPONENT_NUMERIC_FIELDS = frozenset(
    {
        "dimensions.width",
        "dimensions.height",
        "dimensions.depth",
        "dimensions.radius",
        "dimensions.length",
        "geometryDescriptor.latheProfile.radii",
        "attachment.baseRadius",
        "attachment.endRadius",
        *DERIVED_SCALE_FIELDS,
    }
)
COMPONENT_PERMITTED_FIELDS = COMPONENT_NUMERIC_FIELDS - frozenset(DERIVED_SCALE_FIELDS)
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def bounded_ratio(measured: float, authored: float, maximum_delta: float) -> float:
    if not math.isfinite(measured) or not math.isfinite(authored) or authored <= 0:
        raise ValueError("invalid_geometry_measurement: sizes must be finite and positive")
    raw = measured / authored
    return min(1.0 + maximum_delta, max(1.0 - maximum_delta, raw))


def _components(spec: dict[str, object]) -> list[tuple[dict[str, Any], list[object], tuple[float, float, float]]]:
    result: list[tuple[dict[str, Any], list[object], tuple[float, float, float]]] = []

    def visit(items: object, path: list[object], parent_position: tuple[float, float, float]) -> None:
        if not isinstance(items, list):
            return
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            transform = item.get("transform")
            position = transform.get("position") if isinstance(transform, dict) else None
            local = (
                tuple(float(value) for value in position)
                if isinstance(position, list)
                and len(position) == 3
                and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in position)
                else (0.0, 0.0, 0.0)
            )
            world = tuple(parent_position[axis] + local[axis] for axis in range(3))
            item_path = [*path, index]
            result.append((item, item_path, world))
            visit(item.get("children"), [*item_path, "children"], world)

    visit(spec.get("componentTree"), ["componentTree"], (0.0, 0.0, 0.0))
    return result


def _authored_size(spec: dict[str, object]) -> tuple[float, float, float]:
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    seen = False
    for component, _path, world in _components(spec):
        dimensions = component.get("dimensions")
        if not isinstance(dimensions, dict):
            continue
        values = [dimensions.get("width"), dimensions.get("height"), dimensions.get("depth")]
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
            for value in values
        ):
            continue
        seen = True
        for axis, value in enumerate(values):
            half = float(value) / 2.0
            minimum[axis] = min(minimum[axis], world[axis] - half)
            maximum[axis] = max(maximum[axis], world[axis] + half)
    if not seen:
        raise ValueError("invalid_geometry_measurement: no component xyz dimensions")
    return tuple(maximum[axis] - minimum[axis] for axis in range(3))


def _max_delta(spec: dict[str, object]) -> float:
    quality = spec.get("qualityContract")
    dense = quality.get("denseEvidence") if isinstance(quality, dict) else None
    value = dense.get("maxNumericDeltaFraction") if isinstance(dense, dict) else 0.20
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 0.5
    ):
        raise ValueError("invalid_dense_evidence_policy: maxNumericDeltaFraction must be in (0, 0.5]")
    return float(value)


def _set_change(
    component: dict[str, Any],
    path: list[object],
    field: str,
    new_value: float,
    changes: list[dict[str, object]],
    *,
    scope: str,
    measured: float,
    confidence: float,
    source_region: str,
    field_label: str | None = None,
    derived_from: str | None = None,
) -> None:
    tokens: list[object] = field.split(".")
    resolved_tokens: list[object] = []
    target: Any = component
    for token in tokens[:-1]:
        if isinstance(target, dict):
            target = target.get(token)
            resolved_tokens.append(token)
        elif isinstance(target, list):
            index = int(token)
            target = target[index]
            resolved_tokens.append(index)
        else:
            return
    final = tokens[-1]
    old: object
    if isinstance(target, dict):
        old = target.get(final)
        if not isinstance(old, (int, float)) or isinstance(old, bool):
            return
        target[final] = new_value
    elif isinstance(target, list):
        index = int(final)
        if index >= len(target) or not isinstance(target[index], (int, float)) or isinstance(target[index], bool):
            return
        old = target[index]
        target[index] = new_value
        resolved_final: object = index
    else:
        return
    if isinstance(target, dict):
        resolved_final = final
    if math.isclose(float(old), new_value, rel_tol=1e-12, abs_tol=1e-12):
        if isinstance(target, dict):
            target[final] = old
        else:
            target[int(final)] = old
        return
    change: dict[str, object] = {
        "path": [*path, *resolved_tokens, resolved_final],
        "componentId": component.get("id"),
        "field": field_label or field,
        "old": float(old),
        "new": float(new_value),
        "measured": float(measured),
        "confidence": float(confidence),
        "sourceRegion": source_region,
        "scope": scope,
        "reason": "bounded dense-evidence measurement proposal",
    }
    if derived_from is not None:
        change["derivedFrom"] = derived_from
        change["reason"] = "transform.scale mirrors the dimensional change (generator reads scale first)"
    changes.append(change)


def _sync_transform_scale(
    component: dict[str, Any],
    path: list[object],
    axes: tuple[int, ...],
    factor: float,
    changes: list[dict[str, object]],
    *,
    scope: str,
    measured: float,
    confidence: float,
    source_region: str,
    derived_from: str,
) -> None:
    transform = component.get("transform")
    scale = transform.get("scale") if isinstance(transform, dict) else None
    if not isinstance(scale, list) or len(scale) != 3:
        return
    for axis in axes:
        value = scale[axis]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _set_change(
                component, path, f"transform.scale.{axis}", float(value) * factor, changes,
                scope=scope, measured=measured, confidence=confidence, source_region=source_region,
                derived_from=derived_from,
            )


def _validate_binding(
    spec: dict[str, object],
    evidence: dict[str, object],
    admission: dict[str, object],
    component_map: dict[str, object] | None,
) -> str:
    if admission.get("decision") != "ALLOW" or not isinstance(admission.get("binding"), dict):
        raise ValueError("influence_not_approved: ALLOW admission is required")
    binding = admission["binding"]
    scope = admission.get("approvedInfluenceScope")
    provenance = evidence.get("provenance")
    if scope not in {"global-massing", "component-measurements"}:
        raise ValueError("influence_scope_exceeded: unsupported approval scope")
    expected = {
        "targetSpecSha256": _canonical_sha256(spec),
        "evidenceSha256": _canonical_sha256(evidence),
        "glbSha256": provenance.get("glbSha256") if isinstance(provenance, dict) else None,
        "scope": scope,
    }
    if component_map is not None:
        expected["componentMapSha256"] = _canonical_sha256(component_map)
    if any(binding.get(field) != value for field, value in expected.items()):
        raise ValueError("admission_hash_mismatch: approval tuple no longer matches inputs")
    return str(scope)


def _global_proposal(
    proposal: dict[str, object], evidence: dict[str, object], changes: list[dict[str, object]]
) -> tuple[float, float, float]:
    geometry = evidence.get("globalGeometry")
    bounds = geometry.get("bounds") if isinstance(geometry, dict) else None
    measured = bounds.get("size") if isinstance(bounds, dict) else None
    if not isinstance(measured, list) or len(measured) != 3:
        raise ValueError("invalid_geometry_measurement: evidence bounds size is missing")
    authored = _authored_size(proposal)
    maximum_delta = _max_delta(proposal)
    measured_values = tuple(float(value) for value in measured)
    if not all(math.isfinite(value) and value > 0 for value in measured_values):
        raise ValueError("invalid_geometry_measurement: evidence bounds must be finite and positive")
    authored_anchor = math.prod(authored) ** (1.0 / 3.0)
    measured_anchor = math.prod(measured_values) ** (1.0 / 3.0)
    scale = tuple(
        bounded_ratio(
            measured_values[axis] / measured_anchor,
            authored[axis] / authored_anchor,
            maximum_delta,
        )
        for axis in range(3)
    )
    for component, path, _world in _components(proposal):
        dimensions = component.get("dimensions")
        if isinstance(dimensions, dict):
            for field, factor, measurement in (
                ("dimensions.width", scale[0], float(measured[0])),
                ("dimensions.height", scale[1], float(measured[1])),
                ("dimensions.depth", scale[2], float(measured[2])),
            ):
                value = dimensions.get(field.split(".")[-1])
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    _set_change(component, path, field, float(value) * factor, changes, scope="global-massing", measured=measurement, confidence=0.8, source_region="global")
                    axis = {"dimensions.width": 0, "dimensions.height": 1, "dimensions.depth": 2}[field]
                    _sync_transform_scale(component, path, (axis,), factor, changes, scope="global-massing", measured=measurement, confidence=0.8, source_region="global", derived_from=field)
            radius = dimensions.get("radius")
            if isinstance(radius, (int, float)) and not isinstance(radius, bool):
                _set_change(component, path, "dimensions.radius", float(radius) * ((scale[0] + scale[2]) / 2.0), changes, scope="global-massing", measured=(float(measured[0]) + float(measured[2])) / 2.0, confidence=0.75, source_region="global")
            length = dimensions.get("length")
            dominant = component.get("dominantAxis")
            if isinstance(length, (int, float)) and not isinstance(length, bool) and dominant in {"x", "y", "z"}:
                axis = {"x": 0, "y": 1, "z": 2}[str(dominant)]
                _set_change(component, path, "dimensions.length", float(length) * scale[axis], changes, scope="global-massing", measured=float(measured[axis]), confidence=0.75, source_region="global")
        transform = component.get("transform")
        position = transform.get("position") if isinstance(transform, dict) else None
        if isinstance(position, list) and len(position) == 3:
            for axis in range(3):
                if isinstance(position[axis], (int, float)) and not isinstance(position[axis], bool):
                    _set_change(component, path, f"transform.position.{axis}", float(position[axis]) * scale[axis], changes, scope="global-massing", measured=float(measured[axis]), confidence=0.8, source_region="global")
    return scale


def _component_proposal(
    proposal: dict[str, object],
    evidence: dict[str, object],
    component_map: dict[str, object] | None,
    changes: list[dict[str, object]],
) -> None:
    if component_map is not None:
        mappings = component_map.get("mappings")
        if isinstance(mappings, list):
            for mapping in mappings:
                fields = mapping.get("permittedFields") if isinstance(mapping, dict) else None
                if isinstance(fields, list) and any(
                    field not in COMPONENT_PERMITTED_FIELDS for field in fields
                ):
                    raise ValueError(
                        "influence_scope_exceeded: component field is forbidden"
                    )
    validation = validate_dense_evidence(evidence, proposal, component_map)
    if not validation["passed"]:
        category = validation["failureCategories"][0] if validation["failureCategories"] else "component_mapping_invalid"
        raise ValueError(f"{category}: {'; '.join(validation['errors'])}")
    if component_map is None:
        raise ValueError("component_mapping_invalid: component map is required")
    components = {str(item.get("id")): (item, path) for item, path, _world in _components(proposal)}
    regions = {
        str(item.get("regionId")): item
        for item in evidence.get("regions", [])
        if isinstance(item, dict)
    }
    maximum_delta = _max_delta(proposal)
    for mapping in component_map.get("mappings", []):
        fields = mapping.get("permittedFields", [])
        if any(field not in COMPONENT_PERMITTED_FIELDS for field in fields):
            raise ValueError("influence_scope_exceeded: component field is forbidden")
        component, path = components[str(mapping["componentId"])]
        region = regions[str(mapping["selectors"][0]["regionId"])]
        size = [float(value) for value in region["bounds"]["size"]]
        dimensions = component.get("dimensions", {})
        common = {
            "scope": "component-measurements",
            "confidence": float(mapping["confidence"]),
            "source_region": str(region["regionId"]),
        }

        def numeric(value: object) -> float | None:
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        for field in fields:
            key = field.split(".")[-1]
            if field in {"dimensions.width", "dimensions.height", "dimensions.depth"}:
                axis = {"width": 0, "height": 1, "depth": 2}[key]
                old = numeric(dimensions.get(key))
                if old is None:
                    continue
                factor = bounded_ratio(size[axis], old, maximum_delta)
                _set_change(component, path, field, old * factor, changes, measured=size[axis], **common)
                _sync_transform_scale(component, path, (axis,), factor, changes, measured=size[axis], derived_from=field, **common)
            elif field == "dimensions.radius":
                # Mean of the region's lateral extents, halved: a cylinder's radius, robust to a
                # slightly elliptical crop.
                old = numeric(dimensions.get("radius"))
                if old is None:
                    continue
                measured = (size[0] + size[2]) / 4.0
                factor = bounded_ratio(measured, old, maximum_delta)
                _set_change(component, path, field, old * factor, changes, measured=measured, **common)
                _sync_transform_scale(component, path, (0, 2), factor, changes, measured=measured, derived_from=field, **common)
            elif field == "dimensions.length":
                old = numeric(dimensions.get("length"))
                if old is None:
                    continue
                dominant = component.get("dominantAxis")
                axis = AXIS_INDEX[str(dominant)] if dominant in AXIS_INDEX else max(range(3), key=lambda i: size[i])
                factor = bounded_ratio(size[axis], old, maximum_delta)
                _set_change(component, path, field, old * factor, changes, measured=size[axis], **common)
                _sync_transform_scale(component, path, (axis,), factor, changes, measured=size[axis], derived_from=field, **common)
            elif field == "geometryDescriptor.latheProfile.radii":
                _lathe_profile_proposal(component, path, region, changes, maximum_delta, common)
            elif field in {"attachment.baseRadius", "attachment.endRadius"}:
                _attachment_radius_proposal(component, path, region, field, changes, maximum_delta, common)


def _profile_stations(region: dict[str, Any]) -> list[tuple[float, float]]:
    stations = [
        (float(item[0]), float(item[1]))
        for item in region.get("profile", [])
        if isinstance(item, list) and len(item) == 2
    ]
    stations.sort(key=lambda item: item[0])
    return stations


def _interpolate_radius(stations: list[tuple[float, float]], position: float) -> float:
    if position <= stations[0][0]:
        return stations[0][1]
    if position >= stations[-1][0]:
        return stations[-1][1]
    for (p0, r0), (p1, r1) in zip(stations, stations[1:]):
        if p0 <= position <= p1:
            t = 0.0 if p1 == p0 else (position - p0) / (p1 - p0)
            return r0 + (r1 - r0) * t
    return stations[-1][1]


def _lateral_scale(component: dict[str, Any]) -> float | None:
    """World units per unit-lathe radius: the mean lateral transform.scale (or dimensions)."""
    transform = component.get("transform")
    scale = transform.get("scale") if isinstance(transform, dict) else None
    if isinstance(scale, list) and len(scale) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in scale
    ):
        lateral = (float(scale[0]) + float(scale[2])) / 2.0
        return lateral if lateral > 0 else None
    dimensions = component.get("dimensions")
    if isinstance(dimensions, dict):
        width = dimensions.get("width")
        depth = dimensions.get("depth")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (width, depth)):
            lateral = (float(width) + float(depth)) / 2.0
            return lateral if lateral > 0 else None
    return None


def _lathe_profile_proposal(
    component: dict[str, Any],
    path: list[object],
    region: dict[str, Any],
    changes: list[dict[str, object]],
    maximum_delta: float,
    common: dict[str, Any],
) -> None:
    """Resample the region's measured radius at every authored lathe station.

    Authored `latheProfile.points` are [radius, height] in the component's unit frame
    (radius 0..0.5, height -0.5..0.5) and the generator scales them by transform.scale, so the
    measured world radius is divided by the lateral scale before comparison. Heights are the
    authored ones -- only the radius column changes, each station bounded on its own.
    """
    stations = _profile_stations(region)
    descriptor = component.get("geometryDescriptor")
    profile = descriptor.get("latheProfile") if isinstance(descriptor, dict) else None
    points = profile.get("points") if isinstance(profile, dict) else None
    lateral = _lateral_scale(component)
    if len(stations) < 2 or not isinstance(points, list) or lateral is None:
        return
    heights = [
        float(point[1]) for point in points
        if isinstance(point, list) and len(point) == 2 and isinstance(point[1], (int, float))
    ]
    if len(heights) < 2 or max(heights) - min(heights) <= 1e-12:
        return
    low, high = min(heights), max(heights)
    station_low, station_high = stations[0][0], stations[-1][0]
    for index, point in enumerate(points):
        if not (isinstance(point, list) and len(point) == 2):
            continue
        radius = point[0]
        if not isinstance(radius, (int, float)) or isinstance(radius, bool) or float(radius) <= 0:
            continue
        t = (float(point[1]) - low) / (high - low)
        measured_world = _interpolate_radius(stations, station_low + t * (station_high - station_low))
        measured_unit = measured_world / lateral
        factor = bounded_ratio(measured_unit, float(radius), maximum_delta)
        _set_change(
            component, path, f"geometryDescriptor.latheProfile.points.{index}.0", float(radius) * factor, changes,
            measured=measured_unit, field_label="geometryDescriptor.latheProfile.radii", **common,
        )


def _attachment_radius_proposal(
    component: dict[str, Any],
    path: list[object],
    region: dict[str, Any],
    field: str,
    changes: list[dict[str, object]],
    maximum_delta: float,
    common: dict[str, Any],
) -> None:
    """Strut radii from the two ends of the region profile.

    `base` is the localStart end and `end` the localEnd end of the attachment; when the
    attachment does not say which way it runs along the profile axis, base is the low station.
    """
    stations = _profile_stations(region)
    attachment = component.get("attachment")
    if len(stations) < 2 or not isinstance(attachment, dict):
        return
    key = field.split(".")[-1]
    old = attachment.get(key)
    if not isinstance(old, (int, float)) or isinstance(old, bool) or float(old) <= 0:
        return
    axis = AXIS_INDEX.get(str(region.get("profileAxis")), 1)
    start = attachment.get("localStart")
    end = attachment.get("localEnd")
    base_is_low = True
    if isinstance(start, list) and isinstance(end, list) and len(start) == 3 and len(end) == 3:
        try:
            base_is_low = float(start[axis]) <= float(end[axis])
        except (TypeError, ValueError):
            base_is_low = True
    low_radius, high_radius = stations[0][1], stations[-1][1]
    measured = (low_radius if base_is_low else high_radius) if key == "baseRadius" else (high_radius if base_is_low else low_radius)
    factor = bounded_ratio(measured, float(old), maximum_delta)
    _set_change(component, path, field, float(old) * factor, changes, measured=measured, **common)


def build_proposal(
    accepted_spec: dict[str, object],
    evidence: dict[str, object],
    admission: dict[str, object],
    component_map: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    scope = _validate_binding(accepted_spec, evidence, admission, component_map)
    proposal = copy.deepcopy(accepted_spec)
    changes: list[dict[str, object]] = []
    if scope == "global-massing":
        scale = _global_proposal(proposal, evidence, changes)
    else:
        _component_proposal(proposal, evidence, component_map, changes)
        scale = (1.0, 1.0, 1.0)
    delta = {
        "schemaVersion": 1,
        "kind": "dense-evidence-spec-delta",
        "acceptedSpecSha256": _canonical_sha256(accepted_spec),
        "proposedSpecSha256": _canonical_sha256(proposal),
        "evidenceSha256": _canonical_sha256(evidence),
        "approvedScope": scope,
        "changes": changes,
    }
    fit_plan = {
        "schemaVersion": 1,
        "kind": "dense-evidence-fit-plan",
        "acceptedSpecSha256": delta["acceptedSpecSha256"],
        "proposedSpecSha256": delta["proposedSpecSha256"],
        "evidenceSha256": delta["evidenceSha256"],
        "correctionGroup": "silhouette",
        "parameterVector": list(scale),
        "requiredBrowserViews": ["source", "front", "right", "rear", "left"],
        "minimumEvidenceImprovement": 0.01,
        "maximumSourceSilhouetteRegression": 0.02,
        "correctionLoopBudget": {"maxPerPass": 3, "maxTotal": 6},
    }
    return proposal, delta, fit_plan


def _set_path(root: object, path: list[object], value: object) -> None:
    target: Any = root
    for token in path[:-1]:
        target = target[token]
    target[path[-1]] = value


def apply_reverse_delta(
    proposed_spec: dict[str, object], delta: dict[str, object]
) -> dict[str, object]:
    restored = copy.deepcopy(proposed_spec)
    changes = delta.get("changes", [])
    if not isinstance(changes, list):
        raise ValueError("delta changes must be a list")
    for change in reversed(changes):
        if not isinstance(change, dict) or not isinstance(change.get("path"), list):
            raise ValueError("delta change path is invalid")
        _set_path(restored, change["path"], change.get("old"))
    return restored


def _write_atomic(path: Path, value: object) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--component-map", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--delta-out", type=Path, required=True)
    parser.add_argument("--fit-plan-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        admission = json.loads(args.admission.read_text(encoding="utf-8"))
        component_map = json.loads(args.component_map.read_text(encoding="utf-8")) if args.component_map else None
        # Admissions created by the CLI bind exact file bytes. Rebind only after those exact
        # hashes have been checked here, then use the same pure proposal implementation.
        binding = admission.get("binding", {})
        exact = {
            "targetSpecSha256": hashlib.sha256(args.spec.read_bytes()).hexdigest(),
            "evidenceSha256": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
        }
        if args.component_map:
            exact["componentMapSha256"] = hashlib.sha256(args.component_map.read_bytes()).hexdigest()
        if not isinstance(binding, dict) or any(binding.get(key) != value for key, value in exact.items()):
            raise ValueError("admission_hash_mismatch: exact input bytes changed")
        normalized = copy.deepcopy(admission)
        normalized["binding"]["targetSpecSha256"] = _canonical_sha256(spec)
        normalized["binding"]["evidenceSha256"] = _canonical_sha256(evidence)
        if component_map is not None:
            normalized["binding"]["componentMapSha256"] = _canonical_sha256(component_map)
        proposal, delta, fit_plan = build_proposal(spec, evidence, normalized, component_map)
        _write_atomic(args.out, proposal)
        _write_atomic(args.delta_out, delta)
        _write_atomic(args.fit_plan_out, fit_plan)
        validator = ROOT / "forge" / "stage2_spec" / "validate_sculpt_spec.py"
        normal = subprocess.run([sys.executable, str(validator), str(args.out)], capture_output=True, text=True, check=False)
        strict = subprocess.run([sys.executable, str(validator), str(args.out), "--strict-quality"], capture_output=True, text=True, check=False)
        if normal.returncode or strict.returncode:
            print(json.dumps({"status": "strict_quality_failed", "normal": normal.stdout + normal.stderr, "strict": strict.stdout + strict.stderr}, ensure_ascii=False))
            return 1
        print(json.dumps({"status": "complete", "proposal": str(args.out), "changes": len(delta["changes"])}, ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
