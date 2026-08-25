#!/usr/bin/env python3
"""Tiny contract sanity check for the SDK snapshot."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "openapi" / "codag-v1.openapi.json"
CASES = ROOT / "fixtures" / "conformance" / "validation_cases.json"

# Shared conformance cases are keyed by client method; each method exercises one
# request schema. Every required field of that schema must have a reject-case.
CASE_SCHEMAS = {
    "send_metrics": "MetricEvent",
    "reduce_action": "ActionEnvelope",
}


def check_required_fields_are_covered(schemas: dict, cases=None) -> None:
    """Pair each required-field omission with an otherwise identical accept-case."""
    if cases is None:
        cases = json.loads(CASES.read_text())
    for method, schema in CASE_SCHEMAS.items():
        required = set(schemas[schema].get("required", []))
        inputs = {"accept": [], "reject": []}
        for case in cases:
            if case["method"] != method or case.get("dynamic_only"):
                continue
            payload = case["input"]
            if method == "send_metrics":
                events = payload.get("events", [])
                if len(events) != 1:
                    continue
                payload = events[0]
            inputs[case["expect"]].append(payload)
        covered = set()
        for accepted in inputs["accept"]:
            if not required.issubset(accepted):
                continue
            for field in required:
                omitted = {key: value for key, value in accepted.items() if key != field}
                if omitted in inputs["reject"]:
                    covered.add(field)
        missing = sorted(required - covered)
        if missing:
            raise SystemExit(
                f"{schema} required fields have no paired omission reject-case in "
                f"fixtures/conformance/validation_cases.json: " + ", ".join(missing)
            )


def main() -> int:
    spec = json.loads(SPEC.read_text())
    paths = spec.get("paths", {})
    required = (
        ("/health", "get"),
        ("/v1/actions/reduce", "post"),
        ("/v1/metrics/batch", "post"),
        ("/v1/usage/summary", "get"),
        ("/v1/usage/timeseries", "get"),
        ("/v1/usage/breakdown", "get"),
        ("/v1/usage/reliability", "get"),
        ("/v1/trials/report", "get"),
        ("/v1/model-prices", "get"),
        ("/v1/workspace/policy", "get"),
        ("/v1/workspace/policy", "put"),
        ("/v1/service/status", "get"),
    )
    missing = [
        f"{method.upper()} {path}"
        for path, method in required
        if method not in paths.get(path, {})
    ]
    if missing:
        raise SystemExit("missing contract operations: " + ", ".join(missing))
    schemas = spec.get("components", {}).get("schemas", {})
    for name in (
        "ActionEnvelope",
        "ActionResponse",
        "MetricEvent",
        "MetricsBatch",
        "UsageSummary",
        "ModelPrice",
        "ModelPriceCatalog",
        "WorkspacePolicy",
    ):
        if name not in schemas:
            raise SystemExit(f"missing schema: {name}")
    metric_properties = set(schemas["MetricEvent"].get("properties", {}))
    forbidden = {"prompt", "command", "path", "filename", "task", "arguments", "result", "output"}
    leaked = sorted(metric_properties & forbidden)
    if leaked:
        raise SystemExit("content-bearing metric properties are forbidden: " + ", ".join(leaked))
    if schemas["MetricEvent"].get("additionalProperties") is not False:
        raise SystemExit("MetricEvent must reject unknown fields")
    contentless_strings = {
        "id",
        "session_id",
        "install_id",
        "harness",
        "provider",
        "model",
        "decision",
        "reason",
        "client_version",
    }
    unbounded = sorted(
        name
        for name in contentless_strings
        if not schemas["MetricEvent"]["properties"].get(name, {}).get("pattern")
        or not schemas["MetricEvent"]["properties"].get(name, {}).get("maxLength")
    )
    if unbounded:
        raise SystemExit(
            "contentless metric strings require patterns and bounds: "
            + ", ".join(unbounded)
        )
    selectors = schemas.get("Selector", {}).get("properties", {})
    if not selectors.get("id", {}).get("pattern") or not selectors.get("group", {}).get("pattern"):
        raise SystemExit("selector ids and group tokens must be contentless-safe")
    if schemas["ActionResponse"]["properties"]["selectors"].get("maxItems") != 64:
        raise SystemExit("action responses must cap omission selectors at 64")
    check_required_fields_are_covered(schemas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
