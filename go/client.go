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
	"strings"
	"time"
)

const (
	DefaultBaseURL       = "https://api.codag.ai"
	maxResponseBody      = 16 << 20
	maxLogLines          = 20_000
	maxLogLineChars      = 256 * 1024
	maxMetadataJSONBytes = 64 * 1024
	defaultUserAgent     = "codag-go/0.1.0"
)

var (
	ErrMissingAPIKey  = errors.New("missing Codag API key; pass WithAPIKey or set CODAG_API_KEY")
	ErrAuthentication = errors.New("codag authentication error")
	ErrBilling        = errors.New("codag billing action required")
	ErrRateLimited    = errors.New("codag rate limited or overloaded")
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
// May require a Codag Pro workspace; backend 402 responses unwrap to ErrBilling.
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
		raw, err := json.Marshal(opts.Metadata)
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
			if len(line) > maxLogLineChars {
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
			if out[i].Message == "" {
				return nil, fmt.Errorf("line %d is missing message", i)
			}
			if len(out[i].Message) > maxLogLineChars {
				return nil, fmt.Errorf("line %d exceeds %d characters", i, maxLogLineChars)
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
		raw, err := json.Marshal(payload)
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
