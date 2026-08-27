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

    def test_flux_mixin_compatibility_pack_is_pinned_current_and_nonduplicative(self):
        dashboard_resource = yaml.safe_load((APP / "grafana-dashboard-flux-cluster.yaml").read_text())
        dashboard = json.loads(dashboard_resource["data"]["flux-cluster.json"])
        self.assertEqual("flux-cluster", dashboard["uid"])
        self.assertEqual("Flux Cluster Stats", dashboard["title"])
        self.assertFalse(dashboard["editable"])
        self.assertGreaterEqual(len(dashboard["panels"]), 13)
        rendered_dashboard = json.dumps(dashboard, sort_keys=True, separators=(",", ":"))
        self.assertIn("$${DS_PROMETHEUS}", rendered_dashboard)
        self.assertNotRegex(rendered_dashboard, r"(?<!\$)\$\{DS_PROMETHEUS\}")
        self.assertIn("gotk_resource_info", rendered_dashboard)
        self.assertIn("gotk_reconcile_duration_seconds", rendered_dashboard)
        self.assertNotIn("gotk_reconcile_condition", rendered_dashboard)
        self.assertNotIn('cluster=\\"$cluster\\"', rendered_dashboard)

        provenance = dashboard_resource["metadata"]["annotations"]
        self.assertEqual("5f69de628466706e76d71ce2ba588d40530d5818", provenance["observability.home/mixin-revision"])
        self.assertEqual("7ab65dc8b90f7a6751d88f18bbb4e1bee33bf334", provenance["observability.home/source-revision"])
        canonical = json.dumps(dashboard, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), provenance["observability.home/content-sha256"])

        platform = yaml.safe_load((APP / "prometheusrule.yaml").read_text())
        rules = [rule for group in platform["spec"]["groups"] for rule in group["rules"] if rule.get("alert") == "FluxReconciliationFailure"]
        self.assertEqual(1, len(rules))
        rule = rules[0]
        self.assertEqual('gotk_resource_info{ready!="True"} == 1', rule["expr"])
        self.assertEqual("10m", rule["for"])
        self.assertEqual("critical", rule["labels"]["severity"])
        self.assertTrue(rule["annotations"]["runbook_url"])
        platform_alerts = [rule["alert"] for group in platform["spec"]["groups"] for rule in group["rules"] if "alert" in rule]
        self.assertNotIn("FluxReconcilationFailed", platform_alerts)
        self.assertNotIn("FluxReconciliationFailed", platform_alerts)

        generator = ROOT / "scripts/generate-flux-mixin.py"
        self.assertTrue(generator.exists())
        self.assertIn("python3 ./scripts/generate-flux-mixin.py --check", (ROOT / "scripts/kubeconform.sh").read_text())

    def test_flux_cluster_inventory_covers_current_source_kinds(self):
        release = yaml.safe_load((APP / "helmrelease.yaml").read_text())
        kube_state_metrics = release["spec"]["values"]["kube-state-metrics"]
        resources = kube_state_metrics["customResourceState"]["config"]["spec"]["resources"]
        flux_kinds = {
            item["groupVersionKind"]["kind"]
            for item in resources
            if item["groupVersionKind"]["group"].endswith("toolkit.fluxcd.io")
        }
        self.assertEqual(
            {"Kustomization", "HelmRelease", "GitRepository", "HelmRepository", "OCIRepository", "Bucket"},
            flux_kinds,
        )
        source_rules = [rule for rule in kube_state_metrics["rbac"]["extraRules"] if rule["apiGroups"] == ["source.toolkit.fluxcd.io"]]
        self.assertEqual(1, len(source_rules))
        self.assertEqual({"buckets", "gitrepositories", "helmrepositories", "ocirepositories"}, set(source_rules[0]["resources"]))
        for item in resources:
            if item["groupVersionKind"]["kind"] in {"HelmRepository", "OCIRepository", "Bucket"}:
                labels = item["metrics"][0]["each"].get("labelsFromPath", {}) | item["metrics"][0].get("labelsFromPath", {})
                self.assertNotIn("revision", labels)

    def test_resources_and_ci_are_wired(self):
        resources = yaml.safe_load((APP / "kustomization.yaml").read_text())["resources"]
        self.assertIn("./flux-podmonitor.yaml", resources)
        self.assertIn("./grafana-dashboard-flux-cluster.yaml", resources)
        self.assertIn("./grafana-dashboard-flux-control-plane.yaml", resources)
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("python3 ./scripts/test-flux-monitoring.py", canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
