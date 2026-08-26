#!/usr/bin/env python3
"""Contracts for storage and NFS observability."""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/app"


class StorageObservabilityTests(unittest.TestCase):
    def test_node_exporter_collects_host_nfs_mountstats(self):
        release = yaml.safe_load((APP / "helmrelease.yaml").read_text())
        exporter = release["spec"]["values"]["prometheus-node-exporter"]
        self.assertIn("--collector.mountstats", exporter.get("extraArgs", []))
        root_mount = exporter.get("hostRootFsMount", {})
        self.assertTrue(root_mount.get("enabled"))
        self.assertEqual("HostToContainer", root_mount.get("mountPropagation"))

    def test_generated_storage_dashboard_has_privacy_safe_nfs_and_pvc_queries(self):
        path = APP / "grafana-dashboard-storage.yaml"
        self.assertTrue(path.exists(), "storage dashboard must be generated and Git-owned")
        resource = yaml.safe_load(path.read_text())
        self.assertEqual("ConfigMap", resource["kind"])
        self.assertEqual("1", resource["metadata"]["labels"]["grafana_dashboard"])
        dashboard = json.loads(resource["data"]["storage.json"])
        self.assertEqual("platform-storage", dashboard["uid"])
        self.assertFalse(dashboard["editable"])
        expressions = "\n".join(
            target["expr"]
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        )
        for metric in (
            "node_mountstats_nfs_operations_requests_total",
            "node_mountstats_nfs_operations_request_time_seconds_total",
            "node_mountstats_nfs_operations_transmissions_total",
            "node_mountstats_nfs_operations_major_timeouts_total",
            "kubelet_volume_stats_capacity_bytes",
            "kubelet_volume_stats_available_bytes",
            "kube_persistentvolumeclaim_resource_requests_storage_bytes",
            "kube_persistentvolumeclaim_status_phase",
        ):
            self.assertIn(metric, expressions)
        compact = re.sub(r"\s+", "", expressions)
        self.assertIn(
            "maxby(namespace,persistentvolumeclaim)(kubelet_volume_stats_capacity_bytes)",
            compact,
        )
        self.assertIn(
            "maxby(namespace,persistentvolumeclaim)(kube_persistentvolumeclaim_resource_requests_storage_bytes)",
            compact,
        )
        self.assertIn(
            'max by (namespace, persistentvolumeclaim) (kube_persistentvolumeclaim_status_phase{phase=~"Pending|Lost"}) == 1',
            expressions,
        )
        for private_label in ("export", "mountaddr", "mountpoint"):
            self.assertNotIn(private_label, expressions)

    def test_storage_dashboard_is_wired_into_gitops_and_canonical_validation(self):
        resources = yaml.safe_load((APP / "kustomization.yaml").read_text())["resources"]
        self.assertIn("./grafana-dashboard-storage.yaml", resources)
        canonical = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("python3 ./scripts/test-storage-observability.py", canonical)
        provenance = (ROOT / "docs/runbooks/monitoring/dashboard-sources.md").read_text()
        self.assertIn("node_exporter", provenance)
        self.assertIn("6044da783597cc3b57aef7580ddcdcff58a4ee99", provenance)

    def test_generated_dashboard_has_no_drift(self):
        completed = subprocess.run(
            ["python3", str(ROOT / "scripts/generate-observability-dashboards.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
