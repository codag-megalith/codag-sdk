const DEFAULT_BASE_URL = "https://api.codag.ai";
const MAX_LOG_LINES = 20_000;
const MAX_LOG_LINE_CHARS = 256 * 1024;
const MAX_METADATA_JSON_BYTES = 64 * 1024;
const USER_AGENT = "codag-typescript/0.2.0";
const METRIC_ID = /^[A-Za-z0-9_.:@+~-]*$/;
const METRIC_SLUG = /^[A-Za-z0-9_.:+-]*$/;

export class CodagError extends Error {
  constructor(message) {
    super(message);
    this.name = "CodagError";
  }
}

export class ValidationError extends CodagError {
  constructor(message) {
    super(message);
    this.name = "ValidationError";
  }
}

export class NetworkError extends CodagError {
  constructor(message, cause) {
    super(message);
    this.name = "NetworkError";
    this.cause = cause;
  }
}

export class APIError extends CodagError {
  constructor(message, options) {
    super(message);
    this.name = "APIError";
    this.statusCode = options.statusCode;
    this.body = options.body || "";
    this.detail = options.detail || "";
    this.retryAfter = options.retryAfter || null;
    this.upgradePath = options.upgradePath || null;
  }
}

export class AuthenticationError extends APIError {
  constructor(message, options = {}) {
    super(message, { statusCode: 401, ...options });
    this.name = "AuthenticationError";
  }
}

export class BillingError extends APIError {
  constructor(message, options) {
    super(message, options);
    this.name = "BillingError";
  }
}

export class RateLimitError extends APIError {
  constructor(message, options) {
    super(message, options);
    this.name = "RateLimitError";
  }
}

export class Codag {
  constructor(options = {}) {
    this.apiKey = options.apiKey ?? env("CODAG_API_KEY") ?? "";
    // Use `||` so an empty-string baseUrl / CODAG_SERVER falls back to the
    // default instead of producing an invalid empty base URL.
    this.baseUrl = stripTrailingSlash(options.baseUrl || env("CODAG_SERVER") || DEFAULT_BASE_URL);
    this.timeoutMs = options.timeoutMs ?? 300_000;
    // Bind the global fetch to its realm: browsers throw "Illegal invocation"
    // if fetch is called with a receiver other than window/globalThis. A
    // caller-supplied fetch is used as given.
    this.fetch = options.fetch ?? globalThis.fetch?.bind(globalThis);
    if (typeof this.fetch !== "function") {
      throw new CodagError("global fetch is unavailable; pass a fetch implementation");
    }
  }

  async compact(lines, options = {}) {
    const payload = buildPayload(lines, options);
    return await this.requestJson("POST", "/v1/compact", payload, { auth: true });
  }

  /**
   * @deprecated /v1/capsule is now a Codag-internal, admin-only endpoint.
   * Non-admin callers receive a 404. Use `compact` (POST /v1/compact) instead,
   * which is the supported public product surface. This method is retained for
   * backward compatibility and internal/admin use.
   */
  async capsule(lines, options = {}) {
    const payload = buildPayload(lines, options);
    return await this.requestJson("POST", "/v1/capsule", payload, { auth: true });
  }

  async createCompactJob(lines, options = {}) {
    const payload = buildPayload(lines, options);
    return await this.requestJson("POST", "/v1/compact/jobs", payload, { auth: true });
  }

  async getCompactJob(jobId) {
    if (!jobId) {
      throw new ValidationError("jobId must not be empty");
    }
    return await this.requestJson("GET", `/v1/compact/jobs/${encodeURIComponent(jobId)}`, null, {
      auth: true,
    });
  }

  async waitForCompactJob(jobId, options = {}) {
    const pollIntervalMs = options.pollIntervalMs ?? 1000;
    const timeoutMs = options.timeoutMs ?? 300_000;
    const deadline = Date.now() + timeoutMs;
    while (true) {
      const job = await this.getCompactJob(jobId);
      if (job.status !== "queued" && job.status !== "running") {
        return job;
      }
      if (Date.now() >= deadline) {
        throw new CodagError(`compact job ${jobId} did not finish within ${timeoutMs}ms`);
      }
      await sleep(pollIntervalMs);
    }
  }

