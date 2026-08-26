#!/usr/bin/env python3
"""Inject value-free bootstrap substitutions into a Flux diff checkout."""
from __future__ import annotations

import argparse
from pathlib import Path

RESOURCE = "./ci-bootstrap-substitutions.yaml"
RETIRED_RESOURCES = {"./cluster-secrets.sops.yaml", "./tailscale-settings.sops.yaml", RESOURCE}
CONTRACTS = (
    (
        "cluster-secrets",
        (
            "SECRET_ACME_EMAIL",
            "SECRET_CLOUDFLARE_ACCOUNT_ID",
            "SECRET_CLOUDFLARE_TUNNEL_ID",
            "SECRET_DOMAIN",
        ),
    ),
    ("tailscale-settings", ("SECRET_INFRASTRUCTURE_CIDR",)),
)


def render() -> str:
    documents: list[str] = []
    for name, keys in CONTRACTS:
        lines = [
            "---",
            "apiVersion: v1",
            "kind: Secret",
            "metadata:",
            f"  name: {name}",
            "  namespace: flux-system",
            "type: Opaque",
            "stringData:",
        ]
        lines.extend(f'  {key}: ".PLACEHOLDER_{key}."' for key in keys)
        documents.append("\n".join(lines))
    return "\n".join(documents) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    args = parser.parse_args()
    target = args.checkout / "kubernetes/flux/vars"
    kustomization = target / "kustomization.yaml"
    lines = [
        line
        for line in kustomization.read_text().splitlines()
        if line.strip().removeprefix("- ") not in RETIRED_RESOURCES
    ]
    lines.append(f"  - {RESOURCE}")
    kustomization.write_text("\n".join(lines) + "\n")
    (target / RESOURCE.removeprefix("./")).write_text(render())


if __name__ == "__main__":
    main()
