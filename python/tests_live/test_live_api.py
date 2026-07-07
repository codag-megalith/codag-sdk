"""Live integration checks against a real Codag API server.

Opt-in: not part of `make test`. Run with an API key:

    CODAG_API_KEY=cdk_... make test-live

CODAG_SERVER overrides the target host (defaults to the hosted API).
"""

from __future__ import annotations

import os
import unittest

from codag import (
    APIError,
    AuthenticationError,
    BillingError,
    Codag,
    ValidationError,
)

API_KEY = os.getenv("CODAG_API_KEY", "")

SAMPLE_LINES = [
    "ERROR api db pool timeout active=20 waiting=30 path=/api/orders",
    "WARN api db pool nearing capacity active=18 path=/api/orders",
    "ERROR api db pool timeout active=21 waiting=31 path=/api/checkout",
    "INFO api request completed status=200 path=/api/health elapsed_ms=3",
    "ERROR worker job retry queue=email attempt=3 err=smtp_timeout",
]


@unittest.skipUnless(API_KEY, "CODAG_API_KEY is not set")
class LiveAPICase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Codag(timeout=60)

    def test_health_reports_ok(self):
        health = self.client.health()
        self.assertEqual(health.get("status"), "ok")

    def test_compact_returns_text_and_stats(self):
        result = self.client.compact(SAMPLE_LINES, service="api", level="error")
        self.assertTrue(result.text)
        self.assertGreaterEqual(result.stats.elapsed_ms, 0)
        self.assertTrue(result.compact_engine)
        self.assertEqual(result.raw["text"], result.text)

    def test_compact_accepts_records_and_metadata(self):
        result = self.client.compact(
            [{"message": line, "level": "error"} for line in SAMPLE_LINES],
            metadata={"source": "sdk-live-test"},
        )
        self.assertTrue(result.text)

    def test_capsule_returns_structured_incident(self):
        try:
            result = self.client.capsule(SAMPLE_LINES, level="error")
        except BillingError as exc:
            self.skipTest(f"workspace lacks capsule access: {exc.detail}")
        self.assertIn("schema_version", result.capsule)
        self.assertIn("incident", result.capsule)

    def test_compact_job_lifecycle(self):
        try:
            created = self.client.create_compact_job(
                SAMPLE_LINES, metadata={"source": "sdk-live-test"}
            )
        except BillingError as exc:
            self.skipTest(f"workspace lacks compact job access: {exc.detail}")
        self.assertTrue(created.job_id)
        self.assertTrue(created.poll_url.endswith(created.job_id))
        job = self.client.wait_for_compact_job(created.job_id, poll_interval=1, timeout=120)
        self.assertEqual(job.status, "succeeded", msg=f"job error: {job.error}")
        self.assertTrue(job.text)

    def test_unknown_job_maps_to_404_api_error(self):
        with self.assertRaises(APIError) as raised:
            self.client.get_compact_job("cj_sdk_live_does_not_exist")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertTrue(raised.exception.detail)

    def test_invalid_key_maps_to_authentication_error(self):
        bad = Codag(api_key="cdk_sdk_live_invalid", base_url=self.client.base_url, timeout=30)
        with self.assertRaises(AuthenticationError) as raised:
            bad.compact(SAMPLE_LINES[:1])
        self.assertEqual(raised.exception.status_code, 401)
        self.assertTrue(raised.exception.detail)

    def test_validation_fails_before_network(self):
        with self.assertRaises(ValidationError):
            self.client.compact([])


if __name__ == "__main__":
    unittest.main()
