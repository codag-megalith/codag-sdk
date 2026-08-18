// Package codag is the official Go client for the Codag hosted API.
//
// Credentials resolve from WithAPIKey, then the CODAG_API_KEY environment
// variable. The base URL resolves from WithBaseURL, then CODAG_SERVER, then
// the hosted default.
package codag

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	DefaultBaseURL       = "https://api.codag.ai"
	maxResponseBody      = 16 << 20
	maxLogLines          = 20_000
	maxLogLineChars      = 256 * 1024
	maxMetadataJSONBytes = 64 * 1024
	defaultUserAgent     = "codag-go/0.2.0"
)

var (
	ErrMissingAPIKey  = errors.New("missing Codag API key; pass WithAPIKey or set CODAG_API_KEY")
	ErrAuthentication = errors.New("codag authentication error")
	ErrBilling        = errors.New("codag billing action required")
	ErrRateLimited    = errors.New("codag rate limited or overloaded")
)

var (
	metricIDPattern   = regexp.MustCompile(`^[A-Za-z0-9_.:@+~-]*$`)
	metricSlugPattern = regexp.MustCompile(`^[A-Za-z0-9_.:+-]*$`)
)

type Client struct {
	BaseURL    string
	APIKey     string
	HTTPClient *http.Client
	UserAgent  string
}

type Option func(*Client)

func WithAPIKey(apiKey string) Option {
	return func(c *Client) {
		c.APIKey = apiKey
	}
}

func WithBaseURL(baseURL string) Option {
	return func(c *Client) {
		c.BaseURL = strings.TrimRight(baseURL, "/")
	}
}

func WithHTTPClient(httpClient *http.Client) Option {
	return func(c *Client) {
		c.HTTPClient = httpClient
	}
}

func New(options ...Option) *Client {
	c := &Client{
		BaseURL:    strings.TrimRight(firstNonEmpty(os.Getenv("CODAG_SERVER"), DefaultBaseURL), "/"),
		APIKey:     os.Getenv("CODAG_API_KEY"),
		HTTPClient: &http.Client{Timeout: 5 * time.Minute},
		UserAgent:  defaultUserAgent,
	}
	for _, option := range options {
		option(c)
	}
	if c.HTTPClient == nil {
		c.HTTPClient = &http.Client{Timeout: 5 * time.Minute}
	}
	return c
}

type LineRecord struct {
	LineID    int    `json:"line_id"`
	Message   string `json:"message"`
	Level     string `json:"level,omitempty"`
	Timestamp string `json:"timestamp,omitempty"`
	Service   string `json:"service,omitempty"`
}

type RequestOptions struct {
	Metadata map[string]any
	Service  string
	Level    string
}

type CapsuleRequest struct {
	Lines    []LineRecord   `json:"lines"`
	Metadata map[string]any `json:"metadata,omitempty"`
}

type ParseStats struct {
	LLMCalls                  int `json:"llm_calls"`
	CacheHits                 int `json:"cache_hits"`
	Unmatched                 int `json:"unmatched"`
	ElapsedMS                 int `json:"elapsed_ms"`
	IncidentFamilyHits        int `json:"incident_family_hits,omitempty"`
	IncidentInducedTemplates  int `json:"incident_induced_templates,omitempty"`
	GlobalCacheHits           int `json:"global_cache_hits,omitempty"`
	GlobalShadowHits          int `json:"global_shadow_hits,omitempty"`
	GlobalShadowAgreements    int `json:"global_shadow_agreements,omitempty"`
	GlobalShadowDisagreements int `json:"global_shadow_disagreements,omitempty"`
	TotalPatterns             int `json:"total_patterns,omitempty"`
	CandidatePatterns         int `json:"candidate_patterns,omitempty"`
	DroppedPatterns           int `json:"dropped_patterns,omitempty"`
	CachePatternHits          int `json:"cache_pattern_hits,omitempty"`
	GlobalCachePatternHits    int `json:"global_cache_pattern_hits,omitempty"`
}

type CompactResponse struct {
	Text            string     `json:"text"`
	Stats           ParseStats `json:"stats"`
	CompactEngine   string     `json:"compact_engine,omitempty"`
	CompactFallback string     `json:"compact_fallback,omitempty"`
	CompactError    string     `json:"compact_error,omitempty"`
}

type CapsuleResponse struct {
	Capsule map[string]any `json:"capsule"`
	Stats   ParseStats     `json:"stats"`
}

