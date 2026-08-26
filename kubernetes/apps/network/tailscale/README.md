# Tailscale Kubernetes Operator

Flux installs the pinned official `tailscale-operator` chart into the `network`
namespace. A dedicated, two-replica `ProxyGroup` exposes the Kubernetes API in
`auth` mode, where the proxy derives Kubernetes impersonation headers from the
caller's Tailscale identity and an explicit Tailscale grant. The in-process
operator proxy remains disabled. A two-replica `Connector` advertises only the
encrypted `SECRET_INFRASTRUCTURE_CIDR` substitution. Required pod anti-affinity
keeps Connector replicas on distinct eligible nodes.

The API endpoint and subnet route remain private to the tailnet. This repository
does not grant access by itself: the owner must separately approve the exact
Tailscale policy and route. The NATed client/IoT network is intentionally not
advertised because a router must be physically inside that network.

## Required owner setup

Complete all prerequisites before merging. Flux deliberately blocks the
operator Kustomization until External Secrets can create `operator-oauth`.

1. In the tailnet access controls, define these tag owners (merge them into the
   existing `tagOwners` object rather than replacing other entries):

   ```json
   "tag:k8s-operator": [],
   "tag:k8s": ["tag:k8s-operator"]
   ```

2. In **Trust credentials**, create an OAuth client with `tag:k8s-operator`
   and **Write** access for exactly:
   - `General / Services`
   - `Devices / Core`
   - `Keys / Auth Keys`

3. In the existing 1Password vault configured by the `1password`
   ClusterSecretStore, create an item named `tailscale-operator-oauth` with
   concealed fields named `client_id` and `client_secret`. Paste the generated
   values directly into 1Password; never put them in Git, command output, an
   issue, or a pull request.

The ExternalSecret maps only those two fields into the chart's pre-existing
`operator-oauth` Secret contract. No credential value is stored in this repo.

## Required access-control approval

The API proxy does **not** map a Tailscale group in Kubernetes YAML. In Tailscale's
documented auth model, a tailnet grant addressed to the ProxyGroup tag supplies
the `Impersonate-Group` value. Kubernetes then authorizes that group through the
existing `hermes-reader` ClusterRoleBinding. Without the application capability
grant below, the approved source is not mapped to `hermes-readers`.

Before merge, replace placeholders locally, validate the policy in Tailscale's
policy editor, and obtain explicit owner approval. Merge these entries into the
existing objects; do not replace unrelated policy. Do not commit the resolved
policy or values.

```json
{
  "tagOwners": {
    "tag:k8s-api": ["tag:k8s-operator"],
    "tag:k8s-subnet": ["tag:k8s-operator"]
  },
  "grants": [
    {
      "src": ["group:<APPROVED_TAILSCALE_GROUP>"],
      "dst": ["tag:k8s-api"],
      "ip": ["tcp:80", "tcp:443"]
    },
    {
      "src": ["group:<APPROVED_TAILSCALE_GROUP>"],
      "dst": ["tag:k8s-api"],
      "app": {
        "tailscale.com/cap/kubernetes": [{
          "impersonate": {"groups": ["hermes-readers"]}
        }]
      }
    },
    {
      "src": ["group:<APPROVED_TAILSCALE_GROUP>"],
      "dst": ["<INFRASTRUCTURE_CIDR>"],
      "ip": ["*"]
    }
  ],
  "autoApprovers": {
    "services": {
      "svc:*": ["tag:k8s-api"]
    },
    "routes": {
      "<INFRASTRUCTURE_CIDR>": ["tag:k8s-subnet"]
    }
  }
}
```

If automatic route approval is not acceptable, omit the `routes` auto-approver
and approve exactly `<INFRASTRUCTURE_CIDR>` for both Connector devices manually
after reviewing them. Never approve any additional advertised route. The
existing OAuth client scopes remain unchanged; `tag:k8s-operator` ownership of
the two workload tags lets the operator create only those tagged devices.

The route is a bootstrap-only 1Password item field restored into the
`tailscale-settings` Flux substitution by `scripts/bootstrap-secrets.py`. To
change it, update the concealed recovery field, run the helper's value-safe
`check` and `apply` modes, and never put the value in a command argument, Git
diff, issue, or pull request.

Restricted DNS is also an owner action. If internal names are required, add a
split-DNS nameserver for `<INTERNAL_DOMAIN>` pointing to
`<INTERNAL_DNS_SERVER>` only after the route is approved and verify that the
approved group alone can reach that resolver. Do not enable global nameservers
or replace unrelated tailnet DNS settings.

