#!/usr/bin/env python3
"""Contract tests for identity-aware API and HA subnet access."""

from __future__ import annotations

import ipaddress
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/apps/network/tailscale/app"
RBAC = ROOT / "kubernetes/apps/security/hermes-reader/clusterrolebinding.json"
ROUTE_VARIABLE = "${SECRET_INFRASTRUCTURE_CIDR}"


def load_yaml(name: str) -> dict:
    with (APP / name).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def main() -> None:
    release = load_yaml("helmrelease.yaml")
    proxy_config = release["spec"]["values"]["apiServerProxyConfig"]
    # Impersonation RBAC is required by the dedicated ProxyGroup. Keeping the
    # in-process proxy disabled prevents the operator device becoming an API endpoint.
    assert proxy_config == {"allowImpersonation": "true", "mode": "false"}

    api_proxy = load_yaml("api-proxy.yaml")
    assert api_proxy["apiVersion"] == "tailscale.com/v1alpha1"
    assert api_proxy["kind"] == "ProxyGroup"
    assert api_proxy["spec"] == {
        "type": "kube-apiserver",
        "replicas": 2,
        "tags": ["tag:k8s-api"],
        "kubeAPIServer": {"mode": "auth"},
    }

    proxy_class = load_yaml("connector-proxyclass.yaml")
    pod = proxy_class["spec"]["statefulSet"]["pod"]
    expected_labels = {"app.kubernetes.io/part-of": "tailscale-infrastructure-connector"}
    assert pod["labels"] == expected_labels
    required = pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    assert required == [
        {
            "labelSelector": {"matchLabels": expected_labels},
            "topologyKey": "kubernetes.io/hostname",
        }
    ]

    connector = load_yaml("connector.yaml")
    assert connector["apiVersion"] == "tailscale.com/v1alpha1"
    assert connector["kind"] == "Connector"
    assert connector["spec"] == {
        "replicas": 2,
        "hostnamePrefix": "infrastructure-subnet-",
        "proxyClass": "tailscale-connector-ha",
        "tags": ["tag:k8s-subnet"],
        "subnetRouter": {"advertiseRoutes": [ROUTE_VARIABLE]},
    }

    # The route remains a Flux substitution token in the public manifest.
    public_route = connector["spec"]["subnetRouter"]["advertiseRoutes"][0]
    try:
        ipaddress.ip_network(public_route)
    except ValueError:
        pass
    else:
        raise AssertionError("public Connector manifest contains a literal route")

    binding = yaml.safe_load(RBAC.read_text(encoding="utf-8"))
    assert binding["subjects"] == [
        {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Group",
            "name": "hermes-readers",
        }
    ]

    kustomization = load_yaml("kustomization.yaml")
    assert set(kustomization["resources"]) == {
        "./api-proxy.yaml",
        "./connector-proxyclass.yaml",
        "./connector.yaml",
        "./helmrelease.yaml",
    }

    encrypted_settings = yaml.safe_load(
        (ROOT / "kubernetes/flux/vars/tailscale-settings.sops.yaml").read_text(encoding="utf-8")
    )
    encrypted_route = encrypted_settings["stringData"]["SECRET_INFRASTRUCTURE_CIDR"]
    assert encrypted_settings["metadata"] == {
        "name": "tailscale-settings",
        "namespace": "flux-system",
    }
    assert encrypted_route.startswith("ENC[AES256_GCM,")
    assert encrypted_settings["sops"]["encrypted_regex"] == "^(data|stringData)$"

    flux_apps = yaml.safe_load((ROOT / "kubernetes/flux/apps.yaml").read_text(encoding="utf-8"))
    top_level_sources = flux_apps["spec"]["postBuild"]["substituteFrom"]
    assert {source["name"] for source in top_level_sources} >= {"tailscale-settings"}
    nested_patch = yaml.safe_load(flux_apps["spec"]["patches"][0]["patch"])
    nested_sources = nested_patch["spec"]["postBuild"]["substituteFrom"]
    assert {source["name"] for source in nested_sources} >= {"tailscale-settings"}

    print("PASS: Tailscale API proxy, impersonation, route indirection, and HA contracts")


if __name__ == "__main__":
    main()
