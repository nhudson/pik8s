#!/usr/bin/env python3
"""Contracts for Flux controller telemetry and dashboard provisioning."""
from __future__ import annotations

import hashlib
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/app"
CONTROLLERS = {
    "source-controller",
    "kustomize-controller",
    "helm-controller",
    "notification-controller",
    "image-reflector-controller",
    "image-automation-controller",
    "source-watcher",
}


class FluxMonitoringTests(unittest.TestCase):
    def test_podmonitor_scrapes_all_installed_controllers(self):
        monitor = yaml.safe_load((APP / "flux-podmonitor.yaml").read_text())
        self.assertEqual("flux-system", monitor["spec"]["namespaceSelector"]["matchNames"][0])
        expression = monitor["spec"]["selector"]["matchExpressions"][0]
        self.assertEqual("app", expression["key"])
        self.assertEqual("In", expression["operator"])
        self.assertEqual(CONTROLLERS, set(expression["values"]))
        endpoint = monitor["spec"]["podMetricsEndpoints"][0]
        self.assertEqual("http-prom", endpoint["port"])
        self.assertEqual("60s", endpoint["interval"])

    def test_pinned_upstream_dashboard_is_owned_and_immutable(self):
        resource = yaml.safe_load((APP / "grafana-dashboard-flux-control-plane.yaml").read_text())
        self.assertEqual("1", resource["metadata"]["labels"]["grafana_dashboard"])
        payload = json.loads(resource["data"]["flux-control-plane.json"])
        self.assertTrue(payload.get("uid"))
        self.assertFalse(payload["editable"])
        self.assertIn("Flux", payload["title"])
        provenance = resource["metadata"]["annotations"]
        self.assertEqual("7ab65dc8b90f7a6751d88f18bbb4e1bee33bf334", provenance["observability.home/source-revision"])
        rendered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(rendered).hexdigest(), provenance["observability.home/content-sha256"])

    def test_resources_and_ci_are_wired(self):
        resources = yaml.safe_load((APP / "kustomization.yaml").read_text())["resources"]
        self.assertIn("./flux-podmonitor.yaml", resources)
        self.assertIn("./grafana-dashboard-flux-control-plane.yaml", resources)
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("python3 ./scripts/test-flux-monitoring.py", canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
