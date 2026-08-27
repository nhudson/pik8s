#!/usr/bin/env python3
"""Contracts for the official Cilium Agent Grafana dashboard."""
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
RELEASE = ROOT / "kubernetes/apps/kube-system/cilium/app/helmrelease.yaml"
CHART_URL = "https://helm.cilium.io/cilium-1.20.1.tgz"
CHART_SHA256 = "06210eef7c23d15f7699c79e2fe3a1ec9c389024c5c5c006ea04022d322449a2"


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


class CiliumDashboardTests(unittest.TestCase):
    def test_official_agent_dashboard_is_provisioned_where_grafana_watches(self):
        release = yaml.safe_load(RELEASE.read_text())
        self.assertEqual("1.20.1", release["spec"]["chart"]["spec"]["version"])
        dashboard = release["spec"]["values"]["dashboards"]
        self.assertTrue(dashboard["enabled"])
        self.assertEqual("monitoring", dashboard["namespace"])
        self.assertEqual("grafana_dashboard", dashboard["label"])
        self.assertEqual("1", dashboard["labelValue"])
        self.assertEqual("Cilium", dashboard["annotations"]["grafana_folder"])

    def test_exact_chart_renders_only_the_agent_dashboard_into_monitoring(self):
        archive = pathlib.Path(tempfile.gettempdir()) / "cilium-1.20.1.tgz"
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != CHART_SHA256:
            with urllib.request.urlopen(CHART_URL, timeout=30) as response:
                archive.write_bytes(response.read())
        self.assertEqual(CHART_SHA256, hashlib.sha256(archive.read_bytes()).hexdigest())
        release = yaml.safe_load(RELEASE.read_text())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as values:
            yaml.safe_dump(release["spec"]["values"], values)
            values.flush()
            completed = subprocess.run(
                [os.environ.get("HELM_BIN", "helm"), "template", "cilium", str(archive), "-n", "kube-system", "-f", values.name],
                text=True,
                capture_output=True,
            )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        resources = [item for item in yaml.load_all(completed.stdout, Loader=UniqueKeyLoader) if item]
        monitoring_dashboards = [
            item
            for item in resources
            if item.get("kind") == "ConfigMap"
            and item.get("metadata", {}).get("namespace") == "monitoring"
            and item.get("metadata", {}).get("labels", {}).get("grafana_dashboard") == "1"
        ]
        self.assertEqual(1, len(monitoring_dashboards))
        config_map = monitoring_dashboards[0]
        self.assertEqual("cilium-dashboard", config_map["metadata"]["name"])
        payload = json.loads(next(iter(config_map["data"].values())))
        self.assertEqual("Cilium Metrics", payload["title"])
        self.assertTrue(payload["uid"])
        self.assertGreater(len(payload["panels"]), 0)
        grafana_workloads = [
            item
            for item in resources
            if item.get("kind") in {"Deployment", "StatefulSet", "Service", "PersistentVolumeClaim"}
            and "grafana" in item.get("metadata", {}).get("name", "").lower()
        ]
        self.assertEqual([], grafana_workloads)

    def test_provenance_and_canonical_validation_are_wired(self):
        provenance = (ROOT / "docs/runbooks/monitoring/dashboard-sources.md").read_text()
        for expected in (
            "2428bc06f693c9ccde087c8901ebd291941262b6",
            CHART_SHA256,
            "Cilium Metrics",
            "Apache-2.0",
        ):
            self.assertIn(expected, provenance)
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("python3 ./scripts/test-cilium-dashboard.py", canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
