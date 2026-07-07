import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import {
  APIError,
  AuthenticationError,
  BillingError,
  Codag,
  CodagError,
  NetworkError,
  RateLimitError,
  ValidationError,
  normalizeLines,
} from "../src/index.js";

const root = new URL("../../", import.meta.url);
const compactFixture = JSON.parse(await readFile(new URL("fixtures/compact_response.json", root), "utf8"));
const capsuleFixture = JSON.parse(await readFile(new URL("fixtures/capsule_response.json", root), "utf8"));

class HeadersLike {
  constructor(values = {}) {
    this.values = values;
  }
  get(name) {
    return this.values[name] ?? this.values[name.toLowerCase()] ?? null;
  }
}

function response(status, body, headers = {}) {
  return rawResponse(status, JSON.stringify(body), headers);
}

function rawResponse(status, body, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new HeadersLike(headers),
    async text() {
      return body;
    },
  };
}

function makeClient({ apiKey = "cdk_test", baseUrl = "http://example.test", responses = {} } = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, init, body });
    let spec = responses[url] ?? response(200, { ok: true });
    if (Array.isArray(spec)) {
      spec = spec.shift();
    }
    if (spec instanceof Error) {
      throw spec;
    }
    return spec;
  };
  return { client: new Codag({ apiKey, baseUrl, fetch }), calls };
}

function withEnv(name, value, fn) {
  const old = process.env[name];
  if (value === undefined) {
    delete process.env[name];
  } else {
    process.env[name] = value;
  }
  try {
    return fn();
  } finally {
    if (old === undefined) {
      delete process.env[name];
    } else {
      process.env[name] = old;
    }
  }
}

test("constructor uses hosted api by default", () => {
  const client = new Codag({ apiKey: "cdk_test", fetch: async () => response(200, {}) });
  assert.equal(client.baseUrl, "https://api.codag.ai");
});

test("constructor trims trailing base url slash", () => {
  const client = new Codag({ apiKey: "cdk_test", baseUrl: "http://example.test///", fetch: async () => response(200, {}) });
  assert.equal(client.baseUrl, "http://example.test");
});

test("constructor uses CODAG_SERVER env", () => withEnv("CODAG_SERVER", "http://env.test/", () => {
  const client = new Codag({ apiKey: "cdk_test", fetch: async () => response(200, {}) });
  assert.equal(client.baseUrl, "http://env.test");
}));

test("constructor baseUrl wins over CODAG_SERVER env", () => withEnv("CODAG_SERVER", "http://env.test", () => {
  const client = new Codag({ apiKey: "cdk_test", baseUrl: "http://arg.test", fetch: async () => response(200, {}) });
  assert.equal(client.baseUrl, "http://arg.test");
}));

test("constructor uses CODAG_API_KEY env", () => withEnv("CODAG_API_KEY", "cdk_env", () => {
  const client = new Codag({ baseUrl: "http://example.test", fetch: async () => response(200, {}) });
  assert.equal(client.apiKey, "cdk_env");
}));

test("constructor apiKey wins over CODAG_API_KEY env", () => withEnv("CODAG_API_KEY", "cdk_env", () => {
  const client = new Codag({ apiKey: "cdk_arg", baseUrl: "http://example.test", fetch: async () => response(200, {}) });
  assert.equal(client.apiKey, "cdk_arg");
}));

test("health uses GET without auth", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/health": response(200, { ok: true }) } });
  const result = await client.health();
  assert.equal(result.ok, true);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.headers.Authorization, undefined);
});

test("health omits request body and content type", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/health": response(200, { ok: true }) } });
  await client.health();
  assert.equal(calls[0].init.body, undefined);
  assert.equal(calls[0].init.headers["Content-Type"], undefined);
});

test("compact posts to compact endpoint", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await client.compact(["ERROR one"]);
  assert.equal(calls[0].url, "http://example.test/v1/compact");
  assert.equal(calls[0].init.method, "POST");
});

test("compact sends bearer token", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await client.compact(["ERROR one"]);
  assert.equal(calls[0].init.headers.Authorization, "Bearer cdk_test");
});

test("compact sends json content type", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await client.compact(["ERROR one"]);
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
});

test("compact sends user agent", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await client.compact(["ERROR one"]);
  assert.equal(calls[0].init.headers["User-Agent"], "codag-typescript/0.1.0");
});

test("compact decodes text and stats", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  const result = await client.compact(["ERROR one"]);
  assert.match(result.text, /# codag compact/);
  assert.equal(result.stats.elapsed_ms, 31);
});

test("compact decodes engine fields", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  const result = await client.compact(["ERROR one"]);
  assert.equal(result.compact_engine, "mvp");
  assert.equal(result.compact_fallback, null);
});

test("compact sends metadata", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await client.compact(["ERROR one"], { metadata: { source: "unit" } });
  assert.equal(calls[0].body.metadata.source, "unit");
});

test("compact omits metadata when absent", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await client.compact(["ERROR one"]);
  assert.equal("metadata" in calls[0].body, false);
});

