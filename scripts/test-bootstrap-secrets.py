#!/usr/bin/env python3
"""Contract tests for value-safe bootstrap Secret recovery."""
from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import unittest
from unittest import mock
import yaml

MODULE_PATH = pathlib.Path(__file__).with_name("bootstrap-secrets.py")
ROOT = MODULE_PATH.parent.parent
spec = importlib.util.spec_from_file_location("bootstrap_secrets", MODULE_PATH)
assert spec and spec.loader
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

EXPECTED = {
    "cluster-secrets": {
        "namespace": "flux-system",
        "secret": "cluster-secrets",
        "keys": ["SECRET_ACME_EMAIL", "SECRET_CLOUDFLARE_ACCOUNT_ID", "SECRET_CLOUDFLARE_TUNNEL_ID", "SECRET_DOMAIN"],
    },
    "tailscale-settings": {
        "namespace": "flux-system",
        "secret": "tailscale-settings",
        "keys": ["SECRET_INFRASTRUCTURE_CIDR"],
    },
    "external-secrets-bootstrap-token": {
        "namespace": "security",
        "secret": "onepassword-token",
        "keys": ["token"],
    },
}


class FakeRunner:
    def __init__(self, live: bool):
        self.items = {
            item: {key: f"value-{index}-{key}".encode() for key in contract["keys"]}
            for index, (item, contract) in enumerate(EXPECTED.items(), start=1)
        }
        self.secrets = {}
        self.namespaces = []
        self.applied = []
        if live:
            for item, contract in EXPECTED.items():
                self.secrets[(contract["namespace"], contract["secret"])] = bootstrap.build_secret(contract, self.items[item])

    def item_values(self, item, keys):
        return self.items[item]

    def get_secret(self, namespace, name):
        return self.secrets.get((namespace, name))

    def ensure_namespace(self, namespace):
        self.namespaces.append(namespace)

    def apply_secret(self, secret):
        metadata = secret["metadata"]
        self.applied.append(secret)
        self.secrets[(metadata["namespace"], metadata["name"])] = secret


