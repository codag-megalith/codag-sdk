from __future__ import annotations

import asyncio
import json
import os
import socket
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from codag import (
    APIError,
    AsyncCodag,
    AuthenticationError,
    BillingError,
    Codag,
    CodagError,
    LineRecord,
    NetworkError,
    RateLimitError,
    ValidationError,
)
from codag.client import DEFAULT_BASE_URL, normalize_lines


ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, payload=None, raw: bytes | None = None):
        self.payload = payload
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if self.raw is not None:
            return self.raw
        return json.dumps(self.payload).encode("utf-8")


def fake_urlopen(calls, responses):
    def _open(req, timeout=0):
        payload = json.loads(req.data) if req.data else None
        headers = {key.lower(): value for key, value in req.header_items()}
        calls.append(
            {
                "method": req.get_method(),
                "url": req.full_url,
                "headers": headers,
                "authorization": req.get_header("Authorization"),
                "payload": payload,
                "timeout": timeout,
            }
        )
        spec = responses.get(req.full_url, (200, {}, {"ok": True}))
        if isinstance(spec, list):
            spec = spec.pop(0)
        if isinstance(spec, BaseException):
            raise spec
        status, headers, response = spec
        if status >= 400:
            body = response if isinstance(response, bytes) else json.dumps(response).encode("utf-8")
            raise urllib.error.HTTPError(
                req.full_url,
                status,
                "error",
                headers,
                BytesIO(body),
            )
        if isinstance(response, bytes):
            return FakeResponse(raw=response)
        return FakeResponse(response)

    return _open


