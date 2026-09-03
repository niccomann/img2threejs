"""Region inventory: candidate node boundaries plus human-reviewed selector crops.

Two kinds of region can appear in `dense-evidence.v1.json`:

* **candidate** regions come from explicit GLB node boundaries (`inventory_boundaries`). They
  carry no semantics (`candidateOnly: true`, `semanticLabel: null`) and only exist when the
  provider mesh is multipart.
* **reviewed** regions come from an authored, hash-bound `region-selectors.json`
  (`reviewed_regions`). A human (or an agent under review) crops the aligned point cloud with
  an axis-aligned box and names what that box contains. The bridge never labels geometry on
  its own; the selector file IS the review, and it is bound to the GLB by SHA-256 so it cannot
  drift to another mesh.

A reviewed region optionally carries a radius-vs-station `profile` along one axis, so a lathe
or a tapered strut can be measured station by station instead of by its bounding box alone.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import trimesh

from .model import DenseEvidenceError, finite_number

REGION_SELECTORS_KIND = "dense-evidence-region-selectors"
REVIEWED_REGION_PREFIX = "reviewed:"
MIN_REGION_POINTS = 64
MAX_PROFILE_STATIONS = 24
PROFILE_AXES = {"x": 0, "y": 1, "z": 2}
# Radial extent at a station: the band is split into angular sectors around the region's axis,
# the outermost point of each occupied sector is taken, and the station radius is the median
# of those sector maxima. A plain percentile over all band points underestimates a capped
# shell (the bottom disc of an islet fills the band with interior vertices), while a raw
# maximum lets a single stray vertex set the whole station.
PROFILE_SECTORS = 24


def inventory_boundaries(
    scene: trimesh.Scene, transform: np.ndarray
) -> list[dict[str, Any]]:
    nodes = sorted(str(node) for node in scene.graph.nodes_geometry)
    if len(nodes) <= 1:
        return []
    records: list[dict[str, Any]] = []
    for node in nodes:
        node_transform, geometry_name = scene.graph[node]
        geometry = scene.geometry[geometry_name]
        points = trimesh.transform_points(
            np.asarray(geometry.vertices, dtype=float), transform @ node_transform
        )
        minimum = points.min(axis=0)
        maximum = points.max(axis=0)
        records.append(
            {
                "regionId": f"node:{node}/geometry:{geometry_name}",
                "node": node,
                "geometry": str(geometry_name),
                "candidateOnly": True,
                "semanticLabel": None,
                "bounds": {
                    "min": minimum.tolist(),
                    "max": maximum.tolist(),
                    "size": (maximum - minimum).tolist(),
                },
            }
        )
    return records


def _vec3(value: object, field: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise DenseEvidenceError("region_selector_invalid", f"{field} must be three numbers")
    return tuple(finite_number(item, f"{field}[{index}]") for index, item in enumerate(value))  # type: ignore[return-value]


def validate_region_selectors(payload: object, glb_sha256: str) -> list[dict[str, Any]]:
    """Validate an authored selectors file and bind it to the provider GLB.

    Returns the normalised selector list. Raises `region_selector_invalid` for shape problems
    and `evidence_hash_mismatch` when the file was authored against another mesh.
    """
    if not isinstance(payload, dict):
        raise DenseEvidenceError("region_selector_invalid", "selectors must be a JSON object")
    if payload.get("schemaVersion") != 1 or payload.get("kind") != REGION_SELECTORS_KIND:
        raise DenseEvidenceError("region_selector_invalid", "unsupported region selectors contract")
    if payload.get("glbSha256") != glb_sha256:
        raise DenseEvidenceError(
            "evidence_hash_mismatch", "region selectors are bound to another GLB"
        )
    selectors = payload.get("selectors")
    if not isinstance(selectors, list) or not selectors:
        raise DenseEvidenceError("region_selector_invalid", "selectors must be a non-empty list")
    seen: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for index, selector in enumerate(selectors):
        label = f"selectors[{index}]"
        if not isinstance(selector, dict):
            raise DenseEvidenceError("region_selector_invalid", f"{label} must be an object")
        region_id = selector.get("regionId")
        if not isinstance(region_id, str) or not region_id.startswith(REVIEWED_REGION_PREFIX) or len(region_id) <= len(REVIEWED_REGION_PREFIX):
            raise DenseEvidenceError(
                "region_selector_invalid", f"{label}.regionId must start with {REVIEWED_REGION_PREFIX!r}"
            )
        if region_id in seen:
            raise DenseEvidenceError("region_selector_invalid", f"{label}.regionId is duplicated")
        seen.add(region_id)
        semantic = selector.get("semanticLabel")
        if not isinstance(semantic, str) or not semantic.strip():
            raise DenseEvidenceError("region_selector_invalid", f"{label}.semanticLabel is required")
        box = selector.get("box")
        if not isinstance(box, dict):
            raise DenseEvidenceError("region_selector_invalid", f"{label}.box must be an object")
        minimum = _vec3(box.get("min"), f"{label}.box.min")
        maximum = _vec3(box.get("max"), f"{label}.box.max")
        if any(maximum[axis] <= minimum[axis] for axis in range(3)):
            raise DenseEvidenceError("region_selector_invalid", f"{label}.box max must exceed min on every axis")
        profile_axis = selector.get("profileAxis")
        if profile_axis is not None and profile_axis not in PROFILE_AXES:
            raise DenseEvidenceError("region_selector_invalid", f"{label}.profileAxis must be x, y or z")
        if selector.get("observedSurface") is not True:
            raise DenseEvidenceError(
                "region_selector_invalid", f"{label}.observedSurface must be true (hidden surfaces cannot be reviewed)"
            )
        note = selector.get("reviewNote")
        if note is not None and not isinstance(note, str):
            raise DenseEvidenceError("region_selector_invalid", f"{label}.reviewNote must be a string")
        normalised.append(
            {
                "regionId": region_id,
                "semanticLabel": semantic.strip(),
                "box": {"min": list(minimum), "max": list(maximum)},
                "profileAxis": profile_axis,
                "observedSurface": True,
                "reviewNote": note,
            }
        )
    return normalised


def _profile(points: np.ndarray, axis: str, stations: int) -> list[list[float]]:
    index = PROFILE_AXES[axis]
    lateral = [i for i in range(3) if i != index]
    center = (points[:, lateral].min(axis=0) + points[:, lateral].max(axis=0)) / 2.0
    low = float(points[:, index].min())
    high = float(points[:, index].max())
    if high - low <= 1e-9:
        return []
    centers = np.linspace(low, high, stations)
    half_band = max((high - low) / max(stations * 2, 1), 1e-9)
    records: list[list[float]] = []
    for station in centers:
        selected = points[np.abs(points[:, index] - station) <= half_band]
        if len(selected) < 3:
            continue
        offsets = selected[:, lateral] - center
        radial = np.linalg.norm(offsets, axis=1)
        angles = np.arctan2(offsets[:, 1], offsets[:, 0])
        sector = np.floor((angles + np.pi) / (2 * np.pi) * PROFILE_SECTORS).astype(int) % PROFILE_SECTORS
        maxima = [float(radial[sector == s].max()) for s in range(PROFILE_SECTORS) if np.any(sector == s)]
        records.append([float(station), float(np.median(maxima))])
    return records


def reviewed_regions(
    points: np.ndarray, selectors: list[dict[str, Any]], *, stations: int = MAX_PROFILE_STATIONS
) -> list[dict[str, Any]]:
    """Crop the aligned point cloud with each reviewed selector box.

    Every selector must keep at least MIN_REGION_POINTS points, otherwise the review named a
    box that contains no observed geometry and the run fails with `region_selector_empty`.
    """
    if not 1 <= stations <= MAX_PROFILE_STATIONS:
        raise DenseEvidenceError("measurement_limit_exceeded", "profile stations exceed 24")
    records: list[dict[str, Any]] = []
    for selector in selectors:
        minimum = np.asarray(selector["box"]["min"], dtype=float)
        maximum = np.asarray(selector["box"]["max"], dtype=float)
        mask = np.all((points >= minimum) & (points <= maximum), axis=1)
        selected = points[mask]
        if len(selected) < MIN_REGION_POINTS:
            raise DenseEvidenceError(
                "region_selector_empty",
                f"{selector['regionId']} selects {len(selected)} points (< {MIN_REGION_POINTS})",
            )
        low = selected.min(axis=0)
        high = selected.max(axis=0)
        record: dict[str, Any] = {
            "regionId": selector["regionId"],
            "semanticLabel": selector["semanticLabel"],
            "candidateOnly": False,
            "reviewed": True,
            "observedSurface": True,
            "bounds": {
                "min": low.tolist(),
                "max": high.tolist(),
                "size": (high - low).tolist(),
            },
            "pointCount": int(len(selected)),
        }
        if selector.get("reviewNote"):
            record["reviewNote"] = selector["reviewNote"]
        axis = selector.get("profileAxis")
        if axis in PROFILE_AXES:
            record["profileAxis"] = axis
            record["profile"] = _profile(selected, axis, stations)
        records.append(record)
    return records
