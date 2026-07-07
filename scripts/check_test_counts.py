#!/usr/bin/env python3
"""Ensure each SDK keeps at least 50 test cases."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIN_TESTS = 50


def python_count() -> int:
    sys.path.insert(0, str(ROOT / "python" / "src"))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "python" / "tests"))
    return suite.countTestCases()


def typescript_count() -> int:
    count = 0
    for path in (ROOT / "typescript" / "test").glob("*.mjs"):
        count += len(re.findall(r"^test\(", path.read_text(), flags=re.MULTILINE))
    return count


def go_count() -> int:
    env = os.environ.copy()
    env["GOCACHE"] = str(ROOT / ".gocache")
    proc = subprocess.run(
        ["go", "test", "-json", "./..."],
        cwd=ROOT / "go",
        env=env,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    count = 0
    for line in proc.stdout.splitlines():
        event = json.loads(line)
        if event.get("Action") == "pass" and event.get("Test"):
            count += 1
    return count


def main() -> int:
    counts = {
        "python": python_count(),
        "typescript": typescript_count(),
        "go": go_count(),
    }
    for name, count in counts.items():
        print(f"{name}: {count} tests")
        if count < MIN_TESTS:
            raise SystemExit(f"{name} has {count} tests; expected at least {MIN_TESTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
