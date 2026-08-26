#!/usr/bin/env python3
"""Generate the small Git-owned component dashboard pack."""
from __future__ import annotations

import argparse
import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "kubernetes/apps/monitoring/kube-prometheus-stack/app"

DASHBOARDS = {
    "database": {
        "uid": "platform-database",
        "title": "Platform / Database",
        "panels": [
            ("Database instances up", "sum(cnpg_collector_up) or vector(0)", "stat", "short"),
            ("Maximum replication lag", "max(cnpg_pg_replication_lag) or vector(0)", "stat", "s"),
            ("Database size by database", "max by (datname) (cnpg_pg_database_size_bytes{datname!~\"template0|template1\"})", "timeseries", "bytes"),
            ("Active backends", "sum(cnpg_backends_total)", "timeseries", "short"),
            ("WAL generation", "sum(rate(cnpg_collector_wal_bytes[5m]))", "timeseries", "Bps"),
            ("Latest backup age", "time() - max(cnpg_collector_last_available_backup_timestamp)", "timeseries", "s"),
            ("Archive failures", "sum(increase(cnpg_pg_stat_archiver_failed_count[1h]))", "timeseries", "short"),
        ],
    },
    "network": {
        "uid": "platform-network",
        "title": "Platform / Network and Flows",
        "panels": [
            ("Cilium drops by reason", "sum by (reason) (rate(cilium_drop_count_total[5m]))", "timeseries", "ops"),
            ("Cilium endpoint state", "sum by (endpoint_state) (cilium_endpoint_state)", "timeseries", "short"),
            ("Cilium failing controllers", "sum(cilium_controllers_failing) or vector(0)", "stat", "short"),
            ("Hubble flows", "sum(rate(hubble_flows_processed_total[5m]))", "timeseries", "ops"),
            ("Hubble lost events", "sum(rate(hubble_lost_events_total[5m]))", "timeseries", "ops"),
            ("Hubble HTTP responses", "sum by (status) (rate(hubble_http_responses_total[5m]))", "timeseries", "reqps"),
        ],
    },
    "control-plane": {
        "uid": "platform-control-plane",
        "title": "Platform / Controllers and Integrations",
        "panels": [
            ("Nearest certificate expiry", "min(certmanager_certificate_expiration_timestamp_seconds - time())", "stat", "s"),
            ("Certificates not Ready", "sum(certmanager_certificate_ready_status{condition!=\"True\"}) or vector(0)", "stat", "short"),
            ("External Secret sync errors", "sum(rate(externalsecret_sync_calls_error[5m]))", "timeseries", "ops"),
            ("External DNS source errors", "sum(rate(external_dns_source_errors_total[5m]))", "timeseries", "ops"),
            ("Tunnel HA connections", "sum(cloudflared_tunnel_ha_connections)", "timeseries", "short"),
            ("Tunnel request errors", "sum(rate(cloudflared_tunnel_request_errors[5m]))", "timeseries", "ops"),
            ("Reloader executions", "sum(rate(reloader_reload_executed_total[5m]))", "timeseries", "ops"),
            ("Reloader retries", "sum(rate(reloader_retries_total[5m]))", "timeseries", "ops"),
        ],
    },
    "delivery": {
        "uid": "platform-alert-delivery",
        "title": "Platform / Alert Delivery",
        "panels": [
            ("Firing alerts", "sum by (severity) (ALERTS{alertstate=\"firing\"})", "timeseries", "short"),
            ("Notifications sent", "sum by (integration) (rate(alertmanager_notifications_total[5m]))", "timeseries", "ops"),
            ("Notification failures", "sum by (integration) (rate(alertmanager_notifications_failed_total[5m]))", "timeseries", "ops"),
            ("Configuration reload healthy", "min(alertmanager_config_last_reload_successful) or vector(0)", "stat", "short"),
        ],
    },
    "storage": {
        "uid": "platform-storage",
        "title": "Platform / Storage and NFS",
        "panels": [
            ("NFS mounts reporting", "count(node_mountstats_nfs_age_seconds_total) or vector(0)", "stat", "short"),
            ("NFS requests by operation", "sum by (operation) (rate(node_mountstats_nfs_operations_requests_total[5m]))", "timeseries", "reqps"),
            ("NFS average request time", "sum by (operation) (rate(node_mountstats_nfs_operations_request_time_seconds_total[5m])) / clamp_min(sum by (operation) (rate(node_mountstats_nfs_operations_requests_total[5m])), 1e-9)", "timeseries", "s"),
            ("NFS retransmission ratio", "clamp_min(sum by (operation) (rate(node_mountstats_nfs_operations_transmissions_total[5m])) - sum by (operation) (rate(node_mountstats_nfs_operations_requests_total[5m])), 0) / clamp_min(sum by (operation) (rate(node_mountstats_nfs_operations_requests_total[5m])), 1e-9)", "timeseries", "percentunit"),
            ("NFS major timeouts", "sum by (operation) (rate(node_mountstats_nfs_operations_major_timeouts_total[5m]))", "timeseries", "ops"),
            ("PVC capacity", "max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes)", "timeseries", "bytes"),
            ("PVC utilization", "1 - max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_available_bytes) / clamp_min(max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes), 1)", "timeseries", "percentunit"),
            ("PVC requested storage", "max by (namespace, persistentvolumeclaim) (kube_persistentvolumeclaim_resource_requests_storage_bytes)", "timeseries", "bytes"),
            ("PVCs Pending or Lost", "max by (namespace, persistentvolumeclaim) (kube_persistentvolumeclaim_status_phase{phase=~\"Pending|Lost\"}) == 1", "timeseries", "short"),
        ],
    },
    "media": {
        "uid": "platform-media",
        "title": "Platform / Media",
        "panels": [
            ("Exporter targets up", "max by (endpoint) (up{job=\"exportarr\"})", "timeseries", "short"),
            ("Sonarr healthy", "max(sonarr_system_status{job=\"exportarr\"}) or vector(0)", "stat", "short"),
            ("Radarr healthy", "max(radarr_system_status{job=\"exportarr\"}) or vector(0)", "stat", "short"),
            ("Prowlarr healthy", "max(prowlarr_system_status{job=\"exportarr\"}) or vector(0)", "stat", "short"),
            ("SABnzbd healthy", "max(sabnzbd_status{job=\"exportarr\"}) or vector(0)", "stat", "short"),
            ("Sonarr queue", "sum(sonarr_queue_total{job=\"exportarr\"}) or vector(0)", "timeseries", "short"),
            ("Radarr queue", "sum(radarr_queue_total{job=\"exportarr\"}) or vector(0)", "timeseries", "short"),
            ("SABnzbd queue", "sum(sabnzbd_queue_length{job=\"exportarr\"}) or vector(0)", "timeseries", "short"),
            ("SABnzbd download speed", "sum(sabnzbd_speed_bps{job=\"exportarr\"}) or vector(0)", "timeseries", "Bps"),
        ],
    },
}


