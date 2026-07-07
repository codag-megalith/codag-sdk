from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional, Union


DEFAULT_BASE_URL = "https://api.codag.ai"
MAX_LOG_LINES = 20_000
MAX_LOG_LINE_CHARS = 256 * 1024
MAX_METADATA_JSON_BYTES = 64 * 1024
USER_AGENT = "codag-python/0.1.0"


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
        return cls(
            llm_calls=int(value.get("llm_calls", 0)),
            cache_hits=int(value.get("cache_hits", 0)),
            unmatched=int(value.get("unmatched", 0)),
            elapsed_ms=int(value.get("elapsed_ms", 0)),
            incident_family_hits=int(value.get("incident_family_hits", 0)),
            incident_induced_templates=int(value.get("incident_induced_templates", 0)),
            global_cache_hits=int(value.get("global_cache_hits", 0)),
            global_shadow_hits=int(value.get("global_shadow_hits", 0)),
            global_shadow_agreements=int(value.get("global_shadow_agreements", 0)),
            global_shadow_disagreements=int(value.get("global_shadow_disagreements", 0)),
            total_patterns=int(value.get("total_patterns", 0)),
            candidate_patterns=int(value.get("candidate_patterns", 0)),
            dropped_patterns=int(value.get("dropped_patterns", 0)),
            cache_pattern_hits=int(value.get("cache_pattern_hits", 0)),
            global_cache_pattern_hits=int(value.get("global_cache_pattern_hits", 0)),
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

        May require a Codag Pro workspace; backend 402 responses raise
        :class:`BillingError` with ``upgrade_path`` set when provided.
        """
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
        data = self._request_json("GET", f"/v1/compact/jobs/{job_id}", None, auth=True)
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
        """Build a structured incident capsule via ``POST /v1/capsule``."""
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
        """Poll a compact job until it leaves the queued/running states."""
        return await asyncio.to_thread(
            self._sync.wait_for_compact_job, job_id, poll_interval=poll_interval, timeout=timeout
        )

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


def normalize_lines(
    lines: Sequence[LineInput],
    *,
    service: Optional[str] = None,
    level: str = "info",
) -> list[dict[str, Any]]:
    """Normalize strings, dicts, or LineRecords into wire-format records."""
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
