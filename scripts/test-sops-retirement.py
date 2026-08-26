#!/usr/bin/env python3
"""Deterministic contract for complete SOPS retirement and recovery wiring."""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


class SopsRetirementTests(unittest.TestCase):
    def test_no_sops_artifacts_remain(self):
        artifacts = [path for path in ROOT.rglob("*") if path.is_file() and (".sops." in path.name or path.name == ".sops.yaml")]
        self.assertEqual([], artifacts)

    def test_flux_has_no_decryption_or_age_secret_dependency(self):
        paths = [
            ROOT / "kubernetes/flux/apps.yaml",
            ROOT / "kubernetes/flux/config/cluster.yaml",
            ROOT / "bootstrap/templates/kubernetes/flux/apps.yaml.j2",
            ROOT / "bootstrap/templates/kubernetes/flux/config/cluster.yaml.j2",
        ]
        for path in paths:
            text = path.read_text()
            self.assertNotIn("decryption:", text, path)
            self.assertNotIn("sops-age", text, path)
        live_apps = yaml.safe_load((ROOT / "kubernetes/flux/apps.yaml").read_text())
        template_apps = yaml.safe_load((ROOT / "bootstrap/templates/kubernetes/flux/apps.yaml.j2").read_text())
        self.assertEqual(live_apps, template_apps)

    def test_task_and_bootstrap_tooling_has_no_sops_dependency(self):
        sops_task_files = [path for path in (ROOT / ".taskfiles/Sops").glob("**/*") if path.is_file()]
        self.assertEqual([], sops_task_files)
        paths = [
            ROOT / "Taskfile.yaml",
            ROOT / ".taskfiles/Flux/Taskfile.yaml",
            ROOT / ".taskfiles/Repository/Taskfile.yaml",
            ROOT / ".taskfiles/Talos/Taskfile.yaml",
            ROOT / ".taskfiles/Workstation/Archfile",
            ROOT / ".taskfiles/Workstation/Brewfile",
            ROOT / ".taskfiles/Workstation/Taskfile.yaml",
            ROOT / "bootstrap/scripts/validation.py",
            ROOT / "config.sample.yaml",
            ROOT / ".github/workflows/e2e.yaml",
            ROOT / ".devcontainer/ci/features/install.sh",
            ROOT / ".gitattributes",
            ROOT / ".gitignore",
            ROOT / ".vscode/extensions.json",
            ROOT / ".vscode/settings.json",
        ]
        pattern = re.compile(r"\bsops\b|sops-age|SOPS_AGE|bootstrap_sops_age|AGE_FILE|agekey|sopsdiffer", re.IGNORECASE)
        for path in paths:
            self.assertIsNone(pattern.search(path.read_text()), path)

    def test_talos_secret_is_local_private_state(self):
        taskfile = (ROOT / ".taskfiles/Talos/Taskfile.yaml").read_text()
        self.assertIn('{{.PRIVATE_DIR}}/talsecret.yaml', taskfile)
        self.assertIn("umask 077", taskfile)
        self.assertNotIn(".sops.yaml", taskfile)

    def test_private_repository_deploy_key_uses_local_files(self):
        taskfile = (ROOT / ".taskfiles/Flux/Taskfile.yaml").read_text()
        self.assertIn("--from-file=identity=", taskfile)
        self.assertIn("--from-file=identity.pub=", taskfile)
        self.assertIn("--from-file=known_hosts=", taskfile)
        self.assertNotIn("sops --decrypt", taskfile)
        self.assertFalse((ROOT / "bootstrap/templates/kubernetes/bootstrap/flux/github-deploy-key.sops.yaml.j2").exists())

    def test_recovery_scripts_remain_in_validation_path(self):
        kubeconform = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("test-bootstrap-secrets.py", kubeconform)
        self.assertIn("test-sops-retirement.py", kubeconform)
        self.assertTrue((ROOT / "docs/bootstrap-secrets.md").exists())
        readme = (ROOT / "README.md").read_text()
        self.assertNotIn("bootstrap_github_webhook_token", readme)
        self.assertNotIn("bootstrap_cloudflare.domain", readme)

    def test_root_and_provider_sops_resources_are_absent(self):
        root_resources = yaml.safe_load((ROOT / "kubernetes/flux/vars/kustomization.yaml").read_text())["resources"]
        provider_resources = yaml.safe_load((ROOT / "kubernetes/apps/security/external-secrets/app/kustomization.yaml").read_text())["resources"]
        self.assertEqual(["./cluster-settings.yaml"], root_resources)
        self.assertEqual(["./helmrelease.yaml"], provider_resources)

    def test_flux_diff_generates_value_free_bootstrap_substitution_stubs(self):
        script = ROOT / "scripts/prepare-flux-diff-bootstrap.py"
        workflow = (ROOT / ".github/workflows/flux-diff.yaml").read_text()
        self.assertTrue(script.exists())
        self.assertIn("prepare-flux-diff-bootstrap.py pull", workflow)
        self.assertIn("prepare-flux-diff-bootstrap.py default", workflow)
        with tempfile.TemporaryDirectory() as directory:
            checkout = pathlib.Path(directory)
            target = checkout / "kubernetes/flux/vars"
            target.mkdir(parents=True)
            shutil.copy(ROOT / "kubernetes/flux/vars/kustomization.yaml", target)
            with (target / "kustomization.yaml").open("a") as stream:
                stream.write("  - ./cluster-secrets.sops.yaml\n  - ./tailscale-settings.sops.yaml\n")
            subprocess.run(["python3", str(script), str(checkout)], check=True)
            subprocess.run(["python3", str(script), str(checkout)], check=True)
            resources = yaml.safe_load((target / "kustomization.yaml").read_text())["resources"]
            self.assertEqual(["./cluster-settings.yaml", "./ci-bootstrap-substitutions.yaml"], resources)
            documents = list(yaml.safe_load_all((target / "ci-bootstrap-substitutions.yaml").read_text()))
            self.assertEqual(["cluster-secrets", "tailscale-settings"], [doc["metadata"]["name"] for doc in documents])
            self.assertEqual(
                {"SECRET_ACME_EMAIL", "SECRET_CLOUDFLARE_ACCOUNT_ID", "SECRET_CLOUDFLARE_TUNNEL_ID", "SECRET_DOMAIN"},
                set(documents[0]["stringData"]),
            )
            self.assertEqual({"SECRET_INFRASTRUCTURE_CIDR"}, set(documents[1]["stringData"]))
            self.assertTrue(all(value.startswith(".PLACEHOLDER_") and value.endswith(".") for doc in documents for value in doc["stringData"].values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
