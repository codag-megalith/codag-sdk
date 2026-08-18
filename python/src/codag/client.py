from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional, Union


DEFAULT_BASE_URL = "https://api.codag.ai"
MAX_LOG_LINES = 20_000
MAX_LOG_LINE_CHARS = 256 * 1024
MAX_METADATA_JSON_BYTES = 64 * 1024
USER_AGENT = "codag-python/0.2.0"
METRIC_FIELDS = frozenset({
    "id", "occurred_at", "session_id", "install_id", "harness", "provider", "model",
    "action_kind", "decision", "reason", "original_bytes", "replacement_bytes",
    "provider_input_tokens", "provider_output_tokens", "provider_cache_read_tokens",
    "provider_cache_write_tokens", "estimated_cost_microusd", "reducer_cost_microusd",
    "elapsed_ms", "turn_count", "retry_count", "reread_count", "retrieval_count",
    "client_version",
})
METRIC_ID = re.compile(r"^[A-Za-z0-9_.:@+~-]*$")
METRIC_SLUG = re.compile(r"^[A-Za-z0-9_.:+-]*$")
METRIC_TOKEN_LIMITS = {
    "id": (128, METRIC_ID), "session_id": (256, METRIC_ID),
    "install_id": (256, METRIC_ID), "harness": (128, METRIC_SLUG),
    "provider": (128, METRIC_SLUG), "model": (256, METRIC_SLUG),
    "decision": (64, METRIC_SLUG), "reason": (256, METRIC_SLUG),
    "client_version": (128, METRIC_SLUG),
}


class CodagError(Exception):
    """Base class for SDK errors."""


class ValidationError(CodagError):
    """Raised before a request when input cannot be serialized safely."""


class NetworkError(CodagError):
    """Raised when the API server cannot be reached."""


