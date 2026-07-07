const DEFAULT_BASE_URL = "https://api.codag.ai";
const MAX_LOG_LINES = 20_000;
const MAX_LOG_LINE_CHARS = 256 * 1024;
const MAX_METADATA_JSON_BYTES = 64 * 1024;
const USER_AGENT = "codag-typescript/0.1.0";

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
    this.baseUrl = stripTrailingSlash(options.baseUrl ?? env("CODAG_SERVER") ?? DEFAULT_BASE_URL);
    this.timeoutMs = options.timeoutMs ?? 300_000;
    this.fetch = options.fetch ?? globalThis.fetch;
    if (typeof this.fetch !== "function") {
      throw new CodagError("global fetch is unavailable; pass a fetch implementation");
    }
  }

  async compact(lines, options = {}) {
    const payload = buildPayload(lines, options);
    return await this.requestJson("POST", "/v1/compact", payload, { auth: true });
  }

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
    if (record.message.length > MAX_LOG_LINE_CHARS) {
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