test("capsule posts to capsule endpoint", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/capsule": response(200, capsuleFixture) } });
  await client.capsule(["ERROR one"]);
  assert.equal(calls[0].url, "http://example.test/v1/capsule");
});

test("capsule decodes fixture", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/capsule": response(200, capsuleFixture) } });
  const result = await client.capsule([{ message: "ERROR one", level: "error" }]);
  assert.equal(result.capsule.schema_version, "0.3");
  assert.equal(result.stats.llm_calls, 1);
});

test("capsule sends metadata", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/capsule": response(200, capsuleFixture) } });
  await client.capsule(["ERROR one"], { metadata: { source: "node" } });
  assert.equal(calls[0].body.metadata.source, "node");
});

test("createCompactJob decodes response", async () => {
  const body = { job_id: "cj_1", status: "queued", poll_url: "/v1/compact/jobs/cj_1" };
  const { client } = makeClient({ responses: { "http://example.test/v1/compact/jobs": response(200, body) } });
  const result = await client.createCompactJob(["ERROR one"]);
  assert.equal(result.job_id, "cj_1");
});

test("createCompactJob sends metadata", async () => {
  const body = { job_id: "cj_1", status: "queued", poll_url: "/v1/compact/jobs/cj_1" };
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact/jobs": response(200, body) } });
  await client.createCompactJob(["ERROR one"], { metadata: { source: "ci" } });
  assert.equal(calls[0].body.metadata.source, "ci");
});

test("getCompactJob encodes job id path", async () => {
  const body = { job_id: "cj_1", status: "succeeded", text: "ok", stats: null };
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact/jobs/cj_1": response(200, body) } });
  await client.getCompactJob("cj_1");
  assert.equal(calls[0].url, "http://example.test/v1/compact/jobs/cj_1");
});

test("getCompactJob rejects empty id", async () => {
  const { client } = makeClient();
  await assert.rejects(() => client.getCompactJob(""), ValidationError);
});

test("getCompactJob decodes stats null", async () => {
  const body = { job_id: "cj_1", status: "succeeded", text: "ok", stats: null };
  const { client } = makeClient({ responses: { "http://example.test/v1/compact/jobs/cj_1": response(200, body) } });
  const result = await client.getCompactJob("cj_1");
  assert.equal(result.stats, null);
});

test("getCompactJob decodes stats object", async () => {
  const body = { job_id: "cj_1", status: "succeeded", text: "ok", stats: { llm_calls: 0, cache_hits: 1, unmatched: 0, elapsed_ms: 5 } };
  const { client } = makeClient({ responses: { "http://example.test/v1/compact/jobs/cj_1": response(200, body) } });
  const result = await client.getCompactJob("cj_1");
  assert.equal(result.stats.cache_hits, 1);
});

test("waitForCompactJob returns completed job after queued", async () => {
  const responses = {
    "http://example.test/v1/compact/jobs/cj_1": [
      response(200, { job_id: "cj_1", status: "queued" }),
      response(200, { job_id: "cj_1", status: "succeeded", text: "ok" }),
    ],
  };
  const { client, calls } = makeClient({ responses });
  const result = await client.waitForCompactJob("cj_1", { pollIntervalMs: 0, timeoutMs: 1000 });
  assert.equal(result.text, "ok");
  assert.equal(calls.length, 2);
});

test("waitForCompactJob returns failed job", async () => {
  const responses = { "http://example.test/v1/compact/jobs/cj_1": response(200, { job_id: "cj_1", status: "failed", error: "boom" }) };
  const { client } = makeClient({ responses });
  const result = await client.waitForCompactJob("cj_1", { pollIntervalMs: 0, timeoutMs: 1000 });
  assert.equal(result.error, "boom");
});

test("waitForCompactJob times out", async () => {
  const responses = { "http://example.test/v1/compact/jobs/cj_1": response(200, { job_id: "cj_1", status: "queued" }) };
  const { client } = makeClient({ responses });
  await assert.rejects(() => client.waitForCompactJob("cj_1", { pollIntervalMs: 0, timeoutMs: 0 }), CodagError);
});

test("normalizeLines assigns line ids for strings", () => {
  assert.deepEqual(normalizeLines(["a", "b"]).map((line) => line.line_id), [0, 1]);
});

test("normalizeLines uses default level", () => {
  assert.equal(normalizeLines(["a"])[0].level, "info");
});

test("normalizeLines uses custom level", () => {
  assert.equal(normalizeLines(["a"], { level: "error" })[0].level, "error");
});

test("normalizeLines applies service to strings", () => {
  assert.equal(normalizeLines(["a"], { service: "api" })[0].service, "api");
});

test("normalizeLines assigns line id for records", () => {
  assert.equal(normalizeLines([{ message: "a" }])[0].line_id, 0);
});

test("normalizeLines preserves record line id", () => {
  assert.equal(normalizeLines([{ line_id: 99, message: "a" }])[0].line_id, 99);
});

test("normalizeLines assigns default level to records", () => {
  assert.equal(normalizeLines([{ message: "a" }])[0].level, "info");
});

