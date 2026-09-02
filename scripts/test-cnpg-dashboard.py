#!/usr/bin/env python3
"""Contracts for the official CloudNativePG Grafana dashboard."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
import urllib.request

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASE = ROOT / "kubernetes/apps/postgres/cloudnative-pg/app/helmrelease.yaml"
SOURCE = ROOT / "kubernetes/flux/repositories/helm/cloudnative-pg-charts.yaml"
CHART_URL = "https://github.com/cloudnative-pg/charts/releases/download/cloudnative-pg-v0.29.0/cloudnative-pg-0.29.0.tgz"
CHART_SHA256 = "668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f"


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError("mapping", node.start_mark, f"duplicate key: {key}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)


class CloudNativePGDashboardTests(unittest.TestCase):
    def test_official_dashboard_is_provisioned_where_grafana_watches(self):
        release = yaml.safe_load(RELEASE.read_text())
        source = yaml.safe_load(SOURCE.read_text())
        self.assertEqual("HelmRepository", source["kind"])
        self.assertEqual(
            "https://raw.githubusercontent.com/cloudnative-pg/charts/gh-pages",
            source["spec"]["url"],
        )
        self.assertEqual("0.29.0", release["spec"]["chart"]["spec"]["version"])
        dashboard = release["spec"]["values"]["monitoring"]["grafanaDashboard"]
        self.assertTrue(dashboard["create"])
        self.assertEqual("monitoring", dashboard["namespace"])
        self.assertEqual("cnpg-grafana-dashboard", dashboard["configMapName"])
        self.assertEqual({"grafana_dashboard": "1"}, dashboard["labels"])
        self.assertEqual("", dashboard["sidecarLabel"])
        self.assertEqual("", dashboard["sidecarLabelValue"])

    def test_exact_pinned_chart_renders_one_discoverable_official_dashboard(self):
        archive = pathlib.Path(tempfile.gettempdir()) / "cloudnative-pg-0.29.0.tgz"
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != CHART_SHA256:
            with urllib.request.urlopen(CHART_URL, timeout=30) as response:
                archive.write_bytes(response.read())
        self.assertEqual(CHART_SHA256, hashlib.sha256(archive.read_bytes()).hexdigest())
        release = yaml.safe_load(RELEASE.read_text())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as values:
            yaml.safe_dump(release["spec"]["values"], values)
            values.flush()
            completed = subprocess.run(
                [os.environ.get("HELM_BIN", "helm"), "template", "cnpg", str(archive), "-n", "cnpg-system", "-f", values.name],
                text=True,
                capture_output=True,
            )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        resources = [item for item in yaml.load_all(completed.stdout, Loader=UniqueKeyLoader) if item]
        dashboards = [
            item
            for item in resources
            if item.get("kind") == "ConfigMap" and item.get("metadata", {}).get("name") == "cnpg-grafana-dashboard"
        ]
        self.assertEqual(1, len(dashboards))
        config_map = dashboards[0]
        self.assertEqual("monitoring", config_map["metadata"]["namespace"])
        self.assertEqual("1", config_map["metadata"]["labels"]["grafana_dashboard"])
        payload = json.loads(next(value for key, value in config_map["data"].items() if key.endswith(".json")))
        self.assertEqual("CloudNativePG", payload["title"])
        self.assertEqual("cloudnative-pg", payload["uid"])
        self.assertEqual(66, len(payload["panels"]))

    def test_pinned_official_source_and_canonical_validation_are_documented(self):
        provenance = (ROOT / "docs/runbooks/monitoring/dashboard-sources.md").read_text()
        for expected in ("cluster-v0.0.5", "cececeb393fb7c5400b4fa290aca68041293a127", "Apache-2.0"):
            self.assertIn(expected, provenance)
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("python3 ./scripts/test-cnpg-dashboard.py", canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
