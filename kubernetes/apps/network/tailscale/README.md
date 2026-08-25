# Tailscale Kubernetes Operator

Flux installs the pinned official `tailscale-operator` chart into the `network`
namespace. The Kubernetes API server proxy and impersonation RBAC are disabled;
this change does not publish a workload or enable routes, DNS, or public access.

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
`tailscale.com` CRDs exist. In the Tailscale admin console, confirm a machine
named `tailscale-operator` exists with only `tag:k8s-operator`. Do not create
Ingresses, Services, Connectors, routes, grants, or DNS changes as part of this
verification.

## Rollback

Before rollback, confirm no `tailscale.com` custom resources have been created;
removing their CRDs would also remove those resources. Revert the enabling
commit and merge the revert. Flux will uninstall the Helm release and prune its
resources plus the ExternalSecret. Confirm the two Tailscale Kustomizations,
the operator Deployment, and the generated Secret are gone. Then remove the
operator machine and revoke the OAuth client in the Tailscale admin console.
Do not remove or alter tailnet policy entries automatically.

## Compatibility references

- Official installation and required OAuth scopes:
  <https://tailscale.com/docs/kubernetes-operator/install-operator>
- Stable chart repository:
  <https://pkgs.tailscale.com/helmcharts>
- Official compatibility matrix:
  <https://tailscale.com/docs/kubernetes-operator/reference/compatibility>
- Pinned chart `1.102.3` declares app version `v1.102.3`, installs its current
  CRDs by default, and consumes `operator-oauth` keys `client_id` and
  `client_secret` when inline OAuth values are unset. It requires Kubernetes
  `v1.23.0` or newer. The chart defaults both the operator and any proxies to
  `v1.102.3`, matching Tailscale's recommendation to keep their versions equal.