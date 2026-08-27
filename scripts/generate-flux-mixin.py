#!/usr/bin/env python3
"""Generate the pinned Flux mixin compatibility dashboard and alert."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import urllib.request

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/app"
MIXIN_REVISION = "5f69de628466706e76d71ce2ba588d40530d5818"
MIXIN_ALERT_URL = f"https://raw.githubusercontent.com/fluxcd-community/flux-mixin/{MIXIN_REVISION}/alerts/flux-alert.libsonnet"
MIXIN_ALERT_SHA256 = "ea6b9f79f62c271b33561ca4c73db1ccf36a850534f96397e8d741e2a8e24af4"
DASHBOARD_REVISION = "7ab65dc8b90f7a6751d88f18bbb4e1bee33bf334"
DASHBOARD_URL = f"https://raw.githubusercontent.com/fluxcd/flux2-monitoring-example/{DASHBOARD_REVISION}/monitoring/configs/dashboards/cluster.json"
DASHBOARD_SOURCE_SHA256 = "2a52d416ca7fee166c7703524332d3c8e586808c21ff5679a259c9dd744ed309"
RUNBOOK = "https://github.com/nhudson/pik8s/blob/main/docs/runbooks/monitoring/README.md#flux-reconciliation-failure"


def fetch(url: str, expected_sha256: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pik8s-flux-mixin-generator"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise SystemExit(f"upstream checksum mismatch for {url}: {actual}")
    return payload


def dashboard_resource() -> dict:
    dashboard = json.loads(fetch(DASHBOARD_URL, DASHBOARD_SOURCE_SHA256))
    if dashboard.get("uid") != "flux-cluster" or dashboard.get("title") != "Flux Cluster Stats":
        raise SystemExit("unexpected Flux cluster dashboard identity")
    dashboard = json.loads(json.dumps(dashboard).replace("${DS_PROMETHEUS}", "$${DS_PROMETHEUS}"))
    dashboard["editable"] = False
    dashboard["tags"] = sorted(set(dashboard.get("tags", [])) | {"flux", "mixin"})
    rendered = json.dumps(dashboard, sort_keys=True, separators=(",", ":")).encode()
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "grafana-dashboard-flux-cluster",
            "labels": {"grafana_dashboard": "1"},
            "annotations": {
                "grafana_folder": "Flux",
                "observability.home/mixin-revision": MIXIN_REVISION,
                "observability.home/source-revision": DASHBOARD_REVISION,
                "observability.home/source-sha256": DASHBOARD_SOURCE_SHA256,
                "observability.home/content-sha256": hashlib.sha256(rendered).hexdigest(),
            },
        },
        "data": {"flux-cluster.json": json.dumps(dashboard, indent=2, sort_keys=True)},
    }


def validate_rule_contract() -> None:
    source = fetch(MIXIN_ALERT_URL, MIXIN_ALERT_SHA256).decode()
    for contract in ("FluxReconcilationFailed", "gotk_reconcile_condition", "'for': '10m'"):
        if contract not in source:
            raise SystemExit(f"upstream mixin alert contract changed: missing {contract}")
    platform = yaml.safe_load((OUTPUT / "prometheusrule.yaml").read_text())
    matches = [
        rule
        for group in platform["spec"]["groups"]
        for rule in group["rules"]
        if rule.get("alert") == "FluxReconciliationFailure"
    ]
    if len(matches) != 1:
        raise SystemExit("expected exactly one preserved FluxReconciliationFailure rule")
    rule = matches[0]
    expected = {
        "expr": 'gotk_resource_info{ready!="True"} == 1',
        "for": "10m",
        "severity": "critical",
        "runbook_url": RUNBOOK,
    }
    actual = {
        "expr": rule.get("expr"),
        "for": rule.get("for"),
        "severity": rule.get("labels", {}).get("severity"),
        "runbook_url": rule.get("annotations", {}).get("runbook_url"),
    }
    if actual != expected:
        raise SystemExit(f"Flux mixin compatibility alert drift: {actual}")


def render(resource: dict) -> str:
    return "---\n" + yaml.safe_dump(resource, sort_keys=False, width=4096)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    validate_rule_contract()
    outputs = {
        OUTPUT / "grafana-dashboard-flux-cluster.yaml": render(dashboard_resource()),
    }
    drift = []
    for path, expected in outputs.items():
        if args.check:
            if not path.exists() or path.read_text() != expected:
                drift.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(expected)
    if drift:
        raise SystemExit("Flux mixin generation drift: " + ", ".join(drift))


if __name__ == "__main__":
    main()
