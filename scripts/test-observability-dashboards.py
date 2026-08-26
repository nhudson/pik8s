#!/usr/bin/env python3
"""Contracts for the Git-owned component dashboard pack."""
from __future__ import annotations

import json
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/app"
EXPECTED = {
    "grafana-dashboard-database.yaml": ("platform-database", {"cnpg_collector_up", "cnpg_pg_replication_lag", "cnpg_pg_database_size_bytes", "cnpg_collector_last_available_backup_timestamp"}),
    "grafana-dashboard-network.yaml": ("platform-network", {"cilium_drop_count_total", "cilium_endpoint_state", "hubble_flows_processed_total", "hubble_lost_events_total"}),
    "grafana-dashboard-control-plane.yaml": ("platform-control-plane", {"certmanager_certificate_expiration_timestamp_seconds", "externalsecret_sync_calls_error", "external_dns_source_errors_total", "cloudflared_tunnel_ha_connections", "reloader_reload_executed_total"}),
    "grafana-dashboard-delivery.yaml": ("platform-alert-delivery", {"ALERTS", "alertmanager_notifications_total", "alertmanager_notifications_failed_total"}),
}


class ObservabilityDashboardTests(unittest.TestCase):
    def test_generated_dashboards_are_valid_owned_and_query_expected_metrics(self):
        for filename, (uid, metrics) in EXPECTED.items():
            resource = yaml.safe_load((APP / filename).read_text())
            self.assertEqual("ConfigMap", resource["kind"])
            self.assertEqual("1", resource["metadata"]["labels"]["grafana_dashboard"])
            payload = json.loads(next(iter(resource["data"].values())))
            self.assertEqual(uid, payload["uid"])
            self.assertFalse(payload["editable"])
            self.assertEqual("1m", payload["refresh"])
            self.assertEqual(len(payload["panels"]), len({panel["id"] for panel in payload["panels"]}))
            expressions = "\n".join(target["expr"] for panel in payload["panels"] for target in panel.get("targets", []))
            for metric in metrics:
                self.assertIn(metric, expressions)
            for panel in payload["panels"]:
                self.assertEqual("prometheus", panel["datasource"]["uid"])

    def test_generator_reports_no_drift(self):
        completed = subprocess.run(
            ["python3", str(ROOT / "scripts/generate-observability-dashboards.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_kustomization_and_canonical_validation_include_pack(self):
        resources = yaml.safe_load((APP / "kustomization.yaml").read_text())["resources"]
        for filename in EXPECTED:
            self.assertIn("./" + filename, resources)
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("python3 ./scripts/test-observability-dashboards.py", canonical)

    def test_provenance_is_documented(self):
        provenance = (ROOT / "docs/runbooks/monitoring/dashboard-sources.md").read_text()
        for component in ("CloudNativePG", "Cilium", "Hubble", "cert-manager", "External Secrets", "external-dns", "cloudflared", "Reloader", "Alertmanager"):
            self.assertIn(component, provenance)


if __name__ == "__main__":
    unittest.main(verbosity=2)