class APIError(CodagError):
    """Raised for non-2xx API responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: str = "",
        detail: str = "",
        retry_after: Optional[str] = None,
        upgrade_path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.detail = detail
        self.retry_after = retry_after
        self.upgrade_path = upgrade_path


class AuthenticationError(APIError):
    """Raised for missing, invalid, or rejected credentials."""


class BillingError(APIError):
    """Raised when a billing action is required."""


class RateLimitError(APIError):
    """Raised when Codag is rate limited or temporarily overloaded."""


@dataclass(frozen=True)
class LineRecord:
    line_id: int
    message: str
    level: str = "info"
    timestamp: Optional[str] = None
    service: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "line_id": self.line_id,
            "message": self.message,
            "level": self.level,
        }
        if self.timestamp is not None:
            out["timestamp"] = self.timestamp
        if self.service is not None:
            out["service"] = self.service
        return out


@dataclass(frozen=True)
class ParseStats:
    llm_calls: int
    cache_hits: int
    unmatched: int
    elapsed_ms: int
    incident_family_hits: int = 0
    incident_induced_templates: int = 0
    global_cache_hits: int = 0
    global_shadow_hits: int = 0
    global_shadow_agreements: int = 0
    global_shadow_disagreements: int = 0
    total_patterns: int = 0
    candidate_patterns: int = 0
    dropped_patterns: int = 0
    cache_pattern_hits: int = 0
    global_cache_pattern_hits: int = 0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParseStats":
        # Coerce missing OR explicit-null fields to 0 (the server may send null
        # for optional counters); int(None) would otherwise raise TypeError.
        def field(name: str) -> int:
            return int(value.get(name) or 0)

        return cls(
            llm_calls=field("llm_calls"),
            cache_hits=field("cache_hits"),
            unmatched=field("unmatched"),
            elapsed_ms=field("elapsed_ms"),
            incident_family_hits=field("incident_family_hits"),
            incident_induced_templates=field("incident_induced_templates"),
            global_cache_hits=field("global_cache_hits"),
            global_shadow_hits=field("global_shadow_hits"),
            global_shadow_agreements=field("global_shadow_agreements"),
            global_shadow_disagreements=field("global_shadow_disagreements"),
            total_patterns=field("total_patterns"),
            candidate_patterns=field("candidate_patterns"),
            dropped_patterns=field("dropped_patterns"),
            cache_pattern_hits=field("cache_pattern_hits"),
            global_cache_pattern_hits=field("global_cache_pattern_hits"),
        )


@dataclass(frozen=True)
class CompactResponse:
    text: str
    stats: ParseStats
    compact_engine: Optional[str] = None
    compact_fallback: Optional[str] = None
    compact_error: Optional[str] = None
    raw: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompactResponse":
        return cls(
            text=str(value.get("text", "")),
            stats=ParseStats.from_dict(value.get("stats", {})),
            compact_engine=value.get("compact_engine"),
            compact_fallback=value.get("compact_fallback"),
            compact_error=value.get("compact_error"),
            raw=dict(value),
        )


@dataclass(frozen=True)
class CapsuleResponse:
    capsule: Mapping[str, Any]
    stats: ParseStats
    raw: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapsuleResponse":
        return cls(
            capsule=dict(value.get("capsule", {})),
            stats=ParseStats.from_dict(value.get("stats", {})),
            raw=dict(value),
        )


@dataclass(frozen=True)
class CompactJobCreateResponse:
    job_id: str
    status: str
    poll_url: str
    raw: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompactJobCreateResponse":
        return cls(
            job_id=str(value.get("job_id", "")),
            status=str(value.get("status", "")),
            poll_url=str(value.get("poll_url", "")),
            raw=dict(value),
        )


@dataclass(frozen=True)
class CompactJobResponse:
    job_id: str
    status: str
    text: Optional[str] = None
    stats: Optional[ParseStats] = None
    error: Optional[str] = None
    raw: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompactJobResponse":
        raw_stats = value.get("stats")
        return cls(
            job_id=str(value.get("job_id", "")),
            status=str(value.get("status", "")),
            text=value.get("text"),
            stats=ParseStats.from_dict(raw_stats) if isinstance(raw_stats, Mapping) else None,
            error=value.get("error"),
            raw=dict(value),
        )


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Any = None
    id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass(frozen=True)
class ActionEnvelope:
    id: str
    kind: str
    tool: ToolCall
    result: str
    session_id: str = ""
    harness: str = ""
    provider: str = ""
    model: str = ""
    task: str = ""
    intent: str = ""
    retrieval_handle: str = ""
    client_version: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "harness": self.harness,
            "provider": self.provider,
            "model": self.model,
            "kind": self.kind,
            "tool": self.tool.to_json(),
            "result": self.result,
            "task": self.task,
            "intent": self.intent,
            "retrieval_handle": self.retrieval_handle,
            "client_version": self.client_version,
        }


@dataclass(frozen=True)
class Selector:
    id: str
    type: str
    label: str = ""
    start: int = 0
    end: int = 0
    json_path: str = ""
    group: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Selector":
        return cls(
            id=str(value.get("id", "")),
            type=str(value.get("type", "")),
            label=str(value.get("label", "")),
            start=int(value.get("start") or 0),
            end=int(value.get("end") or 0),
            json_path=str(value.get("json_path", "")),
            group=str(value.get("group", "")),
        )


@dataclass(frozen=True)
class ActionResponse:
    action_id: str
    kind: str
    decision: str
    content: str
    reason: str
    selectors: tuple[Selector, ...]
    usage: Mapping[str, int]
    raw: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActionResponse":
        return cls(
            action_id=str(value.get("action_id", "")),
            kind=str(value.get("kind", "")),
            decision=str(value.get("decision", "")),
            content=str(value.get("content", "")),
            reason=str(value.get("reason", "")),
            selectors=tuple(Selector.from_dict(row) for row in value.get("selectors", [])),
            usage=dict(value.get("usage", {})),
            raw=dict(value),
        )


@dataclass(frozen=True)
class UsageSummary:
    period_start: str
    period_end: str
    plan_tier: str
    bytes_used: int
    bytes_included: int
    observed_tokens: int
    avoided_tokens: int
    estimated_provider_spend_microusd: int
    estimated_saved_microusd: int
    by_action: Mapping[str, Any]
    equivalent_savings_microusd: Mapping[str, int]
    raw: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UsageSummary":
        return cls(
            period_start=str(value.get("period_start", "")),
            period_end=str(value.get("period_end", "")),
            plan_tier=str(value.get("plan_tier", "")),
            bytes_used=int(value.get("bytes_used") or 0),
            bytes_included=int(value.get("bytes_included") or 0),
            observed_tokens=int(value.get("observed_tokens") or 0),
            avoided_tokens=int(value.get("avoided_tokens") or 0),
            estimated_provider_spend_microusd=int(
                value.get("estimated_provider_spend_microusd") or 0
            ),
            estimated_saved_microusd=int(value.get("estimated_saved_microusd") or 0),
            by_action=dict(value.get("by_action", {})),
            equivalent_savings_microusd=dict(value.get("equivalent_savings_microusd", {})),
            raw=dict(value),
        )


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model_pattern: str
    input_usd_per_mtok: float
    cached_input_usd_per_mtok: float
    cache_write_usd_per_mtok: float
    output_usd_per_mtok: float
    as_of: str
    source_url: str = ""
    cache_write_basis: str = ""
    price_valid_through: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelPrice":
        return cls(
            provider=str(value.get("provider", "")),
            model_pattern=str(value.get("model_pattern", "")),
            input_usd_per_mtok=float(value.get("input_usd_per_mtok") or 0),
            cached_input_usd_per_mtok=float(value.get("cached_input_usd_per_mtok") or 0),
            cache_write_usd_per_mtok=float(value.get("cache_write_usd_per_mtok") or 0),
            output_usd_per_mtok=float(value.get("output_usd_per_mtok") or 0),
            as_of=str(value.get("as_of", "")),
            source_url=str(value.get("source_url", "")),
            cache_write_basis=str(value.get("cache_write_basis", "")),
            price_valid_through=str(value.get("price_valid_through", "")),
        )


@dataclass(frozen=True)
class ModelPriceCatalog:
    currency: str
    unit: str
    models: tuple[ModelPrice, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelPriceCatalog":
        return cls(
            currency=str(value.get("currency", "")),
            unit=str(value.get("unit", "")),
            models=tuple(ModelPrice.from_dict(row) for row in value.get("models", [])),
        )


@dataclass(frozen=True)
class WorkspacePolicy:
    mode: str
    enabled_actions: tuple[str, ...] = ()
    required_metrics: bool = True
    pinned_client_version: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "enabled_actions": list(self.enabled_actions),
            "required_metrics": self.required_metrics,
            "pinned_client_version": self.pinned_client_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkspacePolicy":
        return cls(
            mode=str(value.get("mode", "audit")),
            enabled_actions=tuple(str(item) for item in value.get("enabled_actions", [])),
            required_metrics=bool(value.get("required_metrics", True)),
            pinned_client_version=str(value.get("pinned_client_version", "")),
        )


LineInput = Union[str, Mapping[str, Any], LineRecord]


class Codag:
    """Synchronous client for the Codag hosted API.

    Credentials resolve from the ``api_key`` argument, then ``CODAG_API_KEY``.
    The base URL resolves from ``base_url``, then ``CODAG_SERVER``, then the
    hosted default.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("CODAG_API_KEY", "")
        self.base_url = (base_url or os.getenv("CODAG_SERVER") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    def compact(
        self,
        lines: Sequence[LineInput],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        service: Optional[str] = None,
        level: str = "info",
    ) -> CompactResponse:
        """Compress log lines into compact text via ``POST /v1/compact``."""
        payload = _build_payload(lines, metadata=metadata, service=service, level=level)
        data = self._request_json("POST", "/v1/compact", payload, auth=True)
        return CompactResponse.from_dict(data)

    def capsule(
        self,
        lines: Sequence[LineInput],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        service: Optional[str] = None,
        level: str = "info",
    ) -> CapsuleResponse:
        """Build a structured incident capsule via ``POST /v1/capsule``.

        .. deprecated::
            ``/v1/capsule`` is now a Codag-internal, admin-only endpoint.
            Non-admin callers receive a 404. Use :meth:`compact`
            (``POST /v1/compact``) instead, which is the supported public
            product surface. This method is retained for backward
            compatibility and internal/admin use.
        """
        warnings.warn(
            "Codag.capsule() is deprecated: /v1/capsule is now internal/admin-only "
            "and returns 404 for non-admin callers. Use Codag.compact() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        payload = _build_payload(lines, metadata=metadata, service=service, level=level)
        data = self._request_json("POST", "/v1/capsule", payload, auth=True)
        return CapsuleResponse.from_dict(data)

    def create_compact_job(
        self,
        lines: Sequence[LineInput],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        service: Optional[str] = None,
        level: str = "info",
    ) -> CompactJobCreateResponse:
        """Start an async compact job via ``POST /v1/compact/jobs``."""
        payload = _build_payload(lines, metadata=metadata, service=service, level=level)
        data = self._request_json("POST", "/v1/compact/jobs", payload, auth=True)
        return CompactJobCreateResponse.from_dict(data)

    def get_compact_job(self, job_id: str) -> CompactJobResponse:
        """Fetch the current state of a compact job."""
        if not job_id:
            raise ValidationError("job_id must not be empty")
        quoted = urllib.parse.quote(job_id, safe="")
        data = self._request_json("GET", f"/v1/compact/jobs/{quoted}", None, auth=True)
        return CompactJobResponse.from_dict(data)

    def wait_for_compact_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> CompactJobResponse:
        """Poll a compact job until it leaves the queued/running states.

        Terminal statuses are ``succeeded`` and ``failed``. Raises the builtin
        :class:`TimeoutError` if the job does not finish within ``timeout``.
        """
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_compact_job(job_id)
            if job.status not in {"queued", "running"}:
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(f"compact job {job_id} did not finish within {timeout:g}s")
            time.sleep(poll_interval)

    def reduce_action(self, envelope: Union[ActionEnvelope, Mapping[str, Any]]) -> ActionResponse:
        """Reduce one action result without cloud retention of its content."""
        payload = envelope.to_json() if isinstance(envelope, ActionEnvelope) else dict(envelope)
        if not payload.get("id") or not payload.get("kind") or not payload.get("result"):
            raise ValidationError("action requires id, kind, tool, and result")
        if not isinstance(payload.get("tool"), Mapping):
            raise ValidationError("action tool must be a ToolCall or mapping")
        data = self._request_json("POST", "/v1/actions/reduce", payload, auth=True)
        return ActionResponse.from_dict(data)

    def send_metrics(self, events: Sequence[Mapping[str, Any]]) -> int:
        """Send required contentless accounting events as a deduplicated batch."""
        if not events or len(events) > 1000:
            raise ValidationError("events must contain 1 through 1000 contentless metrics")
        clean = []
        for event in events:
            if not isinstance(event, Mapping) or not event.get("id") or not event.get("occurred_at"):
                raise ValidationError("each metric requires id and occurred_at")
            extra = set(event) - METRIC_FIELDS
            if extra:
                raise ValidationError("metric contains unsupported fields: " + ", ".join(sorted(extra)))
            for name, (maximum, pattern) in METRIC_TOKEN_LIMITS.items():
                value = event.get(name, "")
                if not isinstance(value, str) or len(value) > maximum or pattern.fullmatch(value) is None:
                    raise ValidationError(
                        "metric identifiers and labels must be bounded contentless tokens"
                    )
            clean.append(dict(event))
        data = self._request_json("POST", "/v1/metrics/batch", {"events": clean}, auth=True)
        return int(data.get("accepted") or 0)

    def usage_summary(self) -> UsageSummary:
        return UsageSummary.from_dict(self._request_json("GET", "/v1/usage/summary", None, auth=True))

    def usage_timeseries(self, *, days: int = 30) -> Mapping[str, Any]:
        return self._request_json("GET", f"/v1/usage/timeseries?days={_days(days)}", None, auth=True)

    def usage_breakdown(self, *, dimension: str = "action", days: int = 30) -> Mapping[str, Any]:
        allowed = {"action", "provider", "model", "harness", "member"}
        if dimension not in allowed:
            raise ValidationError(f"dimension must be one of {', '.join(sorted(allowed))}")
        query = urllib.parse.urlencode({"dimension": dimension, "days": _days(days)})
        return self._request_json("GET", f"/v1/usage/breakdown?{query}", None, auth=True)

    def usage_reliability(self, *, days: int = 30) -> Mapping[str, Any]:
        return self._request_json("GET", f"/v1/usage/reliability?days={_days(days)}", None, auth=True)

    def trial_report(self) -> Mapping[str, Any]:
        return self._request_json("GET", "/v1/trials/report", None, auth=True)

    def model_prices(self) -> ModelPriceCatalog:
        return ModelPriceCatalog.from_dict(
            self._request_json("GET", "/v1/model-prices", None, auth=True)
        )

    def get_workspace_policy(self) -> WorkspacePolicy:
        data = self._request_json("GET", "/v1/workspace/policy", None, auth=True)
        return WorkspacePolicy.from_dict(data)

    def set_workspace_policy(self, policy: WorkspacePolicy) -> WorkspacePolicy:
        data = self._request_json("PUT", "/v1/workspace/policy", policy.to_json(), auth=True)
        return WorkspacePolicy.from_dict(data)

    def service_status(self) -> Mapping[str, Any]:
        return self._request_json("GET", "/v1/service/status", None, auth=True)

    def health(self) -> Mapping[str, Any]:
        """Unauthenticated ``GET /health``."""
        return self._request_json("GET", "/health", None, auth=False)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Mapping[str, Any]],
        *,
        auth: bool,
    ) -> Mapping[str, Any]:
        if auth and not self.api_key:
            raise AuthenticationError(
                "missing Codag API key; pass api_key or set CODAG_API_KEY",
                status_code=401,
            )

        data: Optional[bytes] = None
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                if not body:
                    return {}
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise _error_for_response(
                status_code=exc.code,
                body=body,
                retry_after=exc.headers.get("Retry-After"),
                upgrade_path=exc.headers.get("X-Codag-Upgrade"),
            ) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise NetworkError(
                    f"request to {self.base_url} timed out after {self.timeout:g}s"
                ) from exc
            raise NetworkError(f"cannot reach Codag server at {self.base_url}: {exc}") from exc
        except socket.timeout as exc:
            raise NetworkError(
                f"request to {self.base_url} timed out after {self.timeout:g}s"
            ) from exc
        except json.JSONDecodeError as exc:
            raise CodagError(f"Codag returned invalid JSON: {exc}") from exc


