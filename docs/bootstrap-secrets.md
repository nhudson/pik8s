# Bootstrap Secret recovery

Three Secrets must exist before normal Flux application reconciliation can safely begin:

- `flux-system/cluster-secrets`
- `flux-system/tailscale-settings`
- `security/onepassword-token`

They are bootstrap-only exceptions. External Secrets cannot retrieve its own provider credential, and the root Flux substitutions are required before the External Secrets controller and provider store are available.

## Recovery source

Keep the values outside Git and outside Kubernetes in an operator-accessible 1Password vault. The recovery identity must be independent from the token being restored.

Install the 1Password CLI (`op`) using the platform-specific instructions from 1Password before running `task flux:bootstrap`. The Flux task fails closed when `op` or `OP_VAULT` is unavailable.

Required item contracts:

| Item | Fields |
| --- | --- |
| `cluster-secrets` | `SECRET_ACME_EMAIL`, `SECRET_CLOUDFLARE_ACCOUNT_ID`, `SECRET_CLOUDFLARE_TUNNEL_ID`, `SECRET_DOMAIN` |
| `tailscale-settings` | `SECRET_INFRASTRUCTURE_CIDR` |
| `external-secrets-bootstrap-token` | `token` |

Do not paste values into repository configuration, command arguments, logs, or plaintext files.

## Value-safe check

Set the vault selector in the environment. Authenticate `op` with an independent recovery identity through `OP_SERVICE_ACCOUNT_TOKEN`, or omit that variable and enter the token at the hidden prompt.

```sh
export OP_VAULT='<recovery-vault>'
python3 scripts/bootstrap-secrets.py check --kubeconfig ./kubeconfig
```

The command prints counts and equality booleans only. On an existing cluster it verifies exact provider/live key sets and cryptographic value equality. A missing live Secret causes the check to fail, as expected during cold recovery.

## Idempotent apply

```sh
export OP_VAULT='<recovery-vault>'
python3 scripts/bootstrap-secrets.py apply --kubeconfig ./kubeconfig
```

The helper creates the required namespaces, applies all Secret manifests through JSON on `kubectl` stdin, takes narrowly scoped server-side ownership of those three Secret contracts, sets `kustomize.toolkit.fluxcd.io/prune: disabled`, and reads the objects back for exact key/value verification. The recovery token is provided only to `op`, never to `kubectl`. The helper never prints a value or provider response.

## Clean-cluster order

1. Install Kubernetes and obtain a working kubeconfig.
2. Install the Flux components and CRDs from `kubernetes/bootstrap/flux`.
3. Run the bootstrap Secret helper in `apply` mode.
4. Apply `kubernetes/flux/vars/cluster-settings.yaml`.
5. Apply `kubernetes/flux/config`.
6. Wait for the root `cluster` and `cluster-apps` Kustomizations.
7. Wait for `external-secrets` before `external-secrets-cluster-secret-store`.
8. Require the ClusterSecretStore, every ExternalSecret, and dependent workloads to become Ready.

`task flux:bootstrap` implements steps 2–5 in this order.

## Rotation and rollback

After changing any recovery item, run `check`, then `apply`, then verify the root Flux Kustomizations, provider store, ExternalSecrets, and consumers. Rerunning `apply` is the rollback and recovery mechanism; no repository decryption key or historical encrypted manifest is required.

If recovery authentication and all authorized 1Password access are lost simultaneously, automated recovery is intentionally blocked. Maintain an independently controlled recovery identity according to the operator's credential-backup policy.
