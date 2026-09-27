"""Code-verified seeds for the metric catalog V2.

This module is the single extension point for metrics whose calculation and
page usage have been verified against code.  Documentation-only rows must not
be added here; they belong to ``sys_metric_candidate`` until implementation
evidence is available.
"""
from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from types import ModuleType

from .metric_catalog import IMPLEMENTED_METRICS, TECHNICAL_ONLY_METRICS


def _optional_extension(name: str) -> ModuleType | None:
    """Load an independent verified-seed pack when it is present."""
    qualified = f"{__package__}.{name}"
    try:
        return import_module(qualified)
    except ModuleNotFoundError as exc:
        if exc.name == qualified:
            return None
        raise


def _merge_records(
    groups: Iterable[Iterable[dict]], key_fields: tuple[str, ...],
) -> tuple[dict, ...]:
    """Merge deterministic seed packs; later packs replace the same identity."""
    merged: dict[tuple, dict] = {}
    for group in groups:
        for item in group:
            key = tuple(str(item.get(field, "")) for field in key_fields)
            merged[key] = dict(item)
    return tuple(merged[key] for key in sorted(merged))


_EXTENSIONS = tuple(filter(None, (
    _optional_extension("metric_catalog_verified_core"),
    _optional_extension("metric_catalog_verified_operations"),
    _optional_extension("metric_catalog_verified_reports"),
)))


def _extension_groups(attribute: str) -> tuple[Iterable[dict], ...]:
    return tuple(getattr(module, attribute, ()) for module in _EXTENSIONS)


# Future verified metrics live in independent packs so they can be reviewed by
# business module.  The central catalog performs deterministic de-duplication.
EXTRA_VERIFIED_METRICS: tuple[dict, ...] = _merge_records(
    _extension_groups("EXTRA_VERIFIED_METRICS"), ("metric_id",),
)

# A source metric references/depends on its target metrics.  Keep only edges
# supported by calculation evidence.  F-17's numerator is the verified active
# teaching-teacher population represented by F-01.
_LEGACY_DEPENDENCIES: tuple[dict, ...] = (
    {
        "source_metric_id": "F-17",
        "target_metric_id": "F-01",
        "relation_type": "calculation_input",
        "description": "授课教师覆盖率以授课教师总数作为分子口径。",
        "source_ref": "code/backend/metric_catalog.py#IMPLEMENTED_METRICS",
    },
)

# Optional structured extensions.  Empty tables remain preferable to inventing
# unverified business relationships.
VERIFIED_DEPENDENCIES: tuple[dict, ...] = _merge_records(
    (_LEGACY_DEPENDENCIES, *_extension_groups("VERIFIED_DEPENDENCIES")),
    ("source_metric_id", "target_metric_id", "relation_type"),
)
VERIFIED_RULE_BINDINGS: tuple[dict, ...] = _merge_records(
    _extension_groups("VERIFIED_RULE_BINDINGS"),
    ("metric_id", "rule_type", "rule_id", "role"),
)
VERIFIED_ALIASES: tuple[dict, ...] = _merge_records(
    _extension_groups("VERIFIED_ALIASES"),
    ("metric_id", "alias", "alias_type"),
)
VERIFIED_USAGE_POINTS: tuple[dict, ...] = _merge_records(
    _extension_groups("VERIFIED_USAGE_POINTS"),
    ("metric_id", "module_path", "feature_name", "usage_type", "occurrence_key"),
)
VERIFIED_ISSUES: tuple[dict, ...] = _merge_records(
    _extension_groups("VERIFIED_ISSUES"),
    ("metric_id", "issue_type", "description"),
)


def iter_verified_metric_seeds(
    documented_metrics: Iterable[dict],
) -> list[dict]:
    """Convert the legacy verified registry to the V2 normalized seed shape."""
    documented = {item["metric_id"]: item for item in documented_metrics}
    seeds: list[dict] = []

    for metric_id, evidence in IMPLEMENTED_METRICS.items():
        definition = documented.get(metric_id, {})
        pages = [
            {
                "module_path": path,
                "feature_name": display_name,
                "feature_description": f"页面“{display_name}”指标展示与下钻入口。",
                "usage_type": "display",
                "occurrence_key": f"{path}:{display_name}",
                "source_ref": "code/backend/metric_catalog.py#IMPLEMENTED_METRICS",
            }
            for path, display_name in evidence.get("pages", [])
        ]
        display_name = pages[0]["feature_name"] if pages else metric_id
        seeds.append({
            "metric_id": metric_id,
            "metric_code": metric_id,
            "technical_kpi_id": evidence.get("technical_kpi_id"),
            "domain": definition.get("domain", "其他"),
            "name": definition.get("name", display_name),
            "description": definition.get("management_value", ""),
            "formula": definition.get("formula", ""),
            "boundary": definition.get("boundary", ""),
            "management_value": definition.get("management_value", ""),
            "definition_status": evidence.get("status", "published"),
            "implementation_status": "verified",
            "data_source": evidence.get("data_source", ""),
            "grain": evidence.get("grain", ""),
            "update_cycle": evidence.get("update_cycle", ""),
            "version": evidence.get("version", "1.0"),
            "source_kind": "formal",
            "source_ref": "code/backend/metric_catalog.py#IMPLEMENTED_METRICS",
            "pages": pages,
        })

    for item in TECHNICAL_ONLY_METRICS:
        pages = [
            {
                "module_path": path,
                "feature_name": display_name,
                "feature_description": f"页面“{display_name}”指标展示与下钻入口。",
                "usage_type": "display",
                "occurrence_key": f"{path}:{display_name}",
                "source_ref": item["definition_source"],
            }
            for path, display_name in item.get("pages", [])
        ]
        seeds.append({
            **item,
            "metric_code": item["metric_id"],
            "description": item.get("management_value", ""),
            "source_ref": item["definition_source"],
            "pages": pages,
        })

    seeds.extend(dict(item) for item in EXTRA_VERIFIED_METRICS)
    # Extension packs may refine an existing legacy seed.  The last occurrence
    # wins while output ordering stays stable for snapshots and tests.
    deduplicated = {item["metric_id"]: item for item in seeds}
    return [deduplicated[key] for key in sorted(deduplicated)]