type CompactJobCreateResponse struct {
	JobID   string `json:"job_id"`
	Status  string `json:"status"`
	PollURL string `json:"poll_url"`
}

type CompactJobResponse struct {
	JobID  string      `json:"job_id"`
	Status string      `json:"status"`
	Text   string      `json:"text,omitempty"`
	Stats  *ParseStats `json:"stats,omitempty"`
	Error  string      `json:"error,omitempty"`
}

type ActionKind string

const (
	ActionUnknown       ActionKind = "unknown"
	ActionLog           ActionKind = "log"
	ActionTestBuildLint ActionKind = "test_build_lint"
	ActionSearch        ActionKind = "search"
	ActionFileList      ActionKind = "file_list"
	ActionDocumentRead  ActionKind = "document_read"
	ActionAgentHandoff  ActionKind = "agent_handoff"
	ActionQuery         ActionKind = "query"
	ActionVerbatim      ActionKind = "verbatim"
)

type ToolCall struct {
	ID        string `json:"id,omitempty"`
	Name      string `json:"name"`
	Arguments any    `json:"arguments,omitempty"`
}

type ActionEnvelope struct {
	ID              string     `json:"id"`
	SessionID       string     `json:"session_id,omitempty"`
	Harness         string     `json:"harness,omitempty"`
	Provider        string     `json:"provider,omitempty"`
	Model           string     `json:"model,omitempty"`
	Kind            ActionKind `json:"kind"`
	Tool            ToolCall   `json:"tool"`
	Result          string     `json:"result"`
	Task            string     `json:"task,omitempty"`
	Intent          string     `json:"intent,omitempty"`
	RetrievalHandle string     `json:"retrieval_handle,omitempty"`
	ClientVersion   string     `json:"client_version,omitempty"`
}

type Selector struct {
	ID       string `json:"id"`
	Label    string `json:"label,omitempty"`
	Type     string `json:"type"`
	Start    int    `json:"start,omitempty"`
	End      int    `json:"end,omitempty"`
	JSONPath string `json:"json_path,omitempty"`
	Group    string `json:"group,omitempty"`
}

type ActionUsage struct {
	BytesIn        int64 `json:"bytes_in"`
	BytesOut       int64 `json:"bytes_out"`
	ReducerInput   int64 `json:"reducer_input_tokens,omitempty"`
	ReducerOutput  int64 `json:"reducer_output_tokens,omitempty"`
	ReducerCostUSD int64 `json:"reducer_cost_microusd,omitempty"`
	ElapsedMS      int64 `json:"elapsed_ms,omitempty"`
}

type ActionResponse struct {
	ActionID  string      `json:"action_id"`
	Kind      ActionKind  `json:"kind"`
	Decision  string      `json:"decision"`
	Content   string      `json:"content,omitempty"`
	Reason    string      `json:"reason,omitempty"`
	Selectors []Selector  `json:"selectors,omitempty"`
	Usage     ActionUsage `json:"usage"`
}

// MetricEvent is intentionally contentless. It has no prompt, command, path,
// filename, task, tool arguments, or result fields.
type MetricEvent struct {
	ID                 string     `json:"id"`
	OccurredAt         time.Time  `json:"occurred_at"`
	SessionID          string     `json:"session_id,omitempty"`
	InstallID          string     `json:"install_id,omitempty"`
	Harness            string     `json:"harness,omitempty"`
	Provider           string     `json:"provider,omitempty"`
	Model              string     `json:"model,omitempty"`
	ActionKind         ActionKind `json:"action_kind"`
	Decision           string     `json:"decision"`
	Reason             string     `json:"reason,omitempty"`
	OriginalBytes      int64      `json:"original_bytes,omitempty"`
	ReplacementBytes   int64      `json:"replacement_bytes,omitempty"`
	ProviderInput      int64      `json:"provider_input_tokens,omitempty"`
	ProviderOutput     int64      `json:"provider_output_tokens,omitempty"`
	ProviderCacheRead  int64      `json:"provider_cache_read_tokens,omitempty"`
	ProviderCacheWrite int64      `json:"provider_cache_write_tokens,omitempty"`
	EstimatedMicroUSD  int64      `json:"estimated_cost_microusd,omitempty"`
	ReducerMicroUSD    int64      `json:"reducer_cost_microusd,omitempty"`
	ElapsedMS          int64      `json:"elapsed_ms,omitempty"`
	TurnCount          int64      `json:"turn_count,omitempty"`
	RetryCount         int64      `json:"retry_count,omitempty"`
	RereadCount        int64      `json:"reread_count,omitempty"`
	RetrievalCount     int64      `json:"retrieval_count,omitempty"`
	ClientVersion      string     `json:"client_version,omitempty"`
}

type ActionUse struct {
	Actions                int64 `json:"actions"`
	BytesIn                int64 `json:"bytes_in"`
	BytesOut               int64 `json:"bytes_out"`
	AvoidedTokens          int64 `json:"avoided_tokens"`
	EstimatedSavedMicroUSD int64 `json:"estimated_saved_microusd"`
}

type UsageSummary struct {
	PeriodStart                    time.Time            `json:"period_start"`
	PeriodEnd                      time.Time            `json:"period_end"`
	PlanTier                       string               `json:"plan_tier"`
	BytesUsed                      int64                `json:"bytes_used"`
	BytesIncluded                  int64                `json:"bytes_included"`
	ObservedTokens                 int64                `json:"observed_tokens"`
	AvoidedTokens                  int64                `json:"avoided_tokens"`
	EstimatedProviderSpendMicroUSD int64                `json:"estimated_provider_spend_microusd"`
	EstimatedSavedMicroUSD         int64                `json:"estimated_saved_microusd"`
	ByAction                       map[string]ActionUse `json:"by_action"`
	EquivalentSavings              map[string]int64     `json:"equivalent_savings_microusd"`
}

type ModelPrice struct {
	Provider              string  `json:"provider"`
	ModelPattern          string  `json:"model_pattern"`
	InputUSDPerMTok       float64 `json:"input_usd_per_mtok"`
	CachedInputUSDPerMTok float64 `json:"cached_input_usd_per_mtok"`
	CacheWriteUSDPerMTok  float64 `json:"cache_write_usd_per_mtok"`
	OutputUSDPerMTok      float64 `json:"output_usd_per_mtok"`
	AsOf                  string  `json:"as_of"`
	SourceURL             string  `json:"source_url,omitempty"`
	CacheWriteBasis       string  `json:"cache_write_basis,omitempty"`
	PriceValidThrough     string  `json:"price_valid_through,omitempty"`
}

type ModelPriceCatalog struct {
	Currency string       `json:"currency"`
	Unit     string       `json:"unit"`
	Models   []ModelPrice `json:"models"`
}

type WorkspacePolicy struct {
	Mode                string       `json:"mode"`
	PinnedClientVersion string       `json:"pinned_client_version,omitempty"`
	EnabledActions      []ActionKind `json:"enabled_actions"`
	RequiredMetrics     bool         `json:"required_metrics"`
}

type UsageQuery struct {
	Days      int
	Dimension string
}

type WaitOptions struct {
	PollInterval time.Duration
	Timeout      time.Duration
}

type APIError struct {
	StatusCode  int
	Body        string
	Detail      string
	RetryAfter  string
	UpgradePath string
	Kind        error
}

func (e *APIError) Error() string {
	if e == nil {
		return ""
	}
	message := fmt.Sprintf("Codag API returned %d", e.StatusCode)
	if e.Detail != "" {
		message += ": " + e.Detail
	}
	return message
}

func (e *APIError) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Kind
}

