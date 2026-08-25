# Hermes Kubernetes reader

The `hermes-readers` Kubernetes group is bound to an explicit read-only
`ClusterRole`. The role uses only `get`, `list`, and `watch`, names every API
group and resource, and deliberately grants no access to Secrets, ConfigMaps,
pod logs or streaming subresources, credentials, or authorization policy.

No user, ServiceAccount, token, Secret, or kubeconfig is created here. Tailscale's
Kubernetes API proxy can later add `hermes-readers` as an impersonation group for
the approved tailnet identity. The Tailscale grant and exact identity mapping
are intentionally deferred to issue #1375 because they change the tailnet
security boundary.

Run the manifest authorization matrix locally:

```sh
python3 scripts/test-hermes-reader-rbac.py
```

After Flux applies the manifests, a cluster administrator can verify the same
contract without issuing a credential by impersonating the group. Representative
checks are:

```sh
kubectl auth can-i list nodes --as=hermes-rbac-test --as-group=hermes-readers
kubectl auth can-i list helmreleases.helm.toolkit.fluxcd.io --all-namespaces \
  --as=hermes-rbac-test --as-group=hermes-readers
kubectl auth can-i get secrets --all-namespaces \
  --as=hermes-rbac-test --as-group=hermes-readers
kubectl auth can-i create pods --all-namespaces \
  --as=hermes-rbac-test --as-group=hermes-readers
kubectl auth can-i create pods --subresource=exec --all-namespaces \
  --as=hermes-rbac-test --as-group=hermes-readers
```

The first two checks must return `yes`; the final three must return `no`. The
test script covers every granted tuple and explicit negative checks for Secrets,
ConfigMaps, pod mutation, logs, exec, attach, port-forward, TokenRequests, RBAC,
admission, and impersonation.

## Rollback

Revert the commit that adds this directory and removes its two entries from the
security kustomization. Flux pruning will delete the `hermes-reader`
ClusterRoleBinding and ClusterRole, immediately removing the group's access.
