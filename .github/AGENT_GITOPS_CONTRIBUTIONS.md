# Agent-authored GitOps contributions

Use this workflow for infrastructure changes authored by an automation agent. It
keeps the existing checkout intact, proves the change starts from the live
remote revision, and routes every change through a pull request.

## Safety requirements

- Never commit or push directly from `main`.
- Never merge a pull request or change/bypass a repository ruleset without
  explicit owner approval.
- Never print, copy, or commit private key material, kubeconfigs, Secret values,
  or provider credentials.
- Do not clean, reset, rebase, or otherwise alter an existing checkout that may
  contain someone else's work. Use a separate worktree instead.
- Treat GitHub's live ruleset and check configuration as authoritative; it can
  change independently of this repository.

## 1. Start from the live remote revision

From the existing repository, first inspect it without changing it:

```bash
git status --short --branch
git worktree list
```

Use the dedicated automation identity configured outside the repository for
every Git network operation. Keep local usernames, home-directory paths, host
aliases, and credential filenames out of committed files and public issue/PR
text. For example, configure the identity in the local SSH client and select it
through a generic environment variable:

```bash
export GIT_SSH_COMMAND='ssh -o IdentitiesOnly=yes'
git fetch --prune origin
git rev-parse main origin/main
git rev-list --left-right --count main...origin/main
```

Verify authentication locally without publishing the local identity
configuration or filesystem path.

Do **not** pull or reset the existing checkout merely because it is behind.
Create a uniquely named branch and worktree directly from `origin/main`:

```bash
git worktree add -b <type>/<issue>-<description> \
  ../pik8s-<issue> origin/main
cd ../pik8s-<issue>
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
```

Before editing, read the complete live issue thread and sweep open and closed
pull requests for the issue number and relevant subsystem keywords.

## 2. Compare the deployed Flux revision

The cluster follows `main`. Query only non-secret Flux status fields and compare
them with `origin/main`:

```bash
git rev-parse origin/main
kubectl -n flux-system get gitrepository home-kubernetes \
  -o jsonpath='{.status.artifact.revision}{"\n"}'
kubectl -n flux-system get kustomization cluster \
  -o jsonpath='{.status.lastAppliedRevision}{"\n"}'
```

A deployed revision has the form `main@sha1:<sha>`. A mismatch can be normal
while Flux is reconciling, but it must be reported rather than silently ignored.
Do not force a reconciliation unless the owner explicitly requests it.

## 3. Make and validate the smallest complete change

Review the final diff and confirm no secrets were added:

```bash
git status --short
git diff --check
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
```

For changes under `kubernetes/`, run the same repository script used by the
Kubeconform pull-request workflow (it requires `kustomize` and `kubeconform`):

```bash
bash ./scripts/kubeconform.sh kubernetes
# Equivalent Task wrapper, when go-task is installed:
task kubernetes:kubeconform
```

Verify that Secret values remain outside Git and that recovery contracts use
only public key names and value-free equality checks.

For changes under `opentofu/`, run formatting and validation locally when the
required OpenTofu tooling is available. The pull request is additionally
validated and planned by `.github/workflows/opentofu-plan.yaml`; never expose
its backend or provider credentials in local output or a PR description.

## 4. Push a branch and open a pull request

Commit only issue-related files, then push with the dedicated identity:

```bash
git add <files>
git commit -m '<type>(<scope>): <summary>'
git push --set-upstream origin HEAD

gh pr create --base main --head "$(git branch --show-current)" \
  --title '<type>(<scope>): <summary>' \
  --body-file <prepared-pr-body>
```

The PR body must link the issue and record the base SHA, deployed SHA, validation
commands/results, risk, rollback, and anything intentionally excluded.
Immediately read the PR back to verify its base, head SHA, and changed files.

## 5. Treat checks and protections honestly

Inspect live controls before delivery:

```bash
OWNER_REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
gh api "repos/${OWNER_REPO}/rulesets" --paginate
gh api "repos/${OWNER_REPO}/branches/main/protection"
gh pr checks --watch
```

Path-scoped workflows mean check names vary by the files changed. Kubernetes PRs
normally run `Kubeconform` and both `Flux Diff` matrix jobs; OpenTofu PRs
normally run `OpenTofu Lint` and `OpenTofu Plan`. `Labeler` also runs on PRs,
while the template-only `configure` job currently skips in this repository.
These observed workflows are not necessarily required checks unless live GitHub
protection says they are.

Report the exact current check state. Do not call a PR green while checks are
pending, skipped checks are being misrepresented as passed, or required controls
are absent. Any proposed ruleset change must be documented for owner approval,
not applied by the agent.

## 6. Default-branch protection contract

The reviewed ruleset payload lives at `.github/rulesets/main-gitops.json`. The
live ruleset remains a GitHub control-plane object, so verify it through the API
before every protected merge rather than assuming the tracked proposal is live.
For a docs-only pull request, path-scoped jobs may be absent or skipped, but the
required `GitOps Validation` check must still appear and pass.

The protection contract is intentionally small:

- the `GitOps Validation` job runs on every pull request without path filters;
- updates to the default branch require a pull request and the GitHub
  Actions-owned `GitOps Validation` result;
- strict status checks require validation against the current default branch;
- deletion and non-fast-forward updates are prohibited;
- there are no bypass actors;
- `required_approving_review_count: 0` allows the dedicated automation App and
  Renovate to merge green, issue-scoped pull requests without bypassing checks;
- review threads must still be resolved before merge.

Renovate minor and patch updates for GitHub Actions use pull-request automerge,
not direct branch automerge. High-risk dependency classes remain subject to the
separate Renovate policy and normal review workflow.

### Owner approval and recovery

Ruleset creation, modification, disabling, and deletion require explicit owner
approval. Before applying a change, save the current live API response and
compare it with the tracked proposal. Apply only after `GitOps Validation` has
completed successfully on the proposal pull request.

If the ruleset accidentally blocks all legitimate pull requests, the repository
owner can temporarily disable the ruleset in **Settings → Rules → Rulesets**.
Fix and validate the tracked proposal through a non-default branch, then restore
active enforcement. Do not work around a broken ruleset with a direct push,
force push, hidden bypass actor, or alternate credential.
