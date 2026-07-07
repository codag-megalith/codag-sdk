#!/usr/bin/env python3
"""Tiny contract sanity check for the SDK snapshot."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "openapi" / "codag-v1.openapi.json"


def main() -> int:
    spec = json.loads(SPEC.read_text())
    paths = spec.get("paths", {})
    required = {
        "/health": "get",
        "/v1/compact": "post",
        "/v1/capsule": "post",
        "/v1/compact/jobs": "post",
        "/v1/compact/jobs/{job_id}": "get",
    }
    missing = [
        f"{method.upper()} {path}"
        for path, method in required.items()
        if method not in paths.get(path, {})
    ]
    if missing:
        raise SystemExit("missing contract operations: " + ", ".join(missing))
    schemas = spec.get("components", {}).get("schemas", {})
    for name in (
        "CapsuleRequest",
        "LineRecord",
        "CompactResponse",
        "CapsuleResponse",
        "CompactJobCreateResponse",
        "CompactJobResponse",
        "ParseStats",
    ):
        if name not in schemas:
            raise SystemExit(f"missing schema: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
