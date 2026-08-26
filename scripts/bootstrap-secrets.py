#!/usr/bin/env python3
"""Restore bootstrap-only Kubernetes Secrets from 1Password without value output."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import subprocess
from typing import Any

PRUNE_ANNOTATION = "kustomize.toolkit.fluxcd.io/prune"
CONTRACTS = (
    {
        "item": "cluster-secrets",
        "namespace": "flux-system",
        "secret": "cluster-secrets",
        "keys": ("SECRET_ACME_EMAIL", "SECRET_CLOUDFLARE_ACCOUNT_ID", "SECRET_CLOUDFLARE_TUNNEL_ID", "SECRET_DOMAIN"),
    },
    {
        "item": "tailscale-settings",
        "namespace": "flux-system",
        "secret": "tailscale-settings",
        "keys": ("SECRET_INFRASTRUCTURE_CIDR",),
    },
    {
        "item": "external-secrets-bootstrap-token",
        "namespace": "security",
        "secret": "onepassword-token",
        "keys": ("token",),
    },
)


def digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def build_secret(contract: dict[str, Any], values: dict[str, bytes]) -> dict[str, Any]:
    expected = set(contract["keys"])
    if set(values) != expected:
        raise RuntimeError("provider item key set differs from bootstrap contract")
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": contract["secret"],
            "namespace": contract["namespace"],
            "annotations": {PRUNE_ANNOTATION: "disabled"},
        },
        "type": "Opaque",
        "data": {key: base64.b64encode(values[key]).decode("ascii") for key in contract["keys"]},
    }


def compare_secret(secret: dict[str, Any] | None, values: dict[str, bytes]) -> tuple[bool, bool, bool, bool]:
    if secret is None:
        return False, False, False, False
    encoded = secret.get("data") or {}
    keysets_equal = set(encoded) == set(values)
    try:
        values_equal = keysets_equal and all(
            digest(base64.b64decode(encoded[key], validate=True)) == digest(values[key]) for key in values
        )
    except (ValueError, TypeError):
        values_equal = False
    guarded = (secret.get("metadata") or {}).get("annotations", {}).get(PRUNE_ANNOTATION) == "disabled"
    return True, keysets_equal, values_equal, guarded


def execute(mode: str, runner: Any) -> dict[str, Any]:
    if mode not in {"check", "apply"}:
        raise ValueError("mode must be check or apply")
    plans = []
    for contract in CONTRACTS:
        values = runner.item_values(contract["item"], contract["keys"])
        if set(values) != set(contract["keys"]):
            raise RuntimeError("provider item key set differs from bootstrap contract")
        if any(not values[key] for key in contract["keys"]):
            raise RuntimeError("provider item contains an empty bootstrap field")
        plans.append((contract, values))

    if mode == "apply":
        for namespace in sorted({contract["namespace"] for contract, _ in plans}):
            runner.ensure_namespace(namespace)
        for contract, values in plans:
            runner.apply_secret(build_secret(contract, values))

    results = []
    for contract, values in plans:
        live = runner.get_secret(contract["namespace"], contract["secret"])
        exists, keysets_equal, values_equal, guarded = compare_secret(live, values)
        results.append((exists, keysets_equal, values_equal, guarded))

    return {
        "resources": len(results),
        "live_exists": sum(result[0] for result in results),
        "applied": len(results) if mode == "apply" else 0,
        "all_keysets_equal": all(result[1] for result in results),
        "all_values_equal": all(result[2] for result in results),
        "all_prune_guarded": all(result[3] for result in results),
    }


class CommandRunner:
    def __init__(self, *, kubeconfig: str, vault: str, token: str):
        self.kubeconfig = kubeconfig
        self.vault = vault
        self.base_env = os.environ.copy()
        self.base_env.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        self.op_env = self.base_env.copy()
        self.op_env["OP_SERVICE_ACCOUNT_TOKEN"] = token

    def command(self, args: list[str], input_obj: dict[str, Any] | None = None, check: bool = True, env: dict[str, str] | None = None):
        raw = None if input_obj is None else json.dumps(input_obj, separators=(",", ":")).encode()
        completed = subprocess.run(args, input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env or self.base_env)
        if check and completed.returncode:
            raise RuntimeError(f"command failed: {args[0]} {args[1]}")
        return completed

    def item_values(self, item: str, keys: tuple[str, ...]) -> dict[str, bytes]:
        completed = self.command(["op", "item", "get", item, "--vault", self.vault, "--format=json", "--reveal"], env=self.op_env)
        document = json.loads(completed.stdout)
        concealed_fields = [
            field for field in document.get("fields", [])
            if field.get("type") == "CONCEALED" and not field.get("purpose")
        ]
        labels = [field.get("label") for field in concealed_fields]
        if len(labels) != len(set(labels)):
            raise RuntimeError("provider item contains duplicate concealed field labels")
        concealed = {
            field.get("label"): field.get("value", "").encode()
            for field in concealed_fields
        }
        if set(concealed) != set(keys):
            raise RuntimeError("provider item key set differs from bootstrap contract")
        return concealed

    def kubectl(self, args: list[str], input_obj: dict[str, Any] | None = None, check: bool = True):
        return self.command(["kubectl", "--kubeconfig", self.kubeconfig, *args], input_obj, check)

    def get_secret(self, namespace: str, name: str):
        completed = self.kubectl(["-n", namespace, "get", "secret", name, "--ignore-not-found", "-o", "json"], check=False)
        if completed.returncode:
            raise RuntimeError("kubectl get secret failed")
        if not completed.stdout.strip():
            return None
        return json.loads(completed.stdout)

    def ensure_namespace(self, namespace: str):
        manifest = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}
        self.kubectl(["apply", "--server-side", "--field-manager=bootstrap-secrets", "--filename=-"], manifest)

    def apply_secret(self, secret: dict[str, Any]):
        self.kubectl(["apply", "--server-side", "--force-conflicts", "--field-manager=bootstrap-secrets", "--filename=-"], secret)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply"))
    parser.add_argument("--kubeconfig", required=True)
    args = parser.parse_args()
    vault = os.environ.get("OP_VAULT", "").strip()
    if not vault:
        raise SystemExit("OP_VAULT is required")
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("1Password recovery service-account token: ").strip()
    if not token:
        raise SystemExit("1Password recovery token is required")
    summary = execute(args.mode, CommandRunner(kubeconfig=args.kubeconfig, vault=vault, token=token))
    if not summary["all_keysets_equal"] or not summary["all_values_equal"] or (args.mode == "apply" and not summary["all_prune_guarded"]):
        raise SystemExit("bootstrap Secret verification failed")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