class AsyncCodag:
    """Async convenience wrapper around the dependency-free sync client."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        self._sync = Codag(api_key=api_key, base_url=base_url, timeout=timeout)

    async def compact(
        self,
        lines: Sequence[LineInput],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        service: Optional[str] = None,
        level: str = "info",
    ) -> CompactResponse:
        """Compress log lines into compact text via ``POST /v1/compact``."""
        return await asyncio.to_thread(
            self._sync.compact, lines, metadata=metadata, service=service, level=level
        )

    async def capsule(
        self,
        lines: Sequence[LineInput],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        service: Optional[str] = None,
        level: str = "info",
    ) -> CapsuleResponse:
        """Build a structured incident capsule via ``POST /v1/capsule``.

        .. deprecated::
            ``/v1/capsule`` is now a Codag-internal, admin-only endpoint.
            Non-admin callers receive a 404. Use :meth:`compact`
            (``POST /v1/compact``) instead, which is the supported public
            product surface. This method is retained for backward
            compatibility and internal/admin use.
        """
        warnings.warn(
            "AsyncCodag.capsule() is deprecated: /v1/capsule is now internal/admin-only "
            "and returns 404 for non-admin callers. Use AsyncCodag.compact() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await asyncio.to_thread(
            self._sync.capsule, lines, metadata=metadata, service=service, level=level
        )

    async def create_compact_job(
        self,
        lines: Sequence[LineInput],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        service: Optional[str] = None,
        level: str = "info",
    ) -> CompactJobCreateResponse:
        """Start an async compact job via ``POST /v1/compact/jobs``."""
        return await asyncio.to_thread(
            self._sync.create_compact_job, lines, metadata=metadata, service=service, level=level
        )

    async def get_compact_job(self, job_id: str) -> CompactJobResponse:
        """Fetch the current state of a compact job."""
        return await asyncio.to_thread(self._sync.get_compact_job, job_id)

    async def wait_for_compact_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> CompactJobResponse:
        """Poll a compact job until it leaves the queued/running states.

        Runs the poll loop on the event loop with ``asyncio.sleep`` so a long
        wait does not occupy a thread-pool worker for its full duration (only
        the individual HTTP requests are offloaded via ``get_compact_job``).
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            job = await self.get_compact_job(job_id)
            if job.status not in {"queued", "running"}:
                return job
            if loop.time() >= deadline:
                raise TimeoutError(f"compact job {job_id} did not finish within {timeout:g}s")
            await asyncio.sleep(poll_interval)

    async def reduce_action(self, envelope: Union[ActionEnvelope, Mapping[str, Any]]) -> ActionResponse:
        return await asyncio.to_thread(self._sync.reduce_action, envelope)

    async def send_metrics(self, events: Sequence[Mapping[str, Any]]) -> int:
        return await asyncio.to_thread(self._sync.send_metrics, events)

    async def usage_summary(self) -> UsageSummary:
        return await asyncio.to_thread(self._sync.usage_summary)

    async def usage_timeseries(self, *, days: int = 30) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._sync.usage_timeseries, days=days)

    async def usage_breakdown(self, *, dimension: str = "action", days: int = 30) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._sync.usage_breakdown, dimension=dimension, days=days)

    async def usage_reliability(self, *, days: int = 30) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._sync.usage_reliability, days=days)

    async def trial_report(self) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._sync.trial_report)

    async def model_prices(self) -> ModelPriceCatalog:
        return await asyncio.to_thread(self._sync.model_prices)

    async def get_workspace_policy(self) -> WorkspacePolicy:
        return await asyncio.to_thread(self._sync.get_workspace_policy)

    async def set_workspace_policy(self, policy: WorkspacePolicy) -> WorkspacePolicy:
        return await asyncio.to_thread(self._sync.set_workspace_policy, policy)

    async def service_status(self) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._sync.service_status)

    async def health(self) -> Mapping[str, Any]:
        """Unauthenticated ``GET /health``."""
        return await asyncio.to_thread(self._sync.health)


