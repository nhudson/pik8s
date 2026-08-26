#!/usr/bin/env python3
"""Security and observability contracts for the media Exportarr deployment."""
from __future__ import annotations

import json
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/media/exportarr/app"
MONITORING_APP = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/app"
IMAGE = "ghcr.io/onedr0p/exportarr:v2.3.0@sha256:af535d94061cf97a52e1661945ffba78c03f9443eae7c0da1a80a5a4be56b520"
EXPORTERS = {
    "sonarr": (9707, "http://sonarr.media.svc.cluster.local:8989", "sonarr-secret", "APIKEY"),
    "radarr": (9708, "http://radarr.media.svc.cluster.local:7878", "radarr-secret", "APIKEY"),
    "prowlarr": (9709, "http://prowlarr.media.svc.cluster.local:9696", "prowlarr-secret", "APIKEY"),
    "sabnzbd": (9710, "http://sabnzbd.media.svc.cluster.local:8080", "sab-secret", "SABNZBD__API_KEY"),
}


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


class MediaExportarrTests(unittest.TestCase):
    def test_single_hardened_deployment_runs_four_exporters(self):
        deployment = load(APP / "deployment.yaml")
        self.assertEqual("Deployment", deployment["kind"])
        self.assertEqual(1, deployment["spec"]["replicas"])
        pod = deployment["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual({"type": "RuntimeDefault"}, pod["securityContext"]["seccompProfile"])
        containers = {container["name"]: container for container in pod["containers"]}
        self.assertEqual(set(EXPORTERS), set(containers))
        for name, (port, url, secret_name, secret_key) in EXPORTERS.items():
            container = containers[name]
            self.assertEqual(IMAGE, container["image"])
            self.assertEqual([name], container["args"])
            env = {item["name"]: item for item in container["env"]}
            self.assertEqual(str(port), env["PORT"]["value"])
            self.assertEqual(url, env["URL"]["value"])
            self.assertEqual(
                {"name": secret_name, "key": secret_key},
                env["APIKEY"]["valueFrom"]["secretKeyRef"],
            )
            self.assertEqual(port, container["ports"][0]["containerPort"])
            for probe in ("livenessProbe", "readinessProbe"):
                self.assertEqual("/healthz", container[probe]["httpGet"]["path"])
            security = container["securityContext"]
            self.assertFalse(security["allowPrivilegeEscalation"])
            self.assertTrue(security["readOnlyRootFilesystem"])
            self.assertTrue(security["runAsNonRoot"])
            self.assertEqual(65532, security["runAsUser"])
            self.assertEqual(["ALL"], security["capabilities"]["drop"])
            self.assertEqual({"cpu", "memory"}, set(container["resources"]["requests"]))
            self.assertEqual({"cpu", "memory"}, set(container["resources"]["limits"]))

    def test_clusterip_service_and_monitor_scrape_every_exporter_each_minute(self):
        service = load(APP / "service.yaml")
        self.assertEqual("ClusterIP", service["spec"]["type"])
        self.assertNotEqual("None", service["spec"].get("clusterIP"))
        self.assertEqual(set(EXPORTERS), {port["name"] for port in service["spec"]["ports"]})
        monitor = load(APP / "servicemonitor.yaml")
        self.assertEqual("ServiceMonitor", monitor["kind"])
        self.assertEqual("monitoring", monitor["metadata"]["namespace"])
        self.assertEqual(["media"], monitor["spec"]["namespaceSelector"]["matchNames"])
        endpoints = {endpoint["port"]: endpoint for endpoint in monitor["spec"]["endpoints"]}
        self.assertEqual(set(EXPORTERS), set(endpoints))
        for endpoint in endpoints.values():
            self.assertEqual("60s", endpoint["interval"])
            self.assertEqual("/metrics", endpoint["path"])

    def test_network_policies_allow_only_prometheus_dns_and_media_targets(self):
        policies = list(yaml.safe_load_all((APP / "networkpolicy.yaml").read_text()))
        self.assertEqual({"exportarr-ingress", "exportarr-egress"}, {p["metadata"]["name"] for p in policies})
        ingress = next(p for p in policies if p["metadata"]["name"] == "exportarr-ingress")
        egress = next(p for p in policies if p["metadata"]["name"] == "exportarr-egress")
        self.assertEqual(["Ingress"], ingress["spec"]["policyTypes"])
        self.assertEqual(["Egress"], egress["spec"]["policyTypes"])
        self.assertNotIn("ipBlock", json.dumps(policies))
        encoded = json.dumps(policies)
        for required in ("monitoring", "kube-system", "kube-dns", "sonarr", "radarr", "prowlarr", "sabnzbd"):
            self.assertIn(required, encoded)
        for port in (53, 8989, 7878, 9696, 8080):
            self.assertIn(f'"port": {port}', encoded)

    def test_flux_wiring_has_no_gateway_and_canonical_validation(self):
        app_resources = load(APP / "kustomization.yaml")["resources"]
        self.assertEqual(
            {"./deployment.yaml", "./service.yaml", "./servicemonitor.yaml", "./networkpolicy.yaml"},
            set(app_resources),
        )
        media_resources = load(ROOT / "kubernetes/apps/media/kustomization.yaml")["resources"]
        self.assertIn("./exportarr/ks.yaml", media_resources)
        all_text = "\n".join(path.read_text() for path in APP.glob("*.yaml"))
        self.assertNotIn("Gateway", all_text)
        self.assertNotIn("HTTPRoute", all_text)
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("python3 ./scripts/test-media-exportarr.py", canonical)

    def test_generated_dashboard_and_provenance_cover_exportarr(self):
        resource = load(MONITORING_APP / "grafana-dashboard-media.yaml")
        payload = json.loads(resource["data"]["media.json"])
        self.assertEqual("platform-media", payload["uid"])
        self.assertFalse(payload["editable"])
        expressions = "\n".join(target["expr"] for panel in payload["panels"] for target in panel.get("targets", []))
        self.assertIn('max by (endpoint) (up{job="exportarr"})', expressions)
        self.assertNotIn('sum by (endpoint) (up{job="exportarr"})', expressions)
        for metric in ("sonarr_system_status", "radarr_system_status", "prowlarr_system_status", "sabnzbd_status", "sabnzbd_queue_length"):
            self.assertIn(metric, expressions)
        for expression in expressions.splitlines():
            self.assertIn('job="exportarr"', expression)
        resources = load(MONITORING_APP / "kustomization.yaml")["resources"]
        self.assertIn("./grafana-dashboard-media.yaml", resources)
        provenance = (ROOT / "docs/runbooks/monitoring/dashboard-sources.md").read_text()
        for value in ("Exportarr", "v2.3.0", "367f6031dfefeba87b88be55f5780267cb143975", "MIT"):
            self.assertIn(value, provenance)
        completed = subprocess.run(
            ["python3", str(ROOT / "scripts/generate-observability-dashboards.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
