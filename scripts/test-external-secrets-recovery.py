#!/usr/bin/env python3
"""Contracts for bounded recovery from the 1Password SDK WASM failure."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/security/external-secrets/app"
RECOVERY = APP / "recovery.yaml"
RUNBOOK = ROOT / "docs/runbooks/monitoring/README.md"


def documents() -> list[dict]:
    return [doc for doc in yaml.safe_load_all(RECOVERY.read_text()) if doc]


def events_fixture(message: str, uid: str = "event-uid", resource_version: str = "7") -> str:
    return json.dumps(
        {
            "apiVersion": "v1",
            "items": [
                {
                    "metadata": {
                        "creationTimestamp": "2026-09-19T01:00:00Z",
                        "resourceVersion": resource_version,
                        "uid": uid,
                    },
                    "involvedObject": {"kind": "ExternalSecret"},
                    "lastTimestamp": "2026-09-19T01:01:00Z",
                    "message": message,
                    "reason": "UpdateFailed",
                    "type": "Warning",
                }
            ],
            "kind": "List",
        }
    )


def deployment_fixture(last_event: str = "", last_restart: str = "0") -> str:
    annotations = {}
    if last_event:
        annotations["external-secrets-sdk-recovery/last-event"] = last_event
    if last_restart:
        annotations["external-secrets-sdk-recovery/last-restart"] = last_restart
    return json.dumps({"metadata": {"annotations": annotations}})


class ExternalSecretsRecoveryTests(unittest.TestCase):
    def test_recovery_resources_are_gitops_managed(self):
        resources = yaml.safe_load((APP / "kustomization.yaml").read_text())["resources"]
        self.assertIn("./recovery.yaml", resources)
        by_kind = {doc["kind"]: doc for doc in documents()}
        self.assertEqual(
            {"ServiceAccount", "ConfigMap", "ClusterRole", "ClusterRoleBinding", "Role", "RoleBinding", "CronJob"},
            set(by_kind),
        )

    def test_recovery_rbac_reads_events_and_mutates_only_one_deployment(self):
        by_kind = {doc["kind"]: doc for doc in documents()}
        self.assertEqual(
            [{"apiGroups": [""], "resources": ["events"], "verbs": ["list"]}],
            by_kind["ClusterRole"]["rules"],
        )
        self.assertEqual(
            [
                {
                    "apiGroups": ["apps"],
                    "resources": ["deployments"],
                    "resourceNames": ["external-secrets-operator"],
                    "verbs": ["get", "patch"],
                }
            ],
            by_kind["Role"]["rules"],
        )
        self.assertEqual("external-secrets-sdk-recovery", by_kind["ClusterRoleBinding"]["subjects"][0]["name"])
        self.assertEqual("security", by_kind["ClusterRoleBinding"]["subjects"][0]["namespace"])
        self.assertEqual("external-secrets-sdk-recovery", by_kind["RoleBinding"]["subjects"][0]["name"])

    def test_recovery_job_is_bounded_and_hardened(self):
        cron = next(doc for doc in documents() if doc["kind"] == "CronJob")
        spec = cron["spec"]
        self.assertEqual("*/2 * * * *", spec["schedule"])
        self.assertEqual(120, spec["startingDeadlineSeconds"])
        self.assertEqual("Forbid", spec["concurrencyPolicy"])
        self.assertEqual(1, spec["successfulJobsHistoryLimit"])
        self.assertEqual(1, spec["failedJobsHistoryLimit"])
        job = spec["jobTemplate"]["spec"]
        self.assertEqual(180, job["activeDeadlineSeconds"])
        self.assertEqual(1, job["backoffLimit"])
        pod = job["template"]["spec"]
        self.assertEqual("external-secrets-sdk-recovery", pod["serviceAccountName"])
        self.assertEqual("Never", pod["restartPolicy"])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertEqual("RuntimeDefault", pod["securityContext"]["seccompProfile"]["type"])
        container = pod["containers"][0]
        self.assertRegex(
            container["image"],
            r"^docker\.io/alpine/k8s:1\.37\.0@sha256:[a-f0-9]{64}$",
        )
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(["ALL"], container["securityContext"]["capabilities"]["drop"])
        self.assertIn("requests", container["resources"])
        self.assertIn("limits", container["resources"])

    def test_recovery_is_documented_with_upstream_context_and_cooldown(self):
        runbook = RUNBOOK.read_text()
        self.assertIn("external-secrets-sdk-recovery", runbook)
        self.assertIn("external-secrets/external-secrets/issues/6941", runbook)
        self.assertIn("out of bounds memory access", runbook)
        self.assertIn("ten-minute cooldown", runbook)

    def _run_script(
        self,
        events: str,
        deployment: str | None = None,
        now: int = 1000,
        events_exit: int = 0,
        check: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        config = next(doc for doc in documents() if doc["kind"] == "ConfigMap")
        script = config["data"]["recover.sh"]
        with tempfile.TemporaryDirectory() as directory:
            directory_path = pathlib.Path(directory)
            script_path = directory_path / "recover.sh"
            script_path.write_text(script)
            kubectl_path = directory_path / "kubectl"
            kubectl_path.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$FAKE_KUBECTL_LOG\"\n"
                "if [ \"$1\" = get ] && [ \"$2\" = events ]; then\n"
                "  if [ \"$FAKE_EVENTS_EXIT\" -ne 0 ]; then exit \"$FAKE_EVENTS_EXIT\"; fi\n"
                "  printf '%s' \"$FAKE_EVENTS_JSON\"\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = -n ] && [ \"$3\" = get ]; then\n"
                "  printf '%s' \"$FAKE_DEPLOYMENT_JSON\"\n"
                "  exit 0\n"
                "fi\n"
                "exit 0\n"
            )
            kubectl_path.chmod(0o755)
            log_path = directory_path / "kubectl.log"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{directory}:{env['PATH']}",
                    "POD_NAMESPACE": "security",
                    "NOW_EPOCH": str(now),
                    "FAKE_EVENTS_EXIT": str(events_exit),
                    "FAKE_EVENTS_JSON": events,
                    "FAKE_DEPLOYMENT_JSON": deployment or deployment_fixture(),
                    "FAKE_KUBECTL_LOG": str(log_path),
                }
            )
            completed = subprocess.run(
                ["/bin/sh", str(script_path)],
                check=check,
                capture_output=True,
                text=True,
                env=env,
            )
            log = log_path.read_text().splitlines() if log_path.exists() else []
            return completed, log

    @staticmethod
    def _patch_payload(log: list[str]) -> dict:
        patch = next(line for line in log if " patch deployment " in f" {line} ")
        return json.loads(patch.split("--patch ", 1)[1])

    def test_recovery_uses_warning_event_payload_not_sanitized_status(self):
        completed, log = self._run_script(events_fixture("provider request timed out"))
        self.assertEqual(1, len(log))
        self.assertEqual(
            "get events --all-namespaces --field-selector=involvedObject.kind=ExternalSecret --output=json",
            log[0],
        )
        self.assertIn("no unrecoverable SDK failure detected", completed.stdout)

    def test_event_api_failure_fails_the_job_instead_of_reporting_healthy(self):
        completed, log = self._run_script(
            events_fixture("unused"),
            events_exit=42,
            check=False,
        )
        self.assertEqual(42, completed.returncode)
        self.assertEqual(1, len(log))
        self.assertNotIn("no unrecoverable SDK failure detected", completed.stdout)

    def test_first_wasm_event_records_state_and_rolls_controller(self):
        completed, log = self._run_script(events_fixture("wasm error: out of bounds memory access"))
        self.assertEqual(3, len(log))
        payload = self._patch_payload(log)
        annotations = payload["metadata"]["annotations"]
        self.assertEqual("event-uid:7", annotations["external-secrets-sdk-recovery/last-event"])
        self.assertEqual("1000", annotations["external-secrets-sdk-recovery/last-restart"])
        self.assertEqual(
            "1000",
            payload["spec"]["template"]["metadata"]["annotations"]["external-secrets-sdk-recovery/trigger"],
        )
        self.assertIn("controller restarted after unrecoverable SDK failure", completed.stdout)
        self.assertNotIn("out of bounds memory access", completed.stdout)

    def test_already_seen_event_does_not_restart(self):
        completed, log = self._run_script(
            events_fixture("wasm error: out of bounds memory access"),
            deployment_fixture(last_event="event-uid:7", last_restart="900"),
        )
        self.assertEqual(2, len(log))
        self.assertFalse(any(" patch " in f" {line} " for line in log))
        self.assertIn("already handled", completed.stdout)

    def test_new_event_during_cooldown_is_recorded_without_rollout(self):
        completed, log = self._run_script(
            events_fixture("wasm error: out of bounds memory access", resource_version="8"),
            deployment_fixture(last_event="event-uid:7", last_restart="950"),
        )
        payload = self._patch_payload(log)
        self.assertNotIn("spec", payload)
        self.assertEqual(
            "event-uid:8",
            payload["metadata"]["annotations"]["external-secrets-sdk-recovery/last-event"],
        )
        self.assertIn("cooldown", completed.stdout)

    def test_continued_failures_after_cooldown_trigger_one_more_rollout(self):
        _, log = self._run_script(
            events_fixture("wasm error: out of bounds memory access", resource_version="9"),
            deployment_fixture(last_event="event-uid:8", last_restart="300"),
        )
        payload = self._patch_payload(log)
        self.assertEqual(
            "1000",
            payload["spec"]["template"]["metadata"]["annotations"]["external-secrets-sdk-recovery/trigger"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
