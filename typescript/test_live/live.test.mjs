// Opt-in integration checks against the hosted Codag action-cost API.
// Run with CODAG_API_KEY=cdk_... make test-live.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AuthenticationError,
  Codag,
  ValidationError,
} from "../src/index.js";

const apiKey = process.env.CODAG_API_KEY ?? "";
const live = apiKey ? {} : { skip: "CODAG_API_KEY is not set" };
const client = apiKey ? new Codag({ timeoutMs: 60_000 }) : null;
const fileList = "README.md\ntypescript/src/index.js\ntypescript/test/client.test.mjs";

test("live: health reports ok", live, async () => {
  const health = await client.health();
  assert.equal(health.status, "ok");
});

test("live: service status reports reducer state", live, async () => {
  const status = await client.serviceStatus();
  assert.equal(status.status, "ok");
  assert.equal(typeof status.reducer_configured, "boolean");
});

test("live: action passthrough decodes", live, async () => {
  const response = await client.reduceAction({
    id: "sdk-live-typescript-v020",
    kind: "file_list",
    tool: { name: "list_files", arguments: {} },
    result: fileList,
    harness: "openai_compatible",
    client_version: "0.2.0",
  });
  assert.equal(response.action_id, "sdk-live-typescript-v020");
  assert.equal(response.kind, "file_list");
  assert.equal(response.decision, "passthrough");
  assert.equal(response.reason, "conservative_passthrough");
  assert.equal(response.usage.bytes_in, Buffer.byteLength(fileList));
  assert.equal(response.usage.bytes_out, response.usage.bytes_in);
});

test("live: usage and pricing contracts decode", live, async () => {
  const usage = await client.usageSummary();
  assert.ok(usage.period_start);
  assert.ok(usage.period_end);
  assert.ok(usage.bytes_used >= 0);
  const prices = await client.modelPrices();
  assert.equal(prices.currency, "USD");
  assert.ok(prices.models.length > 0);
});

test("live: workspace policy decodes", live, async () => {
  const policy = await client.getWorkspacePolicy();
  assert.ok(["disabled", "audit", "optimize"].includes(policy.mode));
  assert.equal(policy.required_metrics, true);
});

test("live: invalid key maps to AuthenticationError", live, async () => {
  const bad = new Codag({
    apiKey: "cdk_sdk_live_invalid",
    baseUrl: client.baseUrl,
    timeoutMs: 30_000,
  });
  await assert.rejects(
    () => bad.serviceStatus(),
    (error) => error instanceof AuthenticationError
      && error.statusCode === 401
      && error.detail.length > 0,
  );
});

test("live: invalid action fails before network", live, async () => {
  await assert.rejects(() => client.reduceAction({ id: "incomplete" }), ValidationError);
});
