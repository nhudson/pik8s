#!/usr/bin/env python3
"""Validate every PrometheusRule and its behavior with promtool."""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROMTOOL = os.environ.get("PROMTOOL_BIN", "promtool")
RULE_TESTS = ROOT / "scripts/tests/monitoring-rules.test.yaml"


def run_promtool(*args: str) -> None:
    completed = subprocess.run(
        [PROMTOOL, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode:
        detail = (completed.stdout + completed.stderr).strip()
        raise SystemExit(f"promtool rule validation failed:\n{detail}")


def main() -> None:
    checked = 0
    groups: list[dict] = []
    for path in sorted((ROOT / "kubernetes").rglob("*.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            if not document or document.get("kind") != "PrometheusRule":
                continue
            groups.extend(document["spec"]["groups"])
            checked += 1
    if not checked:
        raise SystemExit("no PrometheusRule resources found")

    with tempfile.TemporaryDirectory(prefix="promtool-rules-") as directory:
        temp = pathlib.Path(directory)
        rules_path = temp / "rules.yaml"
        tests_path = temp / "tests.yaml"
        rules_path.write_text(yaml.safe_dump({"groups": groups}, sort_keys=False))
        tests = yaml.safe_load(RULE_TESTS.read_text())
        tests["rule_files"] = [str(rules_path)]
        tests_path.write_text(yaml.safe_dump(tests, sort_keys=False))
        run_promtool("check", "rules", str(rules_path))
        run_promtool("test", "rules", str(tests_path))

    print(f"PASS: promtool validated {checked} PrometheusRule resources and behavior tests")


if __name__ == "__main__":
    main()