## Post-merge verification

```sh
flux get kustomization tailscale-operator-credentials -n flux-system
flux get kustomization tailscale-operator -n flux-system
flux get helmrelease tailscale-operator -n network
kubectl get externalsecret tailscale-operator-oauth -n network
kubectl get deployment operator -n network
kubectl get crd | grep tailscale.com
```

Confirm both Kustomizations and the HelmRelease are `Ready`, the ExternalSecret
reports `SecretSynced`, the operator Deployment is available, and the expected
`tailscale.com` CRDs exist. Also verify:

```sh
kubectl wait proxyclass/tailscale-connector-ha \
  --for=condition=ProxyClassReady=true --timeout=5m
kubectl wait proxygroup/kubernetes-api \
  --for=condition=ProxyGroupReady=true --timeout=5m
kubectl wait connector/infrastructure-subnet \
  --for=condition=ConnectorReady=true --timeout=5m
kubectl get pods -A \
  -l app.kubernetes.io/part-of=tailscale-infrastructure-connector -o wide
```

Confirm the two Connector pods run on different nodes. In the Tailscale admin
console, confirm the API devices have only `tag:k8s-api`, Connector devices have
only `tag:k8s-subnet`, and exactly the intended route is advertised and
approved. No tailnet policy, route, or DNS change is applied by Flux.

### Off-site authorization test

From an approved identity on a genuinely off-site connection:

```sh
tailscale configure kubeconfig <API_PROXY_URL>
kubectl auth can-i get pods --all-namespaces
kubectl auth can-i get secrets --all-namespaces
kubectl auth can-i create pods --all-namespaces
curl --fail --connect-timeout 5 http://<AUTHORIZED_INFRASTRUCTURE_TARGET>/
```

The first authorization check must return `yes`; both sensitive/write checks
must return `no`; and the approved infrastructure target must be reachable.
Repeat from an identity outside `<APPROVED_TAILSCALE_GROUP>` and confirm both API
authorization and infrastructure reachability fail. Do not paste resolved URLs,
addresses, kubeconfig content, or identity names into public artifacts.

### Failure tests

1. Record the two Connector pod names and nodes from the label query above.
2. Delete one Connector pod. While it is unavailable, repeat the off-site
   infrastructure probe and confirm it succeeds through the remaining replica.
3. Wait for the replacement to become Ready and confirm required anti-affinity
   places it on a different eligible node from its peer.
4. Scale the `operator` Deployment in `network` to zero. Confirm existing API
   and Connector proxies continue serving traffic while CR status stops
   reconciling. Scale it back to one, wait for availability, and confirm all
   three custom resources return to Ready. Do not leave the Deployment scaled.

## Rollback

Revert the access-enabling commit and merge the revert. Flux will prune the
`Connector`, `ProxyGroup`, and `ProxyClass`, disable impersonation RBAC in the
chart, and remove the encrypted route Secret. Confirm the workload devices and
advertised route disappear before removing the approved `grants`,
`autoApprovers`, and workload `tagOwners` entries in the Tailscale policy. Remove
split DNS only if it was introduced solely for this access path. Do not revoke
the operator OAuth client or uninstall the operator for this rollback.

## Compatibility references

- Official installation and required OAuth scopes:
  <https://tailscale.com/docs/kubernetes-operator/install-operator>
- Stable chart repository:
  <https://pkgs.tailscale.com/helmcharts>
- Official compatibility matrix:
  <https://tailscale.com/docs/kubernetes-operator/reference/compatibility>
- API proxy auth and grant-to-Kubernetes-group mapping:
  <https://tailscale.com/docs/kubernetes-operator/api-server-access/auth-and-rbac>
- Dedicated auth-mode API ProxyGroup setup:
  <https://tailscale.com/docs/kubernetes-operator/api-server-access/setup-api-over-tailscale>
- Connector subnet-router configuration:
  <https://tailscale.com/docs/kubernetes-operator/connector/deploy-subnet-router>
- ProxyGroup and ProxyClass high availability:
  <https://tailscale.com/docs/kubernetes-operator/manage-and-configure/high-availability>
- Pinned chart `1.102.3` declares app version `v1.102.3`, installs its current
  CRDs by default, and consumes `operator-oauth` keys `client_id` and
  `client_secret` when inline OAuth values are unset. It requires Kubernetes
  `v1.23.0` or newer. The chart defaults both the operator and any proxies to
  `v1.102.3`, matching Tailscale's recommendation to keep their versions equal.