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
  /** Build a structured incident capsule via POST /v1/capsule. May require a Codag Pro workspace. */
  capsule(lines: string[] | LineRecord[], options?: RequestOptions): Promise<CapsuleResponse>;
  /** Start an async compact job via POST /v1/compact/jobs. */
  createCompactJob(lines: string[] | LineRecord[], options?: RequestOptions): Promise<CompactJobCreateResponse>;
  /** Fetch the current state of a compact job. */
  getCompactJob(jobId: string): Promise<CompactJobResponse>;
  /** Poll a compact job until it leaves the queued/running states (terminal: succeeded, failed). */
  waitForCompactJob(jobId: string, options?: WaitOptions): Promise<CompactJobResponse>;
  /** Unauthenticated GET /health. */
  health(): Promise<Record<string, unknown>>;
}

/** Normalize strings or partial records into LineRecords, validating count and size limits. */
export function normalizeLines(lines: string[] | LineRecord[], options?: RequestOptions): LineRecord[];