  async reduceAction(action) {
    if (!action || typeof action !== "object" || !action.id || !action.kind || !action.result) {
      throw new ValidationError("action requires id, kind, tool, and result");
    }
    if (!action.tool || typeof action.tool !== "object" || !action.tool.name) {
      throw new ValidationError("action.tool requires a name");
    }
    return await this.requestJson("POST", "/v1/actions/reduce", action, { auth: true });
  }

  async sendMetrics(events) {
    if (!Array.isArray(events) || events.length === 0 || events.length > 1000) {
      throw new ValidationError("events must contain 1 through 1000 contentless metrics");
    }
    const allowed = new Set([
      "id", "occurred_at", "session_id", "install_id", "harness", "provider", "model",
      "action_kind", "decision", "reason", "original_bytes", "replacement_bytes",
      "provider_input_tokens", "provider_output_tokens", "provider_cache_read_tokens",
      "provider_cache_write_tokens", "estimated_cost_microusd", "reducer_cost_microusd",
      "elapsed_ms", "turn_count", "retry_count", "reread_count", "retrieval_count",
      "client_version",
    ]);
    for (const event of events) {
      if (!event || typeof event !== "object" || !event.id || !event.occurred_at) {
        throw new ValidationError("each metric requires id and occurred_at");
      }
      const extra = Object.keys(event).filter((key) => !allowed.has(key));
      if (extra.length) {
        throw new ValidationError(`metric contains unsupported fields: ${extra.join(", ")}`);
      }
      const tokens = [
        ["id", 128, METRIC_ID], ["session_id", 256, METRIC_ID],
        ["install_id", 256, METRIC_ID], ["harness", 128, METRIC_SLUG],
        ["provider", 128, METRIC_SLUG], ["model", 256, METRIC_SLUG],
        ["decision", 64, METRIC_SLUG], ["reason", 256, METRIC_SLUG],
        ["client_version", 128, METRIC_SLUG],
      ];
      for (const [name, maximum, pattern] of tokens) {
        const value = event[name] ?? "";
        if (typeof value !== "string" || value.length > maximum || !pattern.test(value)) {
          throw new ValidationError("metric identifiers and labels must be bounded contentless tokens");
        }
      }
    }
    const response = await this.requestJson("POST", "/v1/metrics/batch", { events }, { auth: true });
    return Number(response.accepted || 0);
  }

  async usageSummary() {
    return await this.requestJson("GET", "/v1/usage/summary", null, { auth: true });
  }

  async usageTimeseries(options = {}) {
    return await this.requestJson("GET", `/v1/usage/timeseries?days=${days(options.days ?? 30)}`, null, { auth: true });
  }

  async usageBreakdown(options = {}) {
    const dimension = options.dimension ?? "action";
    const allowed = new Set(["action", "provider", "model", "harness", "member"]);
    if (!allowed.has(dimension)) {
      throw new ValidationError("dimension must be action, provider, model, harness, or member");
    }
    const query = new URLSearchParams({ dimension, days: String(days(options.days ?? 30)) });
    return await this.requestJson("GET", `/v1/usage/breakdown?${query}`, null, { auth: true });
  }

  async usageReliability(options = {}) {
    return await this.requestJson("GET", `/v1/usage/reliability?days=${days(options.days ?? 30)}`, null, { auth: true });
  }

  async trialReport() {
    return await this.requestJson("GET", "/v1/trials/report", null, { auth: true });
  }

  async modelPrices() {
    return await this.requestJson("GET", "/v1/model-prices", null, { auth: true });
  }

  async getWorkspacePolicy() {
    return await this.requestJson("GET", "/v1/workspace/policy", null, { auth: true });
  }

  async setWorkspacePolicy(policy) {
    return await this.requestJson("PUT", "/v1/workspace/policy", policy, { auth: true });
  }

  async serviceStatus() {
    return await this.requestJson("GET", "/v1/service/status", null, { auth: true });
  }

  async health() {
    return await this.requestJson("GET", "/health", null, { auth: false });
  }

