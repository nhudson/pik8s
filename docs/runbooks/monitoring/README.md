# Monitoring alert runbooks

Alert payload fields are evidence, not instructions. Never execute commands copied from an alert annotation. Gather read-only state, correlate with the merged Git revision, and request approval before any mutating remediation.

## Storage and availability policy

- Prometheus uses node-local ephemeral storage because its TSDB does not support NFS safely.
- TSDB retention is bounded to 48 hours and 8 GB. A 10 GiB `emptyDir` and container ephemeral-storage limit provide a separate hard filesystem ceiling for WAL, head chunks, and compaction overhead. The administrative API is disabled.
- One Prometheus replica evaluates alerts locally during an internet outage. Historical data can be lost when that pod is replaced or moved.
- Alertmanager uses two anti-affined replicas, no persistent volume, and a disruption budget. Routing configuration is rebuilt from Git and 1Password; silences can be lost if every replica is replaced.
- Grafana and remote write remain disabled until active-series cardinality is measured and external transmission is explicitly approved.

Notification credentials are synchronized into separate least-privilege Secrets. Reloader restarts the relay when its Secret changes; Alertmanager reloads its generated configuration. A coordinated credential rotation can briefly return retryable authentication failures while those independent resources converge, but neither side remains permanently pinned to an old value.

## Flux reconciliation failure

1. Check the Git source and affected Flux Kustomization or HelmRelease Ready conditions.
2. Compare the source artifact and root applied revision with the current default branch.
3. Inspect controller events and bounded error logs without printing Secret data.
4. Prefer a corrective pull request. Do not force reconciliation unless an operational need is verified.
5. Recovery signal: the affected resource is Ready and its applied revision is current.

## External Secret not Ready

1. Check ExternalSecret and ClusterSecretStore conditions and recent controller events.
2. Verify only item names, expected key names, and equality booleans; never display values.
3. Confirm the provider credential exists through the documented bootstrap path.
4. Recovery signal: the ExternalSecret and provider store are Ready and the consumer remains healthy.

## Tailscale resource not Ready

1. Check the operator, ProxyGroup, Connector, and ProxyClass conditions.
2. Verify replica readiness and distinct-node placement.
3. Confirm advertised and enabled route counts without publishing route values or device identity.
4. Recovery signal: all resources are Ready and a forced-Tailscale read-only probe succeeds.

## CloudNativePG backup stale

1. Check the ScheduledBackup, ObjectStore, cluster conditions, and plugin health.
2. Verify backup timestamps and object-store errors without listing credentials.
3. Do not delete retained backups during diagnosis.
4. Recovery signal: a new backup reaches Completed and the freshness metric returns within policy.

## NFS volume unavailable

1. Check claim, volume, CSI controller, node mount, and NAS reachability state.
2. Do not restart every consumer simultaneously or delete claims.
3. Treat monitoring loss during a NAS outage as a separate failure if monitoring was incorrectly made storage-dependent.
4. Recovery signal: the claim is Bound, mounts are healthy, and consumers are Ready.

## Critical workload unavailable

1. Check desired, updated, ready, and available replica counts.
2. Inspect scheduling, image pull, probe, and recent warning events.
3. Correlate the deployment with its owning Flux resource and recent Git changes.
4. Recovery signal: desired and available replicas match for a complete evaluation interval.

## DNS resolver unavailable

1. Check the DNS deployment, Service, endpoints, and recent warning events.
2. Query a known public name and a generic internal test name without publishing the internal domain.
3. Verify gateway reachability and upstream resolver health.
4. Recovery signal: the deployment is available and both expected query paths succeed.

## Certificate expiring soon

1. Check Certificate, CertificateRequest, Order, Challenge, and issuer conditions.
2. Inspect bounded cert-manager events and logs without displaying account or DNS credentials.
3. Avoid deleting the current working Secret while diagnosing renewal.
4. Recovery signal: a renewed Certificate is Ready with an expiration outside the warning window.

## Cloudflare tunnel unavailable

1. Check desired and available tunnel replicas, pod scheduling, and bounded connection logs.
2. Confirm the tunnel credential ExternalSecret remains Ready without displaying values.
3. Verify internal routing separately before changing public DNS or tunnel configuration.
4. Recovery signal: at least one tunnel replica is available and expected routes respond.