class BootstrapSecretTests(unittest.TestCase):
    def test_contracts_are_exact(self):
        actual = {
            contract["item"]: {
                "namespace": contract["namespace"],
                "secret": contract["secret"],
                "keys": list(contract["keys"]),
            }
            for contract in bootstrap.CONTRACTS
        }
        self.assertEqual(EXPECTED, actual)

    def test_secret_shape_is_prune_guarded_and_value_safe(self):
        contract = bootstrap.CONTRACTS[0]
        values = {key: f"private-{key}".encode() for key in contract["keys"]}
        secret = bootstrap.build_secret(contract, values)
        self.assertEqual("disabled", secret["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"])
        self.assertEqual(set(values), set(secret["data"]))
        self.assertTrue(all(secret["data"][key] == base64.b64encode(values[key]).decode() for key in values))
        self.assertNotIn("stringData", secret)

    def test_check_requires_exact_live_key_and_value_equality(self):
        runner = FakeRunner(live=True)
        summary = bootstrap.execute("check", runner)
        self.assertEqual(3, summary["resources"])
        self.assertEqual(3, summary["live_exists"])
        self.assertTrue(summary["all_keysets_equal"])
        self.assertTrue(summary["all_values_equal"])
        self.assertTrue(summary["all_prune_guarded"])
        self.assertEqual([], runner.applied)

    def test_apply_is_idempotent_and_uses_stdin_manifests(self):
        runner = FakeRunner(live=False)
        summary = bootstrap.execute("apply", runner)
        self.assertEqual(3, summary["resources"])
        self.assertEqual(3, summary["applied"])
        self.assertEqual({"flux-system", "security"}, set(runner.namespaces))
        self.assertEqual(3, len(runner.applied))
        self.assertTrue(summary["all_keysets_equal"])
        self.assertTrue(summary["all_values_equal"])
        self.assertTrue(summary["all_prune_guarded"])
        second = bootstrap.execute("apply", runner)
        self.assertEqual(3, second["applied"])
        self.assertEqual(3, len(runner.secrets))

    def test_provider_contract_rejects_missing_or_extra_fields(self):
        runner = FakeRunner(live=True)
        runner.items["cluster-secrets"].pop("SECRET_DOMAIN")
        with self.assertRaises(RuntimeError):
            bootstrap.execute("check", runner)
        runner = FakeRunner(live=True)
        runner.items["cluster-secrets"]["unexpected"] = b"value"
        with self.assertRaises(RuntimeError):
            bootstrap.execute("check", runner)

    def test_repository_bootstrap_wiring_uses_recovery_helper(self):
        taskfile = (ROOT / ".taskfiles/Flux/Taskfile.yaml").read_text()
        self.assertIn("bootstrap-secrets.py apply", taskfile)
        self.assertNotIn("sops --decrypt {{.CLUSTER_SECRET_SOPS_FILE}}", taskfile)
        self.assertLess(taskfile.index("bootstrap-secrets.py apply"), taskfile.index("/flux/config"))

        root_resources = yaml.safe_load((ROOT / "kubernetes/flux/vars/kustomization.yaml").read_text())["resources"]
        self.assertEqual(["./cluster-settings.yaml"], root_resources)
        provider_resources = yaml.safe_load((ROOT / "kubernetes/apps/security/external-secrets/app/kustomization.yaml").read_text())["resources"]
        self.assertEqual(["./helmrelease.yaml"], provider_resources)

        security_namespaces = [
            document["metadata"]["name"]
            for document in yaml.safe_load_all((ROOT / "kubernetes/apps/security/namespace.yaml").read_text())
            if document
        ]
        self.assertEqual(["security"], security_namespaces)

        documents = list(yaml.safe_load_all((ROOT / "kubernetes/apps/security/external-secrets/ks.yaml").read_text()))
        store = next(document for document in documents if document["metadata"]["name"] == "external-secrets-cluster-secret-store")
        self.assertEqual([{"name": "external-secrets"}], store["spec"]["dependsOn"])

    def test_command_runner_scopes_recovery_token_to_op_only(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args[0], kwargs["env"]))
            if args[0] == "op":
                fields = [{"label": key, "value": "value", "type": "CONCEALED"} for key in EXPECTED["cluster-secrets"]["keys"]]
                return bootstrap.subprocess.CompletedProcess(args, 0, json.dumps({"fields": fields}).encode(), b"")
            return bootstrap.subprocess.CompletedProcess(args, 0, b"", b"")

        runner = bootstrap.CommandRunner(kubeconfig="test", vault="test", token="recovery-token")
        with mock.patch.object(bootstrap.subprocess, "run", side_effect=fake_run):
            runner.item_values("cluster-secrets", tuple(EXPECTED["cluster-secrets"]["keys"]))
            self.assertIsNone(runner.get_secret("flux-system", "missing"))
        op_env = next(env for command, env in calls if command == "op")
        kubectl_env = next(env for command, env in calls if command == "kubectl")
        self.assertEqual("recovery-token", op_env["OP_SERVICE_ACCOUNT_TOKEN"])
        self.assertNotIn("OP_SERVICE_ACCOUNT_TOKEN", kubectl_env)

    def test_command_runner_rejects_unexpected_concealed_provider_field(self):
        keys = tuple(EXPECTED["tailscale-settings"]["keys"])
        fields = [
            {"label": keys[0], "value": "value", "type": "CONCEALED"},
            {"label": "unexpected", "value": "value", "type": "CONCEALED"},
        ]
        completed = bootstrap.subprocess.CompletedProcess(["op"], 0, json.dumps({"fields": fields}).encode(), b"")
        runner = bootstrap.CommandRunner(kubeconfig="test", vault="test", token="recovery-token")
        with mock.patch.object(bootstrap.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError):
                runner.item_values("tailscale-settings", keys)

    def test_command_runner_rejects_duplicate_concealed_provider_field(self):
        key = EXPECTED["tailscale-settings"]["keys"][0]
        fields = [
            {"label": key, "value": "first", "type": "CONCEALED"},
            {"label": key, "value": "second", "type": "CONCEALED"},
        ]
        completed = bootstrap.subprocess.CompletedProcess(["op"], 0, json.dumps({"fields": fields}).encode(), b"")
        runner = bootstrap.CommandRunner(kubeconfig="test", vault="test", token="recovery-token")
        with mock.patch.object(bootstrap.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError):
                runner.item_values("tailscale-settings", (key,))

    def test_get_secret_distinguishes_not_found_from_command_failure(self):
        runner = bootstrap.CommandRunner(kubeconfig="test", vault="test", token="recovery-token")
        missing = bootstrap.subprocess.CompletedProcess(["kubectl"], 0, b"", b"")
        with mock.patch.object(bootstrap.subprocess, "run", return_value=missing):
            self.assertIsNone(runner.get_secret("flux-system", "missing"))
        failed = bootstrap.subprocess.CompletedProcess(["kubectl"], 1, b"", b"")
        with mock.patch.object(bootstrap.subprocess, "run", return_value=failed):
            with self.assertRaises(RuntimeError):
                runner.get_secret("flux-system", "failed")

    def test_secret_apply_forces_narrow_field_ownership(self):
        calls = []
        runner = bootstrap.CommandRunner(kubeconfig="test", vault="test", token="recovery-token")
        runner.kubectl = lambda args, input_obj=None, check=True: calls.append((args, input_obj))
        contract = bootstrap.CONTRACTS[1]
        values = {key: b"rotated" for key in contract["keys"]}
        runner.apply_secret(bootstrap.build_secret(contract, values))
        self.assertIn("--force-conflicts", calls[0][0])
        self.assertEqual("Secret", calls[0][1]["kind"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
