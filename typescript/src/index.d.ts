export interface LineRecord {
  line_id?: number;
  message: string;
  level?: string;
  timestamp?: string | null;
  service?: string | null;
}

export interface ParseStats {
  llm_calls: number;
  cache_hits: number;
  unmatched: number;
  elapsed_ms: number;
  incident_family_hits?: number;
  incident_induced_templates?: number;
  global_cache_hits?: number;
  global_shadow_hits?: number;
  global_shadow_agreements?: number;
  global_shadow_disagreements?: number;
  total_patterns?: number;
  candidate_patterns?: number;
  dropped_patterns?: number;
  cache_pattern_hits?: number;
  global_cache_pattern_hits?: number;
  [key: string]: unknown;
}

export interface RequestOptions {
  metadata?: Record<string, unknown>;
  service?: string;
  level?: string;
}

export interface CompactResponse {
  text: string;
  stats: ParseStats;
  compact_engine?: string | null;
  compact_fallback?: string | null;
  compact_error?: string | null;
  [key: string]: unknown;
}

export interface CapsuleResponse {
  capsule: Record<string, unknown>;
  stats: ParseStats;
  [key: string]: unknown;
}

export interface CompactJobCreateResponse {
  job_id: string;
  status: string;
  poll_url: string;
  [key: string]: unknown;
}

export interface CompactJobResponse {
  job_id: string;
  status: string;
  text?: string | null;
  stats?: ParseStats | null;
  error?: string | null;
  [key: string]: unknown;
}

export interface CodagOptions {
  apiKey?: string;
  baseUrl?: string;
  timeoutMs?: number;
  fetch?: typeof fetch;
}

export interface WaitOptions {
  pollIntervalMs?: number;
  timeoutMs?: number;
}

export type ActionKind =
  | "unknown" | "log" | "test_build_lint" | "search" | "file_list"
  | "document_read" | "agent_handoff" | "query" | "verbatim";

export interface ToolCall {
  id?: string;
  name: string;
  arguments?: unknown;
}

export interface ActionEnvelope {
  id: string;
  session_id?: string;
  harness?: string;
  provider?: string;
  model?: string;
  kind: ActionKind;
  tool: ToolCall;
  result: string;
  task?: string;
  intent?: string;
  retrieval_handle?: string;
  client_version?: string;
}

export interface Selector {
  id: string;
  label?: string;
  type: "lines" | "json_path" | "group";
  start?: number;
  end?: number;
  json_path?: string;
  group?: string;
}

export interface ActionResponse {
  action_id: string;
  kind: ActionKind;
  decision: "passthrough" | "reduced";
  content?: string;
  reason?: string;
  selectors: Selector[];
  usage: {
    bytes_in: number;
    bytes_out: number;
    reducer_input_tokens?: number;
    reducer_output_tokens?: number;
    reducer_cost_microusd?: number;
    elapsed_ms?: number;
  };
}

export interface MetricEvent {
  id: string;
  occurred_at: string;
  session_id?: string;
  install_id?: string;
  harness?: string;
  provider?: string;
  model?: string;
  action_kind: ActionKind;
  decision: string;
  reason?: string;
  original_bytes?: number;
  replacement_bytes?: number;
  provider_input_tokens?: number;
  provider_output_tokens?: number;
  provider_cache_read_tokens?: number;
  provider_cache_write_tokens?: number;
  estimated_cost_microusd?: number;
  reducer_cost_microusd?: number;
  elapsed_ms?: number;
  turn_count?: number;
  retry_count?: number;
  reread_count?: number;
  retrieval_count?: number;
  client_version?: string;
}

export interface UsageSummary {
  period_start: string;
  period_end: string;
  plan_tier: string;
  bytes_used: number;
  bytes_included: number;
  observed_tokens: number;
  avoided_tokens: number;
  estimated_provider_spend_microusd: number;
  estimated_saved_microusd: number;
  by_action: Record<string, unknown>;
  equivalent_savings_microusd: Record<string, number>;
}

export interface ModelPrice {
  provider: string;
  model_pattern: string;
  input_usd_per_mtok: number;
  cached_input_usd_per_mtok: number;
  cache_write_usd_per_mtok: number;
  output_usd_per_mtok: number;
  as_of: string;
  source_url?: string;
  cache_write_basis?: string;
  price_valid_through?: string;
}

export interface ModelPriceCatalog {
  currency: string;
  unit: string;
  models: ModelPrice[];
}

export interface WorkspacePolicy {
  mode: "disabled" | "audit" | "optimize";
  enabled_actions: ActionKind[];
  required_metrics: true;
  pinned_client_version?: string;
}

export interface UsageQuery { days?: number; }
export interface BreakdownQuery extends UsageQuery {
  dimension?: "action" | "provider" | "model" | "harness" | "member";
}

export class CodagError extends Error {}
export class ValidationError extends CodagError {}
export class NetworkError extends CodagError {
  cause?: unknown;
}
export class APIError extends CodagError {
  statusCode: number;
  body: string;
  detail: string;
  retryAfter: string | null;
  upgradePath: string | null;
}
export class AuthenticationError extends APIError {}
export class BillingError extends APIError {}
export class RateLimitError extends APIError {}

export class Codag {
  constructor(options?: CodagOptions);
  /** Compress log lines into compact text via POST /v1/compact. */
  compact(lines: string[] | LineRecord[], options?: RequestOptions): Promise<CompactResponse>;
  /**
   * Build a structured incident capsule via POST /v1/capsule.
   *
   * @deprecated /v1/capsule is now a Codag-internal, admin-only endpoint.
   * Non-admin callers receive a 404. Use {@link Codag.compact} (POST /v1/compact)
   * instead, which is the supported public product surface. This method is
   * retained for backward compatibility and internal/admin use.
   */
  capsule(lines: string[] | LineRecord[], options?: RequestOptions): Promise<CapsuleResponse>;
  /** Start an async compact job via POST /v1/compact/jobs. */
  createCompactJob(lines: string[] | LineRecord[], options?: RequestOptions): Promise<CompactJobCreateResponse>;
  /** Fetch the current state of a compact job. */
  getCompactJob(jobId: string): Promise<CompactJobResponse>;
  /** Poll a compact job until it leaves the queued/running states (terminal: succeeded, failed). */
  waitForCompactJob(jobId: string, options?: WaitOptions): Promise<CompactJobResponse>;
  /** Reduce one coding-agent action without retaining its content in Codag's cloud. */
  reduceAction(action: ActionEnvelope): Promise<ActionResponse>;
  /** Submit required contentless product-accounting metrics. */
  sendMetrics(events: MetricEvent[]): Promise<number>;
  usageSummary(): Promise<UsageSummary>;
  usageTimeseries(options?: UsageQuery): Promise<Record<string, unknown>>;
  usageBreakdown(options?: BreakdownQuery): Promise<Record<string, unknown>>;
  usageReliability(options?: UsageQuery): Promise<Record<string, unknown>>;
  trialReport(): Promise<Record<string, unknown>>;
  modelPrices(): Promise<ModelPriceCatalog>;
  getWorkspacePolicy(): Promise<WorkspacePolicy>;
  setWorkspacePolicy(policy: WorkspacePolicy): Promise<WorkspacePolicy>;
  serviceStatus(): Promise<Record<string, unknown>>;
  /** Unauthenticated GET /health. */
  health(): Promise<Record<string, unknown>>;
}

/** Normalize strings or partial records into LineRecords, validating count and size limits. */
export function normalizeLines(lines: string[] | LineRecord[], options?: RequestOptions): LineRecord[];
