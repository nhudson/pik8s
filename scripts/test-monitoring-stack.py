#!/usr/bin/env python3
"""Contracts for resilient local monitoring and alert delivery."""
from __future__ import annotations

import ipaddress
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
MONITORING = ROOT / "kubernetes/apps/monitoring"
STACK = MONITORING / "kube-prometheus-stack"
APP = STACK / "app"
CREDENTIALS = STACK / "credentials"


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


def documents(path: pathlib.Path) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


class MonitoringStackTests(unittest.TestCase):
    def test_dependency_order_is_explicit(self):
        parent = load(MONITORING / "kustomization.yaml")
        self.assertEqual(
            ["./namespace.yaml", "./kube-prometheus-stack/credentials/ks.yaml", "./kube-prometheus-stack/ks.yaml"],
            parent["resources"],
        )
        credentials = load(CREDENTIALS / "ks.yaml")
        self.assertEqual("monitoring-credentials", credentials["metadata"]["name"])
        self.assertEqual([{"name": "external-secrets-cluster-secret-store"}], credentials["spec"]["dependsOn"])
        self.assertTrue(credentials["spec"]["wait"])
        stack = load(STACK / "ks.yaml")
        self.assertEqual([{"name": "monitoring-credentials"}], stack["spec"]["dependsOn"])
        self.assertTrue(stack["spec"]["wait"])

    def test_prometheus_is_bounded_ephemeral_and_local_alerting_is_ha(self):
        release = load(APP / "helmrelease.yaml")
        self.assertNotIn("csi-driver-nfs", release["spec"].get("dependsOn", []))
        values = release["spec"]["values"]
        prometheus = values["prometheus"]["prometheusSpec"]
        self.assertFalse(prometheus["enableAdminAPI"])
        self.assertEqual("48h", prometheus["retention"])
        self.assertEqual("8GB", prometheus["retentionSize"])
        self.assertEqual({"sizeLimit": "10Gi"}, prometheus["storageSpec"]["emptyDir"])
        self.assertEqual("10Gi", prometheus["resources"]["limits"]["ephemeral-storage"])
        self.assertEqual("60s", prometheus["scrapeInterval"])
        self.assertEqual("30s", prometheus["evaluationInterval"])
        self.assertIn("requests", prometheus["resources"])
        self.assertIn("limits", prometheus["resources"])
        self.assertEqual([], prometheus.get("remoteWrite", []))
        self.assertTrue(values["grafana"]["enabled"])
        alertmanager = values["alertmanager"]["alertmanagerSpec"]
        self.assertEqual(2, alertmanager["replicas"])
        self.assertTrue(alertmanager["useExistingSecret"])
        self.assertEqual("alertmanager-config", alertmanager["configSecret"])
        self.assertIn("alertmanager-config", alertmanager["secrets"])
        self.assertEqual({}, alertmanager["storage"])
        self.assertEqual({"enabled": True, "minAvailable": 1}, values["alertmanager"]["podDisruptionBudget"])

    def test_external_secrets_emit_only_required_keys(self):
        contracts = {
            "alertmanager-config": ({"alertmanager.yaml", "bot_token"}, "monitoring-alerts"),
            "grafana-admin": ({"admin-user", "admin-password"}, "grafana-admin"),
            "hermes-alert-relay": ({"webhook_url", "webhook_secret", "bearer_token"}, "monitoring-alerts"),
        }
        for path in sorted(CREDENTIALS.glob("externalsecret-*.yaml")):
            resource = load(path)
            target = resource["spec"]["target"]
            name = target["name"]
            self.assertIn(name, contracts)
            self.assertEqual("1password", resource["spec"]["secretStoreRef"]["name"])
            self.assertEqual("ClusterSecretStore", resource["spec"]["secretStoreRef"]["kind"])
            self.assertEqual("Owner", target["creationPolicy"])
            expected_keys, expected_item = contracts[name]
            self.assertEqual({expected_item}, {item["extract"]["key"] for item in resource["spec"]["dataFrom"]})
            self.assertEqual(expected_keys, set(target["template"]["data"]))
        self.assertEqual(3, len(list(CREDENTIALS.glob("externalsecret-*.yaml"))))

    def test_alertmanager_routes_to_telegram_and_authenticated_relay(self):
        resource = load(CREDENTIALS / "externalsecret-alertmanager.yaml")
        config = resource["spec"]["target"]["template"]["data"]["alertmanager.yaml"]
        self.assertIn("telegram_configs:", config)
        self.assertIn("bot_token_file:", config)
        self.assertIn("send_resolved: true", config)
        self.assertIn("webhook_configs:", config)
        self.assertIn("authorization:", config)
        self.assertIn("credentials:", config)
        self.assertIn("hermes-alert-relay.monitoring.svc.cluster.local", config)
        self.assertNotRegex(config, r"\b\d{8,}\b")
        rendered = re.sub(r"\{\{[^}]+\}\}", "1", config)
        routes = yaml.safe_load(rendered)["route"]["routes"]
        noisy_matchers = {
            'alertname="CPUThrottlingHigh"',
            'namespace="monitoring"',
            'container="grafana-sc-dashboard"',
        }
        matches = [route for route in routes if set(route.get("matchers", [])) == noisy_matchers]
        self.assertEqual(1, len(matches))
        self.assertEqual(3, len(matches[0]["matchers"]))
        self.assertEqual(matches[0], routes[0])
        self.assertEqual("discard", matches[0]["receiver"])
        self.assertFalse(matches[0].get("continue", False))

    def test_relay_is_replicated_hardened_and_network_restricted(self):
        deployment = load(APP / "relay-deployment.yaml")
        self.assertEqual("hermes-alert-relay", deployment["metadata"]["annotations"]["secret.reloader.stakater.com/reload"])
        spec = deployment["spec"]
        self.assertEqual(2, spec["replicas"])
        pod = spec["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        container = pod["containers"][0]
        self.assertRegex(container["image"], r"@sha256:[a-f0-9]{64}$")
        security = container["securityContext"]
        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertTrue(security["readOnlyRootFilesystem"])
        self.assertEqual(["ALL"], security["capabilities"]["drop"])
        self.assertIn("requests", container["resources"])
        self.assertIn("limits", container["resources"])
        policies = documents(APP / "relay-networkpolicy.yaml")
        self.assertEqual({"Ingress", "Egress"}, {policy["spec"]["policyTypes"][0] for policy in policies})
        source = load(APP / "relay-configmap.yaml")["data"]["relay.py"]
        disruption = load(APP / "relay-poddisruptionbudget.yaml")
        self.assertEqual(1, disruption["spec"]["minAvailable"])
        for required in (
            "X-Webhook-Signature-V2",
            "X-Webhook-Timestamp",
            "X-Request-ID",
            "hmac.compare_digest",
            "Content-Length",
            "1_048_576",
        ):
            self.assertIn(required, source)
        self.assertNotIn("print(body", source)
        self.assertNotIn("X-Webhook-Delivery", source)

    def test_alert_rules_have_runbooks_and_recovery_signals(self):
        alerts = []
        for path in APP.glob("prometheusrule*.yaml"):
            rules = load(path)
            alerts.extend(rule for group in rules["spec"]["groups"] for rule in group["rules"] if "alert" in rule)
        expected = {
            "FluxReconciliationFailure",
            "ExternalSecretNotReady",
            "TailscaleResourceNotReady",
            "CloudNativePGBackupStale",
            "NFSVolumeUnavailable",
            "DNSResolverUnavailable",
            "CertificateExpiringSoon",
            "CloudflareTunnelUnavailable",
            "CriticalWorkloadUnavailable",
        }
        self.assertTrue(expected <= {rule["alert"] for rule in alerts})
        for rule in alerts:
            self.assertIn(rule["labels"]["severity"], {"warning", "critical"})
            self.assertTrue(rule.get("for"))
            self.assertIn("summary", rule["annotations"])
            self.assertIn("description", rule["annotations"])
            self.assertIn("runbook_url", rule["annotations"])
            self.assertTrue(rule["annotations"]["runbook_url"].startswith("https://github.com/nhudson/pik8s/blob/main/docs/runbooks/monitoring/"))

    def test_public_files_contain_no_private_literals(self):
        private_ipv4 = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?:/\d{1,2})?\b")
        personal_email = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
        for path in [*MONITORING.rglob("*.yaml"), *MONITORING.rglob("*.md"), ROOT / "docs/runbooks/monitoring/README.md"]:
            text = path.read_text()
            self.assertIsNone(private_ipv4.search(text), path)
            self.assertIsNone(personal_email.search(text), path)
            self.assertNotIn("TELEGRAM_BOT_TOKEN", text)
            self.assertIsNone(re.search(r"chat_id:\s*[\"']?-?\d{7,}", text, re.I), path)

    def test_promtool_validation_is_required_by_ci(self):
        workflow = (ROOT / ".github/workflows/gitops-validation.yaml").read_text()
        kubeconform_workflow = (ROOT / ".github/workflows/kubeconform.yaml").read_text()
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("kustomize prometheus", workflow)
        self.assertIn("kustomize prometheus", kubeconform_workflow)
        self.assertIn("python3 ./scripts/validate-prometheus-rules.py", canonical)
        repositories = load(ROOT / "kubernetes/flux/repositories/helm/kustomization.yaml")
        self.assertIn("./prometheus-community-charts.yaml", repositories["resources"])
        flux_diff = (ROOT / ".github/workflows/flux-diff.yaml").read_text()
        self.assertIn("limit = 40_000", flux_diff)
        self.assertIn("diff truncated", flux_diff)
        receiver_contract = (ROOT / "docs/runbooks/monitoring/hermes-receiver.md").read_text()
        for requirement in ("HMAC V2", "five-minute freshness", "one-hour replay", "read-only", "untrusted evidence", "no automated remediation"):
            self.assertIn(requirement, receiver_contract)


if __name__ == "__main__":
    unittest.main(verbosity=2)
