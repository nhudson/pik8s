#!/usr/bin/env python3
"""Contract tests for redacted relay upstream diagnostics."""
import contextlib
import io
import os
import pathlib
import unittest
import urllib.error
from unittest.mock import patch

import yaml

APP = pathlib.Path(__file__).resolve().parents[1] / "kubernetes/apps/monitoring/kube-prometheus-stack/app"
SOURCE = yaml.safe_load((APP / "relay-configmap.yaml").read_text())["data"]["relay.py"]
# Do not launch the production listener while loading its handler for tests.
namespace = {"__name__": "relay_contract_test"}
exec(SOURCE.rsplit("ThreadingHTTPServer((", 1)[0], namespace)
Handler = namespace["Handler"]


class RelayDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(Handler)
        self.handler.path = "/alerts"
        self.handler.headers = {"Content-Length": "13", "Authorization": "Bearer dummy-token"}
        self.handler.rfile = io.BytesIO(b'{"alerts":[]}')
        self.replies = []
        self.handler.reply = lambda status, payload: self.replies.append((status, payload))
        self.env = patch.dict(os.environ, {
            "RELAY_BEARER_TOKEN": "dummy-token",
            "HERMES_WEBHOOK_SECRET": "dummy-secret",
            "HERMES_WEBHOOK_URL": "https://invalid.example/webhooks/dummy-private-route",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_http_failure_logs_only_status_not_upstream_details(self):
        error = urllib.error.HTTPError(os.environ["HERMES_WEBHOOK_URL"], 503, "dummy-token", {}, None)
        output = io.StringIO()
        with patch.object(namespace["urllib"].request, "urlopen", side_effect=error), contextlib.redirect_stderr(output):
            self.handler.do_POST()
        self.assertEqual(502, self.replies[0][0])
        self.assertIn("upstream_http_error status=503", output.getvalue())
        for private in ("dummy-token", "dummy-secret", "dummy-private-route", "invalid.example"):
            self.assertNotIn(private, output.getvalue())

    def test_network_failure_logs_class_not_message(self):
        error = urllib.error.URLError("dummy-token cannot reach dummy-private-route")
        output = io.StringIO()
        with patch.object(namespace["urllib"].request, "urlopen", side_effect=error), contextlib.redirect_stderr(output):
            self.handler.do_POST()
        self.assertEqual(502, self.replies[0][0])
        self.assertIn("upstream_transport_error type=URLError", output.getvalue())
        self.assertNotIn("dummy-token", output.getvalue())
        self.assertNotIn("dummy-private-route", output.getvalue())


if __name__ == "__main__":
    unittest.main()
