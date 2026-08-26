#!/usr/bin/env python3
"""Contracts for the stateless, Git-owned Grafana deployment."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/app"
CREDENTIALS = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/credentials"


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


class GrafanaStackTests(unittest.TestCase):
    def test_grafana_is_stateless_bounded_and_authenticated(self):
        values = load(APP / "helmrelease.yaml")["spec"]["values"]["grafana"]
        self.assertTrue(values["enabled"])
        self.assertEqual(1, values["replicas"])
        self.assertFalse(values["persistence"]["enabled"])
        self.assertEqual({"enabled": True, "sizeLimit": "256Mi"}, values["persistence"]["inMemory"])
        self.assertFalse(values["initChownData"]["enabled"])
        self.assertEqual("grafana-admin", values["admin"]["existingSecret"])
        self.assertEqual("admin-user", values["admin"]["userKey"])
        self.assertEqual("admin-password", values["admin"]["passwordKey"])
        self.assertEqual([], values["plugins"])
        self.assertEqual("grafana-admin", values["annotations"]["secret.reloader.stakater.com/reload"])
        self.assertFalse(values["enableServiceLinks"])
        self.assertTrue(values["automountServiceAccountToken"])
        self.assertTrue(values["serviceAccount"]["automountServiceAccountToken"])
        self.assertTrue(values["rbac"]["namespaced"])
        self.assertFalse(values["rbac"]["create"])
        self.assertEqual(["monitoring"], values["rbac"]["namespaces"])
        self.assertEqual("1Gi", values["resources"]["limits"]["memory"])
        self.assertEqual("512Mi", values["resources"]["limits"]["ephemeral-storage"])

    def test_grafana_security_and_telemetry_defaults_are_private(self):
        values = load(APP / "helmrelease.yaml")["spec"]["values"]["grafana"]
        ini = values["grafana.ini"]
        self.assertFalse(ini["auth.anonymous"]["enabled"])
        self.assertFalse(ini["users"]["allow_sign_up"])
        self.assertFalse(ini["users"]["allow_org_create"])
        self.assertFalse(ini["analytics"]["reporting_enabled"])
        self.assertFalse(ini["analytics"]["check_for_updates"])
        self.assertFalse(ini["analytics"]["check_for_plugin_updates"])
        self.assertFalse(ini["news"]["news_feed_enabled"])
        self.assertTrue(ini["security"]["cookie_secure"])
        self.assertTrue(ini["security"]["strict_transport_security"])
        self.assertEqual("31536000", ini["security"]["strict_transport_security_max_age_seconds"])
        self.assertFalse(ini["server"]["enforce_domain"])
        self.assertEqual("https://grafana.${SECRET_DOMAIN}", ini["server"]["root_url"])

    def test_dashboards_and_prometheus_datasource_are_chart_owned(self):
        values = load(APP / "helmrelease.yaml")["spec"]["values"]["grafana"]
        self.assertTrue(values["defaultDashboardsEnabled"])
        self.assertFalse(values["forceDeployDatasources"])
        self.assertFalse(values["forceDeployDashboards"])
        self.assertFalse(values["defaultDashboardsEditable"])
        self.assertTrue(values["sidecar"]["dashboards"]["enabled"])
        self.assertEqual("monitoring", values["sidecar"]["dashboards"]["searchNamespace"])
        self.assertEqual("configmap", values["sidecar"]["dashboards"]["resource"])
        self.assertEqual("64Mi", values["sidecar"]["dashboards"]["sizeLimit"])
        self.assertFalse(values["sidecar"]["dashboards"]["provider"]["allowUiUpdates"])
        self.assertTrue(values["sidecar"]["datasources"]["enabled"])
        self.assertTrue(values["sidecar"]["datasources"]["defaultDatasourceEnabled"])
        self.assertTrue(values["sidecar"]["datasources"]["isDefaultDatasource"])
        self.assertEqual("prometheus", values["sidecar"]["datasources"]["uid"])
        self.assertEqual("POST", values["sidecar"]["datasources"]["httpMethod"])
        self.assertEqual("60s", values["sidecar"]["datasources"]["defaultDatasourceScrapeInterval"])
        self.assertEqual("monitoring", values["sidecar"]["datasources"]["searchNamespace"])
        self.assertEqual("configmap", values["sidecar"]["datasources"]["resource"])

        dashboard = load(APP / "grafana-dashboard-platform.yaml")
        self.assertEqual("1", dashboard["metadata"]["labels"]["grafana_dashboard"])
        payload = json.loads(dashboard["data"]["platform-overview.json"])
        self.assertEqual("platform-overview", payload["uid"])
        self.assertFalse(payload["editable"])
        expressions = "\n".join(
            target["expr"]
            for panel in payload["panels"]
            for target in panel.get("targets", [])
            if "expr" in target
        )
        for metric in ("ALERTS", "gotk_resource_info", "external_secret_info", "tailscale_resource_info", "cnpg_collector_last_available_backup_timestamp"):
            self.assertIn(metric, expressions)

    def test_admin_credentials_are_external_and_narrow(self):
        external = load(CREDENTIALS / "externalsecret-grafana.yaml")
        self.assertEqual("1password", external["spec"]["secretStoreRef"]["name"])
        self.assertEqual("ClusterSecretStore", external["spec"]["secretStoreRef"]["kind"])
        self.assertEqual("grafana-admin", external["spec"]["target"]["name"])
        self.assertEqual("Owner", external["spec"]["target"]["creationPolicy"])
        self.assertEqual("Retain", external["spec"]["target"]["deletionPolicy"])
        self.assertEqual({"admin-user", "admin-password"}, set(external["spec"]["target"]["template"]["data"]))
        self.assertEqual([{"extract": {"key": "grafana-admin"}}], external["spec"]["dataFrom"])
        resources = load(CREDENTIALS / "kustomization.yaml")["resources"]
        self.assertIn("./externalsecret-grafana.yaml", resources)

    def test_only_internal_gateway_exposes_grafana(self):
        route = load(APP / "grafana-httproute.yaml")
        self.assertEqual(["grafana.${SECRET_DOMAIN}"], route["spec"]["hostnames"])
        self.assertEqual([{"name": "internal", "namespace": "network"}], route["spec"]["parentRefs"])
        backend = route["spec"]["rules"][0]["backendRefs"][0]
        self.assertEqual("kube-prometheus-stack-grafana", backend["name"])
        self.assertEqual(80, backend["port"])
        resources = load(APP / "kustomization.yaml")["resources"]
        self.assertIn("./grafana-httproute.yaml", resources)
        self.assertIn("./grafana-dashboard-platform.yaml", resources)

    def test_sidecars_can_read_only_monitoring_configmaps(self):
        documents = [doc for doc in yaml.safe_load_all((APP / "grafana-rbac.yaml").read_text()) if doc]
        role = next(doc for doc in documents if doc["kind"] == "Role")
        binding = next(doc for doc in documents if doc["kind"] == "RoleBinding")
        self.assertEqual(
            [{"apiGroups": [""], "resources": ["configmaps"], "verbs": ["get", "list", "watch"]}],
            role["rules"],
        )
        self.assertEqual("kube-prometheus-stack-grafana", binding["roleRef"]["name"])
        self.assertEqual("kube-prometheus-stack-grafana", binding["subjects"][0]["name"])
        self.assertEqual("monitoring", binding["subjects"][0]["namespace"])
        resources = load(APP / "kustomization.yaml")["resources"]
        self.assertIn("./grafana-rbac.yaml", resources)

    def test_public_artifacts_have_no_private_literals(self):
        patterns = {
            "private IPv4": re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?:/\d{1,2})?\b"),
            "home path": re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+"),
            "personal email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
        }
        paths = [
            APP / "helmrelease.yaml",
            APP / "grafana-httproute.yaml",
            APP / "grafana-dashboard-platform.yaml",
            APP / "grafana-rbac.yaml",
            CREDENTIALS / "externalsecret-grafana.yaml",
            ROOT / "docs/runbooks/monitoring/grafana.md",
        ]
        for path in paths:
            text = path.read_text()
            for label, pattern in patterns.items():
                self.assertIsNone(pattern.search(text), f"{label} in {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
