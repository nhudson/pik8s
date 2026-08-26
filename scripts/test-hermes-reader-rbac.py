#!/usr/bin/env python3
"""Policy tests for the GitOps-managed Hermes reader RBAC."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE_PATH = ROOT / "kubernetes/apps/security/hermes-reader/clusterrole.json"
BINDING_PATH = ROOT / "kubernetes/apps/security/hermes-reader/clusterrolebinding.json"
READ_VERBS = {"get", "list", "watch"}

EXPECTED_RESOURCES = {
    "": {
        "events",
        "namespaces",
        "nodes",
        "persistentvolumeclaims",
        "persistentvolumes",
        "pods",
        "services",
    },
    "apps": {"daemonsets", "deployments", "replicasets", "statefulsets"},
    "batch": {"cronjobs", "jobs"},
    "metrics.k8s.io": {"nodes", "pods"},
    "source.toolkit.fluxcd.io": {
        "buckets",
        "gitrepositories",
        "helmcharts",
        "helmrepositories",
        "ocirepositories",
    },
    "kustomize.toolkit.fluxcd.io": {"kustomizations"},
    "helm.toolkit.fluxcd.io": {"helmreleases"},
    "notification.toolkit.fluxcd.io": {"alerts", "providers", "receivers"},
    "image.toolkit.fluxcd.io": {
        "imagepolicies",
        "imagerepositories",
        "imageupdateautomations",
    },
    "gateway.networking.k8s.io": {
        "backendtlspolicies",
        "gatewayclasses",
        "gateways",
        "grpcroutes",
        "httproutes",
        "referencegrants",
        "tcproutes",
        "tlsroutes",
        "udproutes",
    },
    "cert-manager.io": {"certificates", "certificaterequests", "clusterissuers", "issuers"},
    "acme.cert-manager.io": {"challenges", "orders"},
    "postgresql.cnpg.io": {"backups", "clusters", "scheduledbackups"},
    "upgrade.cattle.io": {"plans"},
    "external-secrets.io": {"clustersecretstores", "externalsecrets"},
    "tailscale.com": {"connectors", "proxyclasses", "proxygroups"},
    "monitoring.coreos.com": {"alertmanagers", "podmonitors", "prometheuses", "prometheusrules", "servicemonitors"},
}

DENIED = [
    ("", "secrets", "get"),
    ("", "configmaps", "get"),
    ("", "pods/log", "get"),
    ("", "pods", "create"),
    ("", "pods", "update"),
    ("", "pods", "patch"),
    ("", "pods", "delete"),
    ("", "pods/exec", "create"),
    ("", "pods/attach", "create"),
    ("", "pods/portforward", "create"),
    ("", "serviceaccounts/token", "create"),
    ("rbac.authorization.k8s.io", "roles", "get"),
    ("rbac.authorization.k8s.io", "clusterroles", "get"),
    ("admissionregistration.k8s.io", "validatingwebhookconfigurations", "get"),
    ("", "users", "impersonate"),
    ("", "groups", "impersonate"),
    ("", "serviceaccounts", "impersonate"),
]


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def can_i(rules: list[dict], api_group: str, resource: str, verb: str) -> bool:
    return any(
        (api_group in rule["apiGroups"] or "*" in rule["apiGroups"])
        and (resource in rule["resources"] or "*" in rule["resources"])
        and (verb in rule["verbs"] or "*" in rule["verbs"])
        for rule in rules
    )


def main() -> None:
    role = load_json(ROLE_PATH)
    binding = load_json(BINDING_PATH)
    assert role["apiVersion"] == "rbac.authorization.k8s.io/v1"
    assert role["kind"] == "ClusterRole"
    assert role["metadata"]["name"] == "hermes-reader"
    assert binding["kind"] == "ClusterRoleBinding"
    assert binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "hermes-reader",
    }
    assert binding["subjects"] == [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group", "name": "hermes-readers"}]

    rules = role["rules"]
    for rule in rules:
        assert set(rule) == {"apiGroups", "resources", "verbs"}, rule
        assert "*" not in rule["apiGroups"], rule
        assert "*" not in rule["resources"], rule
        assert set(rule["verbs"]) == READ_VERBS, rule

    actual = {
        api_group: {resource for rule in rules if api_group in rule["apiGroups"] for resource in rule["resources"]}
        for api_group in {group for rule in rules for group in rule["apiGroups"]}
    }
    assert actual == EXPECTED_RESOURCES, f"unexpected permission surface: {actual!r}"

    positive_count = 0
    for api_group, resources in EXPECTED_RESOURCES.items():
        for resource in resources:
            for verb in READ_VERBS:
                assert can_i(rules, api_group, resource, verb), f"expected yes: {verb} {resource}.{api_group}"
                positive_count += 1

    for api_group, resource, verb in DENIED:
        assert not can_i(rules, api_group, resource, verb), f"expected no: {verb} {resource}.{api_group}"

    print(f"PASS: {positive_count} positive and {len(DENIED)} negative can-i-equivalent checks")


if __name__ == "__main__":
    main()