class ClientCase(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = {}
        self.base_url = "http://codag.test"
        self.compact_fixture = json.loads((ROOT / "fixtures" / "compact_response.json").read_text())
        self.capsule_fixture = json.loads((ROOT / "fixtures" / "capsule_response.json").read_text())

    def queue(self, path, payload, *, status=200, headers=None):
        self.responses[self.base_url + path] = (status, headers or {}, payload)

    def run_mocked(self, fn):
        with patch("urllib.request.urlopen", fake_urlopen(self.calls, self.responses)):
            return fn()

    def test_default_base_url_is_hosted_api(self):
        client = Codag(api_key="cdk_test")
        self.assertEqual(client.base_url, DEFAULT_BASE_URL)

    def test_base_url_constructor_trims_trailing_slash(self):
        client = Codag(api_key="cdk_test", base_url="http://codag.test///")
        self.assertEqual(client.base_url, "http://codag.test")

    def test_base_url_uses_codag_server_env(self):
        old = os.environ.get("CODAG_SERVER")
        os.environ["CODAG_SERVER"] = "http://env.test/"
        try:
            client = Codag(api_key="cdk_test")
            self.assertEqual(client.base_url, "http://env.test")
        finally:
            if old is None:
                os.environ.pop("CODAG_SERVER", None)
            else:
                os.environ["CODAG_SERVER"] = old

    def test_constructor_base_url_wins_over_env(self):
        old = os.environ.get("CODAG_SERVER")
        os.environ["CODAG_SERVER"] = "http://env.test"
        try:
            client = Codag(api_key="cdk_test", base_url="http://arg.test")
            self.assertEqual(client.base_url, "http://arg.test")
        finally:
            if old is None:
                os.environ.pop("CODAG_SERVER", None)
            else:
                os.environ["CODAG_SERVER"] = old

    def test_api_key_uses_codag_api_key_env(self):
        old = os.environ.get("CODAG_API_KEY")
        os.environ["CODAG_API_KEY"] = "cdk_env"
        try:
            client = Codag(base_url=self.base_url)
            self.assertEqual(client.api_key, "cdk_env")
        finally:
            if old is None:
                os.environ.pop("CODAG_API_KEY", None)
            else:
                os.environ["CODAG_API_KEY"] = old

    def test_constructor_api_key_wins_over_env(self):
        old = os.environ.get("CODAG_API_KEY")
        os.environ["CODAG_API_KEY"] = "cdk_env"
        try:
            client = Codag(api_key="cdk_arg", base_url=self.base_url)
            self.assertEqual(client.api_key, "cdk_arg")
        finally:
            if old is None:
                os.environ.pop("CODAG_API_KEY", None)
            else:
                os.environ["CODAG_API_KEY"] = old

    def test_health_uses_get_without_auth(self):
        self.queue("/health", {"ok": True})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(client.health)
        self.assertEqual(result["ok"], True)
        self.assertEqual(self.calls[0]["method"], "GET")
        self.assertIsNone(self.calls[0]["authorization"])

    def test_health_does_not_send_content_type(self):
        self.queue("/health", {"ok": True})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(client.health)
        self.assertNotIn("content-type", self.calls[0]["headers"])

    def test_compact_uses_post_path(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(self.calls[0]["method"], "POST")
        self.assertEqual(self.calls[0]["url"], self.base_url + "/v1/compact")

    def test_compact_sends_bearer_token(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(self.calls[0]["authorization"], "Bearer cdk_test")

    def test_compact_sends_json_content_type(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(self.calls[0]["headers"]["content-type"], "application/json")

    def test_compact_sends_user_agent(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(self.calls[0]["headers"]["user-agent"], "codag-python/0.1.0")

    def test_compact_passes_timeout_to_urlopen(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url, timeout=7)
        self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(self.calls[0]["timeout"], 7)

    def test_compact_decodes_text_and_stats(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertIn("# codag compact", result.text)
        self.assertEqual(result.stats.elapsed_ms, 31)

    def test_compact_decodes_engine_fields(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(result.compact_engine, "mvp")
        self.assertIsNone(result.compact_fallback)
        self.assertIsNone(result.compact_error)

    def test_compact_keeps_raw_response(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(result.raw["compact_engine"], "mvp")

    def test_capsule_uses_post_path(self):
        self.queue("/v1/capsule", self.capsule_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.capsule(["ERROR one"]))
        self.assertEqual(self.calls[0]["url"], self.base_url + "/v1/capsule")

    def test_capsule_decodes_fixture(self):
        self.queue("/v1/capsule", self.capsule_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.capsule([{"message": "ERROR one", "level": "error"}]))
        self.assertEqual(result.capsule["schema_version"], "0.3")
        self.assertEqual(result.stats.llm_calls, 1)

    def test_capsule_sends_metadata(self):
        self.queue("/v1/capsule", self.capsule_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.capsule(["ERROR one"], metadata={"source": "pytest"}))
        self.assertEqual(self.calls[0]["payload"]["metadata"]["source"], "pytest")

    def test_create_compact_job_decodes_response(self):
        self.queue("/v1/compact/jobs", {"job_id": "cj_1", "status": "queued", "poll_url": "/v1/compact/jobs/cj_1"})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.create_compact_job(["ERROR one"]))
        self.assertEqual(result.job_id, "cj_1")
        self.assertEqual(result.status, "queued")

    def test_create_compact_job_sends_metadata(self):
        self.queue("/v1/compact/jobs", {"job_id": "cj_1", "status": "queued", "poll_url": "/v1/compact/jobs/cj_1"})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.create_compact_job(["ERROR one"], metadata={"source": "ci"}))
        self.assertEqual(self.calls[0]["payload"]["metadata"]["source"], "ci")

    def test_get_compact_job_decodes_done_response(self):
        self.queue("/v1/compact/jobs/cj_1", {"job_id": "cj_1", "status": "succeeded", "text": "ok", "stats": None})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.get_compact_job("cj_1"))
        self.assertEqual(result.text, "ok")
        self.assertIsNone(result.stats)

    def test_get_compact_job_decodes_stats(self):
        self.queue(
            "/v1/compact/jobs/cj_1",
            {"job_id": "cj_1", "status": "succeeded", "text": "ok", "stats": {"llm_calls": 0, "cache_hits": 1, "unmatched": 0, "elapsed_ms": 5}},
        )
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.get_compact_job("cj_1"))
        self.assertEqual(result.stats.cache_hits, 1)

    def test_get_compact_job_rejects_empty_id(self):
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(ValidationError):
            client.get_compact_job("")

    def test_get_compact_job_url_encodes_id(self):
        self.queue("/v1/compact/jobs/a%2Fb%20c", {"job_id": "a/b c", "status": "succeeded"})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.get_compact_job("a/b c"))
        self.assertEqual(self.calls[0]["url"], self.base_url + "/v1/compact/jobs/a%2Fb%20c")

    def test_wait_for_compact_job_returns_completed_job(self):
        self.responses[self.base_url + "/v1/compact/jobs/cj_1"] = [
            (200, {}, {"job_id": "cj_1", "status": "queued"}),
            (200, {}, {"job_id": "cj_1", "status": "succeeded", "text": "ok"}),
        ]
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.wait_for_compact_job("cj_1", poll_interval=0, timeout=1))
        self.assertEqual(result.text, "ok")
        self.assertEqual(len(self.calls), 2)

    def test_wait_for_compact_job_returns_failed_job(self):
        self.queue("/v1/compact/jobs/cj_1", {"job_id": "cj_1", "status": "failed", "error": "boom"})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.wait_for_compact_job("cj_1", poll_interval=0, timeout=1))
        self.assertEqual(result.error, "boom")

    def test_wait_for_compact_job_times_out(self):
        self.queue("/v1/compact/jobs/cj_1", {"job_id": "cj_1", "status": "queued"})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(TimeoutError):
            self.run_mocked(lambda: client.wait_for_compact_job("cj_1", poll_interval=0, timeout=0))

    def test_async_compact_wraps_sync_client(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = AsyncCodag(api_key="cdk_test", base_url=self.base_url)

        async def run():
            with patch("urllib.request.urlopen", fake_urlopen(self.calls, self.responses)):
                return await client.compact(["ERROR one"])

        result = asyncio.run(run())
        self.assertEqual(result.stats.elapsed_ms, 31)

    def test_async_health_wraps_sync_client(self):
        self.queue("/health", {"ok": True})
        client = AsyncCodag(api_key="cdk_test", base_url=self.base_url)

        async def run():
            with patch("urllib.request.urlopen", fake_urlopen(self.calls, self.responses)):
                return await client.health()

        result = asyncio.run(run())
        self.assertEqual(result["ok"], True)

    def test_async_wait_polls_without_blocking_a_thread(self):
        # The async wait loop runs on the event loop (asyncio.sleep), only
        # offloading individual HTTP calls, so it must transition queued -> done.
        self.responses[self.base_url + "/v1/compact/jobs/cj_1"] = [
            (200, {}, {"job_id": "cj_1", "status": "queued"}),
            (200, {}, {"job_id": "cj_1", "status": "succeeded", "text": "ok"}),
        ]
        client = AsyncCodag(api_key="cdk_test", base_url=self.base_url)

        async def run():
            with patch("urllib.request.urlopen", fake_urlopen(self.calls, self.responses)):
                return await client.wait_for_compact_job("cj_1", poll_interval=0, timeout=5)

        result = asyncio.run(run())
        self.assertEqual(result.text, "ok")
        self.assertEqual(len(self.calls), 2)

    def test_async_wait_times_out(self):
        self.queue("/v1/compact/jobs/cj_1", {"job_id": "cj_1", "status": "queued"})
        client = AsyncCodag(api_key="cdk_test", base_url=self.base_url)

        async def run():
            with patch("urllib.request.urlopen", fake_urlopen(self.calls, self.responses)):
                return await client.wait_for_compact_job("cj_1", poll_interval=0, timeout=0)

        with self.assertRaises(TimeoutError):
            asyncio.run(run())

    def test_normalize_string_assigns_line_ids(self):
        records = normalize_lines(["a", "b"])
        self.assertEqual([r["line_id"] for r in records], [0, 1])

    def test_normalize_string_uses_default_level(self):
        records = normalize_lines(["a"])
        self.assertEqual(records[0]["level"], "info")

    def test_normalize_string_uses_custom_level(self):
        records = normalize_lines(["a"], level="error")
        self.assertEqual(records[0]["level"], "error")

    def test_normalize_string_applies_service(self):
        records = normalize_lines(["a"], service="api")
        self.assertEqual(records[0]["service"], "api")

    def test_normalize_dict_assigns_line_id_when_missing(self):
        records = normalize_lines([{"message": "a"}])
        self.assertEqual(records[0]["line_id"], 0)

    def test_normalize_dict_preserves_line_id(self):
        records = normalize_lines([{"line_id": 99, "message": "a"}])
        self.assertEqual(records[0]["line_id"], 99)

    def test_normalize_dict_assigns_default_level(self):
        records = normalize_lines([{"message": "a"}])
        self.assertEqual(records[0]["level"], "info")

    def test_normalize_dict_preserves_level(self):
        records = normalize_lines([{"message": "a", "level": "warn"}])
        self.assertEqual(records[0]["level"], "warn")

    def test_normalize_dict_fills_missing_service(self):
        records = normalize_lines([{"message": "a"}], service="api")
        self.assertEqual(records[0]["service"], "api")

    def test_normalize_dict_does_not_override_service(self):
        records = normalize_lines([{"message": "a", "service": "worker"}], service="api")
        self.assertEqual(records[0]["service"], "worker")

    def test_normalize_line_record_to_json(self):
        records = normalize_lines([LineRecord(line_id=7, message="a", level="warn", service="api")])
        self.assertEqual(records[0]["line_id"], 7)
        self.assertEqual(records[0]["service"], "api")

    def test_normalize_line_record_applies_service_when_missing(self):
        records = normalize_lines([LineRecord(line_id=1, message="a")], service="api")
        self.assertEqual(records[0]["service"], "api")

    def test_normalize_preserves_timestamp(self):
        records = normalize_lines([{"message": "a", "timestamp": "2026-07-01T00:00:00Z"}])
        self.assertEqual(records[0]["timestamp"], "2026-07-01T00:00:00Z")

    def test_normalize_rejects_empty_lines(self):
        with self.assertRaises(ValidationError):
            normalize_lines([])

    def test_normalize_rejects_too_many_lines(self):
        with self.assertRaises(ValidationError):
            normalize_lines(["x"] * 20_001)

    def test_normalize_rejects_too_long_line(self):
        with self.assertRaises(ValidationError):
            normalize_lines(["x" * (256 * 1024 + 1)])

    def test_normalize_rejects_invalid_item_type(self):
        with self.assertRaises(ValidationError):
            normalize_lines([object()])

    def test_normalize_rejects_missing_message(self):
        with self.assertRaises(ValidationError):
            normalize_lines([{"level": "error"}])

    def test_normalize_rejects_non_string_message(self):
        with self.assertRaises(ValidationError):
            normalize_lines([{"message": 123}])

    def test_normalize_rejects_bare_string(self):
        # A bare string is iterable; it must be rejected, not split into
        # one record per character (parity with the TS/Go clients).
        with self.assertRaises(ValidationError):
            normalize_lines("error: db down")

    def test_normalize_rejects_bare_bytes(self):
        with self.assertRaises(ValidationError):
            normalize_lines(b"error: db down")

    def test_stats_coerces_null_fields_to_zero(self):
        # The server may send explicit null for optional counters; int(None)
        # would otherwise crash instead of decoding cleanly.
        self.queue(
            "/v1/compact",
            {"text": "ok", "stats": {"llm_calls": None, "cache_hits": None, "unmatched": 0, "elapsed_ms": None}},
        )
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(result.stats.llm_calls, 0)
        self.assertEqual(result.stats.cache_hits, 0)
        self.assertEqual(result.stats.elapsed_ms, 0)

    def test_request_includes_metadata(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.compact(["ERROR one"], metadata={"source": "unit"}))
        self.assertEqual(self.calls[0]["payload"]["metadata"]["source"], "unit")

    def test_request_omits_metadata_when_none(self):
        self.queue("/v1/compact", self.compact_fixture)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertNotIn("metadata", self.calls[0]["payload"])

    def test_request_rejects_metadata_over_limit(self):
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(ValidationError):
            client.compact(["ERROR one"], metadata={"x": "y" * (64 * 1024)})

    def test_missing_api_key_fails_before_request(self):
        old = os.environ.pop("CODAG_API_KEY", None)
        try:
            client = Codag(base_url=self.base_url)
            with self.assertRaises(AuthenticationError):
                client.compact(["ERROR one"])
            self.assertEqual(self.calls, [])
        finally:
            if old is not None:
                os.environ["CODAG_API_KEY"] = old

    def test_401_maps_to_authentication_error(self):
        self.queue("/v1/compact", {"detail": "invalid API key"}, status=401)
        client = Codag(api_key="cdk_bad", base_url=self.base_url)
        with self.assertRaises(AuthenticationError) as raised:
            self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(raised.exception.detail, "invalid API key")

    def test_402_maps_to_billing_error(self):
        self.queue("/v1/capsule", {"detail": "billing_required"}, status=402, headers={"X-Codag-Upgrade": "/dashboard/billing"})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(BillingError) as raised:
            self.run_mocked(lambda: client.capsule(["ERROR one"]))
        self.assertEqual(raised.exception.upgrade_path, "/dashboard/billing")

    def test_429_maps_to_rate_limit_error(self):
        self.queue("/v1/compact", {"detail": "mvp_sync_overloaded"}, status=429, headers={"Retry-After": "5"})
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(RateLimitError) as raised:
            self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(raised.exception.retry_after, "5")

    def test_500_maps_to_api_error(self):
        self.queue("/v1/compact", {"detail": "server_error"}, status=500)
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(APIError) as raised:
            self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(raised.exception.status_code, 500)

    def test_plain_error_body_becomes_detail(self):
        self.responses[self.base_url + "/v1/compact"] = (500, {}, b"plain failure")
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(APIError) as raised:
            self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertEqual(raised.exception.detail, "plain failure")

    def test_network_error_maps_to_network_error(self):
        self.responses[self.base_url + "/v1/compact"] = urllib.error.URLError("refused")
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(NetworkError):
            self.run_mocked(lambda: client.compact(["ERROR one"]))

    def test_url_timeout_maps_to_timed_out_message(self):
        self.responses[self.base_url + "/v1/compact"] = urllib.error.URLError(socket.timeout("timed out"))
        client = Codag(api_key="cdk_test", base_url=self.base_url, timeout=5)
        with self.assertRaises(NetworkError) as raised:
            self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertIn("timed out after 5s", str(raised.exception))

    def test_socket_timeout_maps_to_timed_out_message(self):
        self.responses[self.base_url + "/v1/compact"] = socket.timeout("timed out")
        client = Codag(api_key="cdk_test", base_url=self.base_url, timeout=5)
        with self.assertRaises(NetworkError) as raised:
            self.run_mocked(lambda: client.compact(["ERROR one"]))
        self.assertIn("timed out after 5s", str(raised.exception))

    def test_normalize_accepts_generator_input(self):
        records = normalize_lines(line for line in ["a", "b"])
        self.assertEqual([r["line_id"] for r in records], [0, 1])

    def test_invalid_success_json_raises_codag_error(self):
        self.responses[self.base_url + "/v1/compact"] = (200, {}, b"{not-json")
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        with self.assertRaises(CodagError):
            self.run_mocked(lambda: client.compact(["ERROR one"]))

    def test_empty_success_body_returns_empty_dict_for_health(self):
        self.responses[self.base_url + "/health"] = (200, {}, b"")
        client = Codag(api_key="cdk_test", base_url=self.base_url)
        result = self.run_mocked(client.health)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