def _build_payload(
    lines: Sequence[LineInput],
    *,
    metadata: Optional[Mapping[str, Any]],
    service: Optional[str],
    level: str,
) -> dict[str, Any]:
    records = normalize_lines(lines, service=service, level=level)
    payload: dict[str, Any] = {"lines": records}
    if metadata is not None:
        encoded = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_METADATA_JSON_BYTES:
            raise ValidationError(f"metadata exceeds {MAX_METADATA_JSON_BYTES} bytes")
        payload["metadata"] = dict(metadata)
    return payload


def _days(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 90:
        raise ValidationError("days must be an integer from 1 through 90")
    return value


def normalize_lines(
    lines: Sequence[LineInput],
    *,
    service: Optional[str] = None,
    level: str = "info",
) -> list[dict[str, Any]]:
    """Normalize strings, dicts, or LineRecords into wire-format records."""
    if isinstance(lines, (str, bytes)):
        # A bare string is iterable; without this guard list("abc") would be
        # silently split into one record per character.
        raise ValidationError("lines must be a sequence of strings, dicts, or LineRecords, not a single string")
    lines = list(lines)
    if len(lines) == 0:
        raise ValidationError("lines must not be empty")
    if len(lines) > MAX_LOG_LINES:
        raise ValidationError(f"lines exceeds {MAX_LOG_LINES}")

    out: list[dict[str, Any]] = []
    for i, item in enumerate(lines):
        if isinstance(item, str):
            record = LineRecord(line_id=i, message=item, level=level, service=service).to_json()
        elif isinstance(item, LineRecord):
            record = item.to_json()
            if service is not None and "service" not in record:
                record["service"] = service
        elif isinstance(item, Mapping):
            record = dict(item)
            record.setdefault("line_id", i)
            record.setdefault("level", level)
            if service is not None and not record.get("service"):
                record["service"] = service
        else:
            raise ValidationError(f"line {i} must be a string, dict, or LineRecord")

        if "message" not in record or not isinstance(record["message"], str):
            raise ValidationError(f"line {i} is missing string field 'message'")
        if len(record["message"]) > MAX_LOG_LINE_CHARS:
            raise ValidationError(f"line {i} exceeds {MAX_LOG_LINE_CHARS} characters")
        out.append(record)
    return out


def _error_for_response(
    *,
    status_code: int,
    body: str,
    retry_after: Optional[str],
    upgrade_path: Optional[str],
) -> APIError:
    detail = _response_detail(body)
    message = f"Codag API returned {status_code}"
    if detail:
        message += f": {detail}"
    kwargs = {
        "status_code": status_code,
        "body": body,
        "detail": detail,
        "retry_after": retry_after,
        "upgrade_path": upgrade_path,
    }
    if status_code == 401:
        return AuthenticationError(message, **kwargs)
    if status_code == 402:
        return BillingError(message, **kwargs)
    if status_code == 429:
        return RateLimitError(message, **kwargs)
    return APIError(message, **kwargs)


def _response_detail(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    detail = parsed.get("detail") if isinstance(parsed, Mapping) else None
    return detail if isinstance(detail, str) else body.strip()
