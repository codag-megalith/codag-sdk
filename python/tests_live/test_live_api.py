"""Opt-in integration checks against the hosted Codag action-cost API.

Run with ``CODAG_API_KEY=cdk_... make test-live``. ``CODAG_SERVER`` may
override the target host.
"""

from __future__ import annotations

import os
import unittest

from codag import (
    ActionEnvelope,
    AuthenticationError,
    Codag,
    ToolCall,
    ValidationError,
)


API_KEY = os.getenv("CODAG_API_KEY", "")
FILE_LIST = "README.md\npython/src/codag/client.py\npython/tests/test_client.py"


@unittest.skipUnless(API_KEY, "CODAG_API_KEY is not set")
class LiveAPICase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Codag(timeout=60)

    def test_health_reports_ok(self):
        self.assertEqual(self.client.health().get("status"), "ok")

    def test_service_status_reports_configured_reducer(self):
        status = self.client.service_status()
        self.assertEqual(status.get("status"), "ok")
        self.assertIsInstance(status.get("reducer_configured"), bool)

    def test_action_passthrough_decodes_typed_response(self):
        response = self.client.reduce_action(ActionEnvelope(
            id="sdk-live-python-v020",
            kind="file_list",
            tool=ToolCall(name="list_files", arguments={}),
            result=FILE_LIST,
            harness="openai_compatible",
            client_version="0.2.0",
        ))
        self.assertEqual(response.action_id, "sdk-live-python-v020")
        self.assertEqual(response.kind, "file_list")
        self.assertEqual(response.decision, "passthrough")
        self.assertEqual(response.reason, "conservative_passthrough")
        self.assertEqual(response.usage["bytes_in"], len(FILE_LIST.encode("utf-8")))
        self.assertEqual(response.usage["bytes_out"], response.usage["bytes_in"])

    def test_usage_and_pricing_contracts_decode(self):
        usage = self.client.usage_summary()
        self.assertTrue(usage.period_start)
        self.assertTrue(usage.period_end)
        self.assertGreaterEqual(usage.bytes_used, 0)
        prices = self.client.model_prices()
        self.assertEqual(prices.currency, "USD")
        self.assertTrue(prices.models)

    def test_workspace_policy_decodes(self):
        policy = self.client.get_workspace_policy()
        self.assertIn(policy.mode, {"disabled", "audit", "optimize"})
        self.assertTrue(policy.required_metrics)

    def test_invalid_key_maps_to_authentication_error(self):
        bad = Codag(
            api_key="cdk_sdk_live_invalid",
            base_url=self.client.base_url,
            timeout=30,
        )
        with self.assertRaises(AuthenticationError) as raised:
            bad.service_status()
        self.assertEqual(raised.exception.status_code, 401)
        self.assertTrue(raised.exception.detail)

    def test_invalid_action_fails_before_network(self):
        with self.assertRaises(ValidationError):
            self.client.reduce_action({"id": "incomplete"})


if __name__ == "__main__":
    unittest.main()