// Compact compresses log lines into compact text via POST /v1/compact.
// lines must be []string or []LineRecord.
func (c *Client) Compact(ctx context.Context, lines any, opts *RequestOptions) (*CompactResponse, error) {
	req, err := BuildCapsuleRequest(lines, opts)
	if err != nil {
		return nil, err
	}
	var out CompactResponse
	if err := c.requestJSON(ctx, http.MethodPost, "/v1/compact", req, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

// Capsule builds a structured incident capsule via POST /v1/capsule.
//
// Deprecated: /v1/capsule is now a Codag-internal, admin-only endpoint.
// Non-admin callers receive a 404. Use Compact (POST /v1/compact) instead,
// which is the supported public product surface. This method and the
// CapsuleRequest/CapsuleResponse types are retained for backward
// compatibility and internal/admin use, and are not removed.
func (c *Client) Capsule(ctx context.Context, lines any, opts *RequestOptions) (*CapsuleResponse, error) {
	req, err := BuildCapsuleRequest(lines, opts)
	if err != nil {
		return nil, err
	}
	var out CapsuleResponse
	if err := c.requestJSON(ctx, http.MethodPost, "/v1/capsule", req, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

// CreateCompactJob starts an async compact job via POST /v1/compact/jobs.
func (c *Client) CreateCompactJob(ctx context.Context, lines any, opts *RequestOptions) (*CompactJobCreateResponse, error) {
	req, err := BuildCapsuleRequest(lines, opts)
	if err != nil {
		return nil, err
	}
	var out CompactJobCreateResponse
	if err := c.requestJSON(ctx, http.MethodPost, "/v1/compact/jobs", req, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetCompactJob fetches the current state of a compact job.
func (c *Client) GetCompactJob(ctx context.Context, jobID string) (*CompactJobResponse, error) {
	if jobID == "" {
		return nil, errors.New("jobID must not be empty")
	}
	var out CompactJobResponse
	path := "/v1/compact/jobs/" + url.PathEscape(jobID)
	if err := c.requestJSON(ctx, http.MethodGet, path, nil, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

// WaitForCompactJob polls a compact job until it leaves the queued/running
// states (terminal statuses: succeeded, failed).
func (c *Client) WaitForCompactJob(ctx context.Context, jobID string, opts *WaitOptions) (*CompactJobResponse, error) {
	pollInterval := time.Second
	timeout := 5 * time.Minute
	if opts != nil {
		if opts.PollInterval > 0 {
			pollInterval = opts.PollInterval
		}
		if opts.Timeout > 0 {
			timeout = opts.Timeout
		}
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		job, err := c.GetCompactJob(ctx, jobID)
		if err != nil {
			// If the wait deadline expired during the in-flight poll, report it
			// as a timeout (matching Python/TypeScript) rather than leaking the
			// transport-level "context deadline exceeded".
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				return nil, fmt.Errorf("compact job %s did not finish within %s: %w", jobID, timeout, ctx.Err())
			}
			return nil, err
		}
		if job.Status != "queued" && job.Status != "running" {
			return job, nil
		}
		select {
		case <-ctx.Done():
			if errors.Is(ctx.Err(), context.Canceled) {
				return nil, ctx.Err()
			}
			return nil, fmt.Errorf("compact job %s did not finish within %s: %w", jobID, timeout, ctx.Err())
		case <-ticker.C:
		}
	}
}

// ReduceAction reduces one coding-agent action without retaining its content
// in Codag's cloud.
func (c *Client) ReduceAction(ctx context.Context, action ActionEnvelope) (*ActionResponse, error) {
	if action.ID == "" || action.Kind == "" || action.Tool.Name == "" || action.Result == "" {
		return nil, errors.New("action requires ID, Kind, Tool.Name, and Result")
	}
	var out ActionResponse
	if err := c.requestJSON(ctx, http.MethodPost, "/v1/actions/reduce", action, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

// SendMetrics submits required contentless product-accounting events.
func (c *Client) SendMetrics(ctx context.Context, events []MetricEvent) (int, error) {
	if len(events) == 0 || len(events) > 1000 {
		return 0, errors.New("events must contain 1 through 1000 metrics")
	}
	for _, event := range events {
		if event.ID == "" || event.OccurredAt.IsZero() || event.ActionKind == "" || event.Decision == "" {
			return 0, errors.New("each metric requires ID, OccurredAt, ActionKind, and Decision")
		}
		if !validMetricToken(event.ID, 128, metricIDPattern) ||
			!validMetricToken(event.SessionID, 256, metricIDPattern) ||
			!validMetricToken(event.InstallID, 256, metricIDPattern) ||
			!validMetricToken(event.Harness, 128, metricSlugPattern) ||
			!validMetricToken(event.Provider, 128, metricSlugPattern) ||
			!validMetricToken(event.Model, 256, metricSlugPattern) ||
			!validMetricToken(event.Decision, 64, metricSlugPattern) ||
			!validMetricToken(event.Reason, 256, metricSlugPattern) ||
			!validMetricToken(event.ClientVersion, 128, metricSlugPattern) {
			return 0, errors.New("metric identifiers and labels must be bounded contentless tokens")
		}
	}
	var out struct {
		Accepted int `json:"accepted"`
	}
	if err := c.requestJSON(ctx, http.MethodPost, "/v1/metrics/batch", map[string]any{"events": events}, &out, true); err != nil {
		return 0, err
	}
	return out.Accepted, nil
}

func validMetricToken(value string, maximum int, pattern *regexp.Regexp) bool {
	return len(value) <= maximum && pattern.MatchString(value)
}

func (c *Client) UsageSummary(ctx context.Context) (*UsageSummary, error) {
	var out UsageSummary
	if err := c.requestJSON(ctx, http.MethodGet, "/v1/usage/summary", nil, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) UsageTimeseries(ctx context.Context, opts *UsageQuery) (map[string]any, error) {
	path, err := usagePath("/v1/usage/timeseries", opts, false)
	if err != nil {
		return nil, err
	}
	return c.getMap(ctx, path)
}

func (c *Client) UsageBreakdown(ctx context.Context, opts *UsageQuery) (map[string]any, error) {
	path, err := usagePath("/v1/usage/breakdown", opts, true)
	if err != nil {
		return nil, err
	}
	return c.getMap(ctx, path)
}

func (c *Client) UsageReliability(ctx context.Context, opts *UsageQuery) (map[string]any, error) {
	path, err := usagePath("/v1/usage/reliability", opts, false)
	if err != nil {
		return nil, err
	}
	return c.getMap(ctx, path)
}

func (c *Client) TrialReport(ctx context.Context) (map[string]any, error) {
	return c.getMap(ctx, "/v1/trials/report")
}

func (c *Client) ModelPrices(ctx context.Context) (*ModelPriceCatalog, error) {
	var out ModelPriceCatalog
	if err := c.requestJSON(ctx, http.MethodGet, "/v1/model-prices", nil, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) GetWorkspacePolicy(ctx context.Context) (*WorkspacePolicy, error) {
	var out WorkspacePolicy
	if err := c.requestJSON(ctx, http.MethodGet, "/v1/workspace/policy", nil, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) SetWorkspacePolicy(ctx context.Context, policy WorkspacePolicy) (*WorkspacePolicy, error) {
	var out WorkspacePolicy
	if err := c.requestJSON(ctx, http.MethodPut, "/v1/workspace/policy", policy, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) ServiceStatus(ctx context.Context) (map[string]any, error) {
	return c.getMap(ctx, "/v1/service/status")
}

func (c *Client) getMap(ctx context.Context, path string) (map[string]any, error) {
	out := map[string]any{}
	if err := c.requestJSON(ctx, http.MethodGet, path, nil, &out, true); err != nil {
		return nil, err
	}
	return out, nil
}

func usagePath(path string, opts *UsageQuery, dimension bool) (string, error) {
	days := 30
	dim := "action"
	if opts != nil {
		if opts.Days != 0 {
			days = opts.Days
		}
		if opts.Dimension != "" {
			dim = opts.Dimension
		}
	}
	if days < 1 || days > 90 {
		return "", errors.New("days must be from 1 through 90")
	}
	query := url.Values{"days": {fmt.Sprint(days)}}
	if dimension {
		allowed := map[string]bool{"action": true, "provider": true, "model": true, "harness": true, "member": true}
		if !allowed[dim] {
			return "", errors.New("dimension must be action, provider, model, harness, or member")
		}
		query.Set("dimension", dim)
	}
	return path + "?" + query.Encode(), nil
}

// Health performs an unauthenticated GET /health.
func (c *Client) Health(ctx context.Context) (map[string]any, error) {
	out := map[string]any{}
	if err := c.requestJSON(ctx, http.MethodGet, "/health", nil, &out, false); err != nil {
		return nil, err
	}
	return out, nil
}

// BuildCapsuleRequest normalizes lines and validates metadata into the wire
// request shared by the compact, capsule, and job endpoints.
func BuildCapsuleRequest(lines any, opts *RequestOptions) (*CapsuleRequest, error) {
	records, err := NormalizeLines(lines, opts)
	if err != nil {
		return nil, err
	}
	req := &CapsuleRequest{Lines: records}
	if opts != nil && opts.Metadata != nil {
		raw, err := marshalJSON(opts.Metadata)
		if err != nil {
			return nil, fmt.Errorf("marshal metadata: %w", err)
		}
		if len(raw) > maxMetadataJSONBytes {
			return nil, fmt.Errorf("metadata exceeds %d bytes", maxMetadataJSONBytes)
		}
		req.Metadata = opts.Metadata
	}
	return req, nil
}

// marshalJSON encodes v without Go's default HTML escaping of <, >, and &, so
// the byte count and wire payload match the Python and TypeScript clients
// (which do not HTML-escape). encoding/json.Encoder appends a trailing
// newline, which is trimmed.
func marshalJSON(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

// NormalizeLines converts []string or []LineRecord input into validated
// LineRecords, enforcing count and per-line size limits.
func NormalizeLines(lines any, opts *RequestOptions) ([]LineRecord, error) {
	level := "info"
	service := ""
	if opts != nil {
		if opts.Level != "" {
			level = opts.Level
		}
		service = opts.Service
	}

	switch value := lines.(type) {
	case []string:
		if len(value) == 0 {
			return nil, errors.New("lines must not be empty")
		}
		if len(value) > maxLogLines {
			return nil, fmt.Errorf("lines exceeds %d", maxLogLines)
		}
		out := make([]LineRecord, 0, len(value))
		for i, line := range value {
			if tooManyChars(line) {
				return nil, fmt.Errorf("line %d exceeds %d characters", i, maxLogLineChars)
			}
			out = append(out, LineRecord{
				LineID:  i,
				Message: line,
				Level:   level,
				Service: service,
			})
		}
		return out, nil
	case []LineRecord:
		if len(value) == 0 {
			return nil, errors.New("lines must not be empty")
		}
		if len(value) > maxLogLines {
			return nil, fmt.Errorf("lines exceeds %d", maxLogLines)
		}
		out := make([]LineRecord, len(value))
		copy(out, value)
		for i := range out {
			if tooManyChars(out[i].Message) {
				return nil, fmt.Errorf("line %d exceeds %d characters", i, maxLogLineChars)
			}
			// Backfill line_id from the array index when unset, matching the
			// []string branch and the Python/TypeScript clients. Go's int
			// zero value cannot distinguish "unset" from an explicit 0, so an
			// explicit 0 at a non-zero index is also backfilled.
			if out[i].LineID == 0 {
				out[i].LineID = i
			}
			if out[i].Level == "" {
				out[i].Level = level
			}
			if out[i].Service == "" && service != "" {
				out[i].Service = service
			}
		}
		return out, nil
	default:
		return nil, errors.New("lines must be []string or []codag.LineRecord")
	}
}

func (c *Client) requestJSON(ctx context.Context, method string, path string, payload any, out any, auth bool) error {
	if auth && c.APIKey == "" {
		return ErrMissingAPIKey
	}

	var body io.Reader
	if payload != nil {
		raw, err := marshalJSON(payload)
		if err != nil {
			return fmt.Errorf("marshal request: %w", err)
		}
		body = bytes.NewReader(raw)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", firstNonEmpty(c.UserAgent, defaultUserAgent))
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if auth {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	}

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return fmt.Errorf("cannot reach Codag server at %s: %w", c.BaseURL, err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBody+1))
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}
	if int64(len(raw)) > maxResponseBody {
		return fmt.Errorf("response exceeds %d bytes", maxResponseBody)
	}
	if resp.StatusCode/100 != 2 {
		return apiErrorForResponse(resp, string(raw))
	}
	if out == nil || len(raw) == 0 {
		return nil
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	return nil
}

func apiErrorForResponse(resp *http.Response, body string) error {
	detail := responseDetail(body)
	kind := error(nil)
	switch resp.StatusCode {
	case http.StatusUnauthorized:
		kind = ErrAuthentication
	case http.StatusPaymentRequired:
		kind = ErrBilling
	case http.StatusTooManyRequests:
		kind = ErrRateLimited
	}
	return &APIError{
		StatusCode:  resp.StatusCode,
		Body:        body,
		Detail:      detail,
		RetryAfter:  resp.Header.Get("Retry-After"),
		UpgradePath: resp.Header.Get("X-Codag-Upgrade"),
		Kind:        kind,
	}
}

func responseDetail(body string) string {
	var payload map[string]any
	if err := json.Unmarshal([]byte(body), &payload); err == nil {
		if detail, ok := payload["detail"].(string); ok {
			return detail
		}
	}
	return strings.TrimSpace(body)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

// tooManyChars reports whether s exceeds the per-line code-point limit.
// The byte length is an upper bound on the code-point count, so the O(n)
// rune count is only taken when the cheap byte check trips. Counting code
// points (not bytes) matches the server and the Python/TypeScript clients.
func tooManyChars(s string) bool {
	return len(s) > maxLogLineChars && utf8.RuneCountInString(s) > maxLogLineChars
}