def panel(index: int, title: str, expression: str, panel_type: str, unit: str) -> dict:
    width = 8 if panel_type == "stat" else 12
    row = index // 2
    x = 0 if index % 2 == 0 else 12
    return {
        "id": index + 1,
        "title": title,
        "type": panel_type,
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "gridPos": {"h": 7, "w": width, "x": x, "y": row * 7},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {
            "legend": {"displayMode": "table", "placement": "bottom", "showLegend": panel_type != "stat"},
            "tooltip": {"mode": "single", "sort": "none"},
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
        "targets": [{"expr": expression, "refId": "A"}],
    }


def render(name: str, spec: dict) -> str:
    dashboard = {
        "annotations": {"list": []},
        "editable": False,
        "graphTooltip": 1,
        "links": [],
        "panels": [panel(i, *definition) for i, definition in enumerate(spec["panels"])],
        "refresh": "1m",
        "schemaVersion": 41,
        "tags": ["platform", "gitops"],
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": spec["title"],
        "uid": spec["uid"],
        "version": 1,
    }
    resource = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"grafana-dashboard-{name}", "labels": {"grafana_dashboard": "1"}},
        "data": {f"{name}.json": json.dumps(dashboard, indent=2, sort_keys=True)},
    }
    return "---\n" + yaml.safe_dump(resource, sort_keys=False, width=4096)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    drift = []
    for name, spec in DASHBOARDS.items():
        path = OUTPUT / f"grafana-dashboard-{name}.yaml"
        expected = render(name, spec)
        if args.check:
            if not path.exists() or path.read_text() != expected:
                drift.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(expected)
    if drift:
        raise SystemExit("dashboard generation drift: " + ", ".join(drift))


if __name__ == "__main__":
    main()
