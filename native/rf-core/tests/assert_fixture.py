#!/usr/bin/env python3
"""Compare rf-core JSON output against a golden fixture."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def load(path: str) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: assert_fixture.py expected.json actual.json")

    expected = load(sys.argv[1])
    actual = load(sys.argv[2])

    for key in ("engine", "error_code", "warnings"):
        if actual.get(key) != expected.get(key):
            raise AssertionError(f"{key}: expected {expected.get(key)!r}, got {actual.get(key)!r}")

    tolerance_db = expected.get("tolerance_db", 0.001)
    delta = abs(float(actual["path_loss_db"]) - float(expected["path_loss_db"]))
    if not math.isfinite(delta) or delta > tolerance_db:
        raise AssertionError(
            f"path_loss_db delta {delta:.6f} exceeds tolerance {tolerance_db:.6f}"
        )

    print("rf-core fixture check passed")


if __name__ == "__main__":
    main()

