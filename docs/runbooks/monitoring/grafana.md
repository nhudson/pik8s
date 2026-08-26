# Grafana operations

Grafana is a disposable visualization layer over the local Prometheus service. It is not a metrics-retention system and is not part of the alert-delivery path.

## Ownership model

- The kube-prometheus-stack Helm chart owns the Grafana release, Prometheus data source, and kube-prometheus mixin dashboards.
- Labeled ConfigMaps in the monitoring namespace own additional dashboards.
- Dashboard providers reject UI updates, and provisioned dashboards are marked non-editable.
- No dashboard is downloaded at runtime. Imported dashboards must be reviewed, committed as JSON, and loaded through a labeled ConfigMap.
- No plugins are installed unless a later pull request explicitly reviews and pins them.

## State and loss model

Grafana uses a size-limited memory-backed `emptyDir`. Pod replacement therefore discards:

- UI preferences
- ad-hoc dashboards
- sessions
- manually created users, teams, and folders

The admin credential, data source, chart dashboards, and Git-owned dashboards are recreated automatically. Prometheus metrics and Alertmanager delivery are independent of Grafana availability.

## Access and authentication

Grafana attaches only to the internal Gateway API listener. Anonymous access, signup, organization creation, analytics reporting, update checks, and the news feed are disabled. The admin credential is delivered from 1Password by External Secrets and is never stored in Git. Reloader replaces the pod when that credential changes.

The dashboard and data-source sidecars use a namespace-scoped service account that can only read ConfigMaps in the monitoring namespace. They cannot read Secrets or cluster-wide resources.

## Upgrade verification

1. Render the exact kube-prometheus-stack version and verify no Grafana PVC is produced.
2. Verify the Grafana Role allows only `get`, `list`, and `watch` on ConfigMaps.
3. Confirm the internal HTTPRoute is Accepted and has resolved backends.
4. Query `/api/health` through the internal route and require a healthy database response.
5. Query the Grafana API and verify the Prometheus data source plus expected managed dashboard UIDs.
6. Delete one Grafana pod and verify the replacement restores the data source and dashboards.

## Rollback

Disable the Grafana subchart and remove its HTTPRoute, dashboard ConfigMaps, and narrow RBAC objects. Keep the 1Password item during rollback. No persistent volume requires cleanup.