test("normalizeLines preserves record level", () => {
  assert.equal(normalizeLines([{ message: "a", level: "warn" }])[0].level, "warn");
});

test("normalizeLines fills missing service", () => {
  assert.equal(normalizeLines([{ message: "a" }], { service: "api" })[0].service, "api");
});

test("normalizeLines does not override service", () => {
  assert.equal(normalizeLines([{ message: "a", service: "worker" }], { service: "api" })[0].service, "worker");
});

test("normalizeLines preserves timestamp", () => {
  assert.equal(normalizeLines([{ message: "a", timestamp: "2026-07-01T00:00:00Z" }])[0].timestamp, "2026-07-01T00:00:00Z");
});

test("normalizeLines rejects empty input", () => {
  assert.throws(() => normalizeLines([]), ValidationError);
});

test("normalizeLines rejects too many lines", () => {
  assert.throws(() => normalizeLines(new Array(20_001).fill("x")), ValidationError);
});

test("normalizeLines rejects too long line", () => {
  assert.throws(() => normalizeLines(["x".repeat(256 * 1024 + 1)]), ValidationError);
});

test("normalizeLines rejects invalid item type", () => {
  assert.throws(() => normalizeLines([42]), ValidationError);
});

test("normalizeLines rejects missing message", () => {
  assert.throws(() => normalizeLines([{ level: "error" }]), ValidationError);
});

test("normalizeLines rejects non-string message", () => {
  assert.throws(() => normalizeLines([{ message: 123 }]), ValidationError);
});

test("metadata over limit is rejected", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await assert.rejects(() => client.compact(["ERROR one"], { metadata: { x: "y".repeat(64 * 1024) } }), ValidationError);
});

test("missing api key fails before fetch", async () => withEnv("CODAG_API_KEY", undefined, async () => {
  let called = false;
  const client = new Codag({ baseUrl: "http://example.test", fetch: async () => { called = true; return response(200, {}); } });
  await assert.rejects(() => client.compact(["ERROR one"]), AuthenticationError);
  assert.equal(called, false);
}));

test("401 maps to AuthenticationError", async () => {
  const { client } = makeClient({ apiKey: "cdk_bad", responses: { "http://example.test/v1/compact": response(401, { detail: "invalid API key" }) } });
  await assert.rejects(() => client.compact(["ERROR one"]), AuthenticationError);
});

test("402 maps to BillingError with upgrade path", async () => {
  const { client } = makeClient({
    responses: { "http://example.test/v1/capsule": response(402, { detail: "billing_required" }, { "X-Codag-Upgrade": "/dashboard/billing" }) },
  });
  await assert.rejects(
    () => client.capsule(["ERROR one"]),
    (error) => error instanceof BillingError && error.upgradePath === "/dashboard/billing",
  );
});

test("429 maps to RateLimitError with retry after", async () => {
  const { client } = makeClient({
    responses: { "http://example.test/v1/compact": response(429, { detail: "mvp_sync_overloaded" }, { "Retry-After": "5" }) },
  });
  await assert.rejects(
    () => client.compact(["ERROR one"]),
    (error) => error instanceof RateLimitError && error.retryAfter === "5",
  );
});

test("500 maps to APIError", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/compact": response(500, { detail: "server_error" }) } });
  await assert.rejects(() => client.compact(["ERROR one"]), APIError);
});

test("plain error body becomes detail", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/compact": rawResponse(500, "plain failure") } });
  await assert.rejects(
    () => client.compact(["ERROR one"]),
    (error) => error instanceof APIError && error.detail === "plain failure",
  );
});

test("network failure maps to NetworkError", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/compact": new Error("refused") } });
  await assert.rejects(() => client.compact(["ERROR one"]), NetworkError);
});

test("timeout abort maps to timed out NetworkError", async () => {
  const abortError = new Error("This operation was aborted");
  abortError.name = "AbortError";
  const client = new Codag({
    apiKey: "cdk_test",
    baseUrl: "http://example.test",
    timeoutMs: 5,
    fetch: async () => {
      throw abortError;
    },
  });
  await assert.rejects(
    () => client.compact(["ERROR one"]),
    (error) => error instanceof NetworkError && /timed out after 5ms/.test(error.message),
  );
});

test("normalizeLines rejects non-array input", () => {
  assert.throws(() => normalizeLines("not an array"), ValidationError);
});

test("metadata size check works without Buffer", async () => {
  const { client, calls } = makeClient({ responses: { "http://example.test/v1/compact": response(200, compactFixture) } });
  await client.compact(["ERROR one"], { metadata: { emoji: "🚀" } });
  assert.equal(calls[0].body.metadata.emoji, "🚀");
});

test("invalid success json raises CodagError", async () => {
  const { client } = makeClient({ responses: { "http://example.test/v1/compact": rawResponse(200, "{not-json") } });
  await assert.rejects(() => client.compact(["ERROR one"]), CodagError);
});

test("empty success body returns empty object for health", async () => {
  const { client } = makeClient({ responses: { "http://example.test/health": rawResponse(200, "") } });
  const result = await client.health();
  assert.deepEqual(result, {});
});
