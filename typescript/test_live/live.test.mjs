// Live integration checks against a real Codag API server.
//
// Opt-in: not part of `make test`. Run with an API key:
//
//   CODAG_API_KEY=cdk_... make test-live
//
// CODAG_SERVER overrides the target host (defaults to the hosted API).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  APIError,
  AuthenticationError,
  BillingError,
  Codag,
  ValidationError,
} from "../src/index.js";

const apiKey = process.env.CODAG_API_KEY ?? "";
const live = apiKey ? {} : { skip: "CODAG_API_KEY is not set" };
const client = apiKey ? new Codag({ timeoutMs: 60_000 }) : null;

const SAMPLE_LINES = [
  "ERROR api db pool timeout active=20 waiting=30 path=/api/orders",
  "WARN api db pool nearing capacity active=18 path=/api/orders",
  "ERROR api db pool timeout active=21 waiting=31 path=/api/checkout",
  "INFO api request completed status=200 path=/api/health elapsed_ms=3",
  "ERROR worker job retry queue=email attempt=3 err=smtp_timeout",
];

test("live: health reports ok", live, async () => {
  const health = await client.health();
  assert.equal(health.status, "ok");
});

test("live: compact returns text and stats", live, async () => {
  const result = await client.compact(SAMPLE_LINES, { service: "api", level: "error" });
  assert.ok(result.text.length > 0);
  assert.ok(result.stats.elapsed_ms >= 0);
  assert.ok(result.compact_engine);
});

test("live: compact accepts records and metadata", live, async () => {
  const records = SAMPLE_LINES.map((message) => ({ message, level: "error" }));
  const result = await client.compact(records, { metadata: { source: "sdk-live-test" } });
  assert.ok(result.text.length > 0);
});

test("live: capsule returns structured incident", live, async (t) => {
  // /v1/capsule is deprecated (internal/admin-only); non-admin callers get a
  // 404 and billing-gated workspaces get a 402. Both are skips.
  let result;
  try {
    result = await client.capsule(SAMPLE_LINES, { level: "error" });
  } catch (error) {
    if (error instanceof BillingError) {
      t.skip(`workspace lacks capsule access: ${error.detail}`);
      return;
    }
    if (error instanceof APIError && error.statusCode === 404) {
      t.skip("capsule is deprecated (internal/admin-only, 404 for non-admin)");
      return;
    }
    throw error;
  }
  assert.ok(result.capsule.schema_version);
  assert.ok(result.capsule.incident);
});

test("live: compact job lifecycle", live, async (t) => {
  let created;
  try {
    created = await client.createCompactJob(SAMPLE_LINES, { metadata: { source: "sdk-live-test" } });
  } catch (error) {
    if (error instanceof BillingError) {
      t.skip(`workspace lacks compact job access: ${error.detail}`);
      return;
    }
    throw error;
  }
  assert.ok(created.job_id);
  assert.ok(created.poll_url.endsWith(created.job_id));
  const job = await client.waitForCompactJob(created.job_id, { pollIntervalMs: 1000, timeoutMs: 120_000 });
  assert.equal(job.status, "succeeded", `job error: ${job.error}`);
  assert.ok(job.text.length > 0);
});

test("live: unknown job maps to 404 APIError", live, async () => {
  await assert.rejects(
    () => client.getCompactJob("cj_sdk_live_does_not_exist"),
    (error) => error instanceof APIError && error.statusCode === 404 && error.detail.length > 0,
  );
});

test("live: invalid key maps to AuthenticationError", live, async () => {
  const bad = new Codag({ apiKey: "cdk_sdk_live_invalid", baseUrl: client.baseUrl, timeoutMs: 30_000 });
  await assert.rejects(
    () => bad.compact(SAMPLE_LINES.slice(0, 1)),
    (error) => error instanceof AuthenticationError && error.statusCode === 401 && error.detail.length > 0,
  );
});

test("live: validation fails before network", live, async () => {
  await assert.rejects(() => client.compact([]), ValidationError);
});