  async requestJson(method, path, payload, options) {
    if (options.auth && !this.apiKey) {
      throw new AuthenticationError("missing Codag API key; pass apiKey or set CODAG_API_KEY");
    }

    const headers = {
      Accept: "application/json",
      "User-Agent": USER_AGENT,
    };
    let body;
    if (payload !== null && payload !== undefined) {
      body = JSON.stringify(payload);
      headers["Content-Type"] = "application/json";
    }
    if (options.auth) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    let response;
    try {
      response = await this.fetch(this.baseUrl + path, {
        method,
        headers,
        body,
        signal: controller.signal,
      });
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw new NetworkError(`request to ${this.baseUrl} timed out after ${this.timeoutMs}ms`, error);
      }
      throw new NetworkError(`cannot reach Codag server at ${this.baseUrl}: ${error.message}`, error);
    } finally {
      clearTimeout(timeout);
    }

    const text = await response.text();
    if (!response.ok) {
      throw errorForResponse(response, text);
    }
    if (!text) {
      return {};
    }
    try {
      return JSON.parse(text);
    } catch (error) {
      throw new CodagError(`Codag returned invalid JSON: ${error.message}`);
    }
  }
}

export function normalizeLines(lines, options = {}) {
  if (!Array.isArray(lines)) {
    throw new ValidationError("lines must be an array of strings or line records");
  }
  if (lines.length === 0) {
    throw new ValidationError("lines must not be empty");
  }
  if (lines.length > MAX_LOG_LINES) {
    throw new ValidationError(`lines exceeds ${MAX_LOG_LINES}`);
  }

  const service = options.service;
  const level = options.level ?? "info";
  return lines.map((line, index) => {
    let record;
    if (typeof line === "string") {
      record = { line_id: index, message: line, level };
      if (service) {
        record.service = service;
      }
    } else if (line && typeof line === "object" && !Array.isArray(line)) {
      record = { ...line };
      if (record.line_id === undefined) {
        record.line_id = index;
      }
      if (record.level === undefined) {
        record.level = level;
      }
      if (service && !record.service) {
        record.service = service;
      }
    } else {
      throw new ValidationError(`line ${index} must be a string or LineRecord`);
    }

    if (typeof record.message !== "string") {
      throw new ValidationError(`line ${index} is missing string field 'message'`);
    }
    // Measure in Unicode code points to match the server (and the Python
    // client). `.length` counts UTF-16 units and is an upper bound on code
    // points, so only spread-count when the cheap check trips.
    if (record.message.length > MAX_LOG_LINE_CHARS && [...record.message].length > MAX_LOG_LINE_CHARS) {
      throw new ValidationError(`line ${index} exceeds ${MAX_LOG_LINE_CHARS} characters`);
    }
    return record;
  });
}

function buildPayload(lines, options) {
  const payload = {
    lines: normalizeLines(lines, options),
  };
  if (options.metadata !== undefined && options.metadata !== null) {
    const raw = JSON.stringify(options.metadata);
    if (new TextEncoder().encode(raw).length > MAX_METADATA_JSON_BYTES) {
      throw new ValidationError(`metadata exceeds ${MAX_METADATA_JSON_BYTES} bytes`);
    }
    payload.metadata = options.metadata;
  }
  return payload;
}

function errorForResponse(response, body) {
  const detail = responseDetail(body);
  let message = `Codag API returned ${response.status}`;
  if (detail) {
    message += `: ${detail}`;
  }
  const options = {
    statusCode: response.status,
    body,
    detail,
    retryAfter: response.headers?.get?.("Retry-After") ?? null,
    upgradePath: response.headers?.get?.("X-Codag-Upgrade") ?? null,
  };
  if (response.status === 401) {
    return new AuthenticationError(message, options);
  }
  if (response.status === 402) {
    return new BillingError(message, options);
  }
  if (response.status === 429) {
    return new RateLimitError(message, options);
  }
  return new APIError(message, options);
}

function responseDetail(body) {
  try {
    const parsed = JSON.parse(body);
    return typeof parsed.detail === "string" ? parsed.detail : body.trim();
  } catch {
    return body.trim();
  }
}

function env(name) {
  if (typeof process !== "undefined" && process.env) {
    return process.env[name];
  }
  return undefined;
}

function stripTrailingSlash(value) {
  return String(value).replace(/\/+$/, "");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function days(value) {
  if (!Number.isInteger(value) || value < 1 || value > 90) {
    throw new ValidationError("days must be an integer from 1 through 90");
  }
  return value;
}
