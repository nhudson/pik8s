#!/usr/bin/env python3
"""Contract tests for enforceable GitHub repository protection."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/gitops-validation.yaml"
RULESET = ROOT / ".github/rulesets/main-gitops.json"


class GitHubProtectionTests(unittest.TestCase):
    def test_validation_check_is_always_present(self):
        self.assertTrue(WORKFLOW.exists())
        workflow = yaml.safe_load(WORKFLOW.read_text())
        triggers = workflow.get("on", workflow.get(True))
        self.assertIn("pull_request", triggers)
        self.assertNotIn("paths", triggers["pull_request"])
        self.assertIn("merge_group", triggers)
        self.assertEqual({"contents": "read"}, workflow["permissions"])
        jobs = workflow["jobs"]
        self.assertEqual(["gitops-validation"], list(jobs))
        job = jobs["gitops-validation"]
        self.assertEqual("GitOps Validation", job["name"])
        checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
        self.assertEqual(0, checkout["with"]["fetch-depth"])
        commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
        self.assertIn("git diff --check", commands)
        self.assertIn("bash ./scripts/kubeconform.sh kubernetes", commands)

    def test_ruleset_proposal_protects_only_default_branch(self):
        self.assertTrue(RULESET.exists())
        ruleset = json.loads(RULESET.read_text())
        self.assertEqual("branch", ruleset["target"])
        self.assertEqual("active", ruleset["enforcement"])
        self.assertEqual([], ruleset["bypass_actors"])
        self.assertEqual({"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}, ruleset["conditions"])
        rules = {rule["type"]: rule for rule in ruleset["rules"]}
        self.assertEqual({"deletion", "non_fast_forward", "pull_request", "required_status_checks"}, set(rules))
        pull_request = rules["pull_request"]["parameters"]
        self.assertEqual(0, pull_request["required_approving_review_count"])
        self.assertTrue(pull_request["required_review_thread_resolution"])
        checks = rules["required_status_checks"]["parameters"]
        self.assertTrue(checks["strict_required_status_checks_policy"])
        self.assertEqual(
            [{"context": "GitOps Validation", "integration_id": 15368}],
            checks["required_status_checks"],
        )

    def test_renovate_uses_pull_requests_without_bypass(self):
        renovate = (ROOT / ".github/renovate.json5").read_text()
        match = re.search(r"'Auto merge Github Actions'.*?\n\s*},", renovate, re.DOTALL)
        assert match is not None
        rule = match.group(0)
        self.assertIn("automerge: true", rule)
        self.assertIn("automergeType: 'pr'", rule)
        self.assertNotIn("ignoreTests: true", rule)

    def test_repository_validation_and_recovery_are_documented(self):
        kubeconform = (ROOT / "scripts/kubeconform.sh").read_text()
        self.assertIn("test-github-protection.py", kubeconform)
        guide = (ROOT / ".github/AGENT_GITOPS_CONTRIBUTIONS.md").read_text()
        for phrase in (
            "GitOps Validation",
            "no bypass actors",
            "required_approving_review_count: 0",
            "temporarily disable the ruleset",
            "Renovate",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main(verbosity=2)
