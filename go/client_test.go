package codag

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type capturedRequest struct {
	Method string
	Path   string
	Header http.Header
	Body   []byte
}

type mockSpec struct {
	Status int
	Body   []byte
	Header http.Header
	Err    error
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) {
	return f(r)
}

func newMockClient(responses map[string][]mockSpec) (*Client, *[]capturedRequest) {
	calls := []capturedRequest{}
	httpClient := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		var body []byte
		if r.Body != nil {
			body, _ = io.ReadAll(r.Body)
		}
		calls = append(calls, capturedRequest{
			Method: r.Method,
			Path:   r.URL.Path,
			Header: r.Header.Clone(),
			Body:   body,
		})
		queue := responses[r.URL.Path]
		if len(queue) == 0 {
			return jsonResponse(http.StatusOK, []byte(`{"ok":true}`), nil), nil
		}
		spec := queue[0]
		responses[r.URL.Path] = queue[1:]
		if spec.Err != nil {
			return nil, spec.Err
		}
		status := spec.Status
		if status == 0 {
			status = http.StatusOK
		}
		return jsonResponse(status, spec.Body, spec.Header), nil
	})}
	return New(WithAPIKey("cdk_test"), WithBaseURL("http://codag.test"), WithHTTPClient(httpClient)), &calls
}

func jsonSpec(status int, body []byte, headers http.Header) mockSpec {
	return mockSpec{Status: status, Body: body, Header: headers}
}

func jsonResponse(status int, body []byte, headers http.Header) *http.Response {
	if headers == nil {
		headers = make(http.Header)
	}
	headers.Set("Content-Type", "application/json")
	return &http.Response{
		StatusCode: status,
		Header:     headers,
		Body:       io.NopCloser(bytes.NewReader(body)),
	}
}

func decodePayload[T any](t *testing.T, body []byte) T {
	t.Helper()
	var out T
	if err := json.Unmarshal(body, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestClientConfiguration(t *testing.T) {
	t.Run("default base url", func(t *testing.T) {
		t.Setenv("CODAG_SERVER", "")
		t.Setenv("CODAG_API_KEY", "")
		client := New(WithAPIKey("cdk_test"))
		if client.BaseURL != DefaultBaseURL {
			t.Fatalf("BaseURL = %q", client.BaseURL)
		}
	})
	t.Run("base url trims slash", func(t *testing.T) {
		client := New(WithAPIKey("cdk_test"), WithBaseURL("http://codag.test///"))
		if client.BaseURL != "http://codag.test" {
			t.Fatalf("BaseURL = %q", client.BaseURL)
		}
	})
	t.Run("server env supplies base url", func(t *testing.T) {
		t.Setenv("CODAG_SERVER", "http://env.test/")
		client := New(WithAPIKey("cdk_test"))
		if client.BaseURL != "http://env.test" {
			t.Fatalf("BaseURL = %q", client.BaseURL)
		}
	})
	t.Run("constructor base url wins over env", func(t *testing.T) {
		t.Setenv("CODAG_SERVER", "http://env.test")
		client := New(WithAPIKey("cdk_test"), WithBaseURL("http://arg.test"))
		if client.BaseURL != "http://arg.test" {
			t.Fatalf("BaseURL = %q", client.BaseURL)
		}
	})
	t.Run("api key env supplies key", func(t *testing.T) {
		t.Setenv("CODAG_API_KEY", "cdk_env")
		client := New(WithBaseURL("http://codag.test"))
		if client.APIKey != "cdk_env" {
			t.Fatalf("APIKey = %q", client.APIKey)
		}
	})
	t.Run("constructor api key wins over env", func(t *testing.T) {
		t.Setenv("CODAG_API_KEY", "cdk_env")
		client := New(WithAPIKey("cdk_arg"))
		if client.APIKey != "cdk_arg" {
			t.Fatalf("APIKey = %q", client.APIKey)
		}
	})
}

func TestHealthRequests(t *testing.T) {
	t.Run("uses GET without auth", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{
			"/health": {jsonSpec(http.StatusOK, []byte(`{"ok":true}`), nil)},
		})
		out, err := client.Health(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if out["ok"] != true || (*calls)[0].Method != http.MethodGet || (*calls)[0].Header.Get("Authorization") != "" {
			t.Fatalf("bad health call: out=%v call=%+v", out, (*calls)[0])
		}
	})
	t.Run("omits content type", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{
			"/health": {jsonSpec(http.StatusOK, []byte(`{"ok":true}`), nil)},
		})
		_, err := client.Health(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if got := (*calls)[0].Header.Get("Content-Type"); got != "" {
			t.Fatalf("Content-Type = %q", got)
		}
	})
}

func TestCompactRequests(t *testing.T) {
	fixture := readFixture(t, "compact_response.json")
	t.Run("posts to compact endpoint", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		if _, err := client.Compact(context.Background(), []string{"ERROR one"}, nil); err != nil {
			t.Fatal(err)
		}
		if (*calls)[0].Method != http.MethodPost || (*calls)[0].Path != "/v1/compact" {
			t.Fatalf("bad call: %+v", (*calls)[0])
		}
	})
	t.Run("sends bearer token", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		_, _ = client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if got := (*calls)[0].Header.Get("Authorization"); got != "Bearer cdk_test" {
			t.Fatalf("Authorization = %q", got)
		}
	})
	t.Run("sends json content type", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		_, _ = client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if got := (*calls)[0].Header.Get("Content-Type"); got != "application/json" {
			t.Fatalf("Content-Type = %q", got)
		}
	})
	t.Run("sends user agent", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		_, _ = client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if got := (*calls)[0].Header.Get("User-Agent"); got != defaultUserAgent {
			t.Fatalf("User-Agent = %q", got)
		}
	})
	t.Run("decodes text and stats", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		out, err := client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(out.Text, "# codag compact") || out.Stats.ElapsedMS != 31 {
			t.Fatalf("bad output: %+v", out)
		}
	})
	t.Run("decodes engine fields", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		out, err := client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if err != nil {
			t.Fatal(err)
		}
		if out.CompactEngine != "mvp" || out.CompactFallback != "" {
			t.Fatalf("bad engine fields: %+v", out)
		}
	})
	t.Run("sends metadata", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		_, err := client.Compact(context.Background(), []string{"ERROR one"}, &RequestOptions{Metadata: map[string]any{"source": "unit"}})
		if err != nil {
			t.Fatal(err)
		}
		payload := decodePayload[CapsuleRequest](t, (*calls)[0].Body)
		if payload.Metadata["source"] != "unit" {
			t.Fatalf("metadata = %#v", payload.Metadata)
		}
	})
	t.Run("omits metadata when nil", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/compact": {jsonSpec(200, fixture, nil)}})
		_, _ = client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if bytes.Contains((*calls)[0].Body, []byte("metadata")) {
			t.Fatalf("body should omit metadata: %s", (*calls)[0].Body)
		}
	})
}

func TestCapsuleRequests(t *testing.T) {
	fixture := readFixture(t, "capsule_response.json")
	t.Run("posts to capsule endpoint", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/capsule": {jsonSpec(200, fixture, nil)}})
		if _, err := client.Capsule(context.Background(), []string{"ERROR one"}, nil); err != nil {
			t.Fatal(err)
		}
		if (*calls)[0].Path != "/v1/capsule" {
			t.Fatalf("Path = %q", (*calls)[0].Path)
		}
	})
	t.Run("decodes fixture", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{"/v1/capsule": {jsonSpec(200, fixture, nil)}})
		out, err := client.Capsule(context.Background(), []LineRecord{{Message: "ERROR one", Level: "error"}}, nil)
		if err != nil {
			t.Fatal(err)
		}
		if out.Capsule["schema_version"] != "0.3" || out.Stats.LLMCalls != 1 {
			t.Fatalf("bad capsule: %+v", out)
		}
	})
	t.Run("sends metadata", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{"/v1/capsule": {jsonSpec(200, fixture, nil)}})
		_, _ = client.Capsule(context.Background(), []string{"ERROR one"}, &RequestOptions{Metadata: map[string]any{"source": "go"}})
		payload := decodePayload[CapsuleRequest](t, (*calls)[0].Body)
		if payload.Metadata["source"] != "go" {
			t.Fatalf("metadata = %#v", payload.Metadata)
		}
	})
}

func TestCompactJobs(t *testing.T) {
	t.Run("create decodes response", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/compact/jobs": {jsonSpec(200, []byte(`{"job_id":"cj_1","status":"queued","poll_url":"/v1/compact/jobs/cj_1"}`), nil)},
		})
		out, err := client.CreateCompactJob(context.Background(), []string{"ERROR one"}, nil)
		if err != nil {
			t.Fatal(err)
		}
		if out.JobID != "cj_1" || out.Status != "queued" {
			t.Fatalf("bad job create: %+v", out)
		}
	})
	t.Run("create sends metadata", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{
			"/v1/compact/jobs": {jsonSpec(200, []byte(`{"job_id":"cj_1","status":"queued","poll_url":"/v1/compact/jobs/cj_1"}`), nil)},
		})
		_, _ = client.CreateCompactJob(context.Background(), []string{"ERROR one"}, &RequestOptions{Metadata: map[string]any{"source": "ci"}})
		payload := decodePayload[CapsuleRequest](t, (*calls)[0].Body)
		if payload.Metadata["source"] != "ci" {
			t.Fatalf("metadata = %#v", payload.Metadata)
		}
	})
	t.Run("get decodes stats null", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/compact/jobs/cj_1": {jsonSpec(200, []byte(`{"job_id":"cj_1","status":"succeeded","text":"ok","stats":null}`), nil)},
		})
		out, err := client.GetCompactJob(context.Background(), "cj_1")
		if err != nil {
			t.Fatal(err)
		}
		if out.Text != "ok" || out.Stats != nil {
			t.Fatalf("bad job: %+v", out)
		}
	})
	t.Run("get decodes stats object", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/compact/jobs/cj_1": {jsonSpec(200, []byte(`{"job_id":"cj_1","status":"succeeded","text":"ok","stats":{"llm_calls":0,"cache_hits":1,"unmatched":0,"elapsed_ms":5}}`), nil)},
		})
		out, err := client.GetCompactJob(context.Background(), "cj_1")
		if err != nil {
			t.Fatal(err)
		}
		if out.Stats == nil || out.Stats.CacheHits != 1 {
			t.Fatalf("bad stats: %+v", out.Stats)
		}
	})
	t.Run("get rejects empty id", func(t *testing.T) {
		client, _ := newMockClient(nil)
		if _, err := client.GetCompactJob(context.Background(), ""); err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("wait returns completed after queued", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{
			"/v1/compact/jobs/cj_1": {
				jsonSpec(200, []byte(`{"job_id":"cj_1","status":"queued"}`), nil),
				jsonSpec(200, []byte(`{"job_id":"cj_1","status":"succeeded","text":"ok"}`), nil),
			},
		})
		out, err := client.WaitForCompactJob(context.Background(), "cj_1", &WaitOptions{PollInterval: time.Nanosecond, Timeout: time.Second})
		if err != nil {
			t.Fatal(err)
		}
		if out.Text != "ok" || len(*calls) != 2 {
			t.Fatalf("bad wait: out=%+v calls=%d", out, len(*calls))
		}
	})
	t.Run("wait surfaces context cancellation", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/compact/jobs/cj_1": {jsonSpec(200, []byte(`{"job_id":"cj_1","status":"queued"}`), nil)},
		})
		ctx, cancel := context.WithCancel(context.Background())
		go func() {
			time.Sleep(10 * time.Millisecond)
			cancel()
		}()
		_, err := client.WaitForCompactJob(ctx, "cj_1", &WaitOptions{PollInterval: time.Hour, Timeout: time.Hour})
		if !errors.Is(err, context.Canceled) || strings.Contains(err.Error(), "did not finish within") {
			t.Fatalf("bad cancellation error: %v", err)
		}
	})
	t.Run("wait returns failed job", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/compact/jobs/cj_1": {jsonSpec(200, []byte(`{"job_id":"cj_1","status":"failed","error":"boom"}`), nil)},
		})
		out, err := client.WaitForCompactJob(context.Background(), "cj_1", &WaitOptions{PollInterval: time.Nanosecond, Timeout: time.Second})
		if err != nil {
			t.Fatal(err)
		}
		if out.Error != "boom" {
			t.Fatalf("bad failed job: %+v", out)
		}
	})
}

func TestNormalizeLinesStrings(t *testing.T) {
	t.Run("assigns ids", func(t *testing.T) {
		out, err := NormalizeLines([]string{"a", "b"}, nil)
		if err != nil {
			t.Fatal(err)
		}
		if out[0].LineID != 0 || out[1].LineID != 1 {
			t.Fatalf("bad ids: %+v", out)
		}
	})
	t.Run("default level", func(t *testing.T) {
		out, _ := NormalizeLines([]string{"a"}, nil)
		if out[0].Level != "info" {
			t.Fatalf("level = %q", out[0].Level)
		}
	})
	t.Run("custom level", func(t *testing.T) {
		out, _ := NormalizeLines([]string{"a"}, &RequestOptions{Level: "error"})
		if out[0].Level != "error" {
			t.Fatalf("level = %q", out[0].Level)
		}
	})
	t.Run("service", func(t *testing.T) {
		out, _ := NormalizeLines([]string{"a"}, &RequestOptions{Service: "api"})
		if out[0].Service != "api" {
			t.Fatalf("service = %q", out[0].Service)
		}
	})
	t.Run("message preserved", func(t *testing.T) {
		out, _ := NormalizeLines([]string{"ERROR one"}, nil)
		if out[0].Message != "ERROR one" {
			t.Fatalf("message = %q", out[0].Message)
		}
	})
	t.Run("line count preserved", func(t *testing.T) {
		out, _ := NormalizeLines([]string{"a", "b", "c"}, nil)
		if len(out) != 3 {
			t.Fatalf("len = %d", len(out))
		}
	})
}

func TestNormalizeLinesRecords(t *testing.T) {
	t.Run("preserves line id", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{LineID: 99, Message: "a"}}, nil)
		if out[0].LineID != 99 {
			t.Fatalf("line id = %d", out[0].LineID)
		}
	})
	t.Run("backfills line id from index when unset", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{Message: "a"}, {Message: "b"}, {Message: "c"}}, nil)
		if out[0].LineID != 0 || out[1].LineID != 1 || out[2].LineID != 2 {
			t.Fatalf("line ids = %d,%d,%d", out[0].LineID, out[1].LineID, out[2].LineID)
		}
	})
	t.Run("default level", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{Message: "a"}}, nil)
		if out[0].Level != "info" {
			t.Fatalf("level = %q", out[0].Level)
		}
	})
	t.Run("preserves level", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{Message: "a", Level: "warn"}}, nil)
		if out[0].Level != "warn" {
			t.Fatalf("level = %q", out[0].Level)
		}
	})
	t.Run("fills service", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{Message: "a"}}, &RequestOptions{Service: "api"})
		if out[0].Service != "api" {
			t.Fatalf("service = %q", out[0].Service)
		}
	})
	t.Run("does not override service", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{Message: "a", Service: "worker"}}, &RequestOptions{Service: "api"})
		if out[0].Service != "worker" {
			t.Fatalf("service = %q", out[0].Service)
		}
	})
	t.Run("preserves timestamp", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{Message: "a", Timestamp: "2026-07-01T00:00:00Z"}}, nil)
		if out[0].Timestamp == "" {
			t.Fatal("timestamp missing")
		}
	})
	t.Run("copies input slice", func(t *testing.T) {
		input := []LineRecord{{Message: "a"}}
		out, _ := NormalizeLines(input, &RequestOptions{Service: "api"})
		if input[0].Service != "" || out[0].Service != "api" {
			t.Fatalf("input=%+v out=%+v", input, out)
		}
	})
	t.Run("line count preserved", func(t *testing.T) {
		out, _ := NormalizeLines([]LineRecord{{Message: "a"}, {Message: "b"}}, nil)
		if len(out) != 2 {
			t.Fatalf("len = %d", len(out))
		}
	})
}

func TestNormalizeLinesValidation(t *testing.T) {
	t.Run("rejects empty string slice", func(t *testing.T) {
		_, err := NormalizeLines([]string{}, nil)
		if err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("rejects empty record slice", func(t *testing.T) {
		_, err := NormalizeLines([]LineRecord{}, nil)
		if err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("rejects too many strings", func(t *testing.T) {
		_, err := NormalizeLines(make([]string, maxLogLines+1), nil)
		if err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("rejects too many records", func(t *testing.T) {
		_, err := NormalizeLines(make([]LineRecord, maxLogLines+1), nil)
		if err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("rejects too long string", func(t *testing.T) {
		_, err := NormalizeLines([]string{strings.Repeat("x", maxLogLineChars+1)}, nil)
		if err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("accepts empty record message", func(t *testing.T) {
		// Parity with the []string branch and the Python/TypeScript clients,
		// which all accept empty-string messages.
		out, err := NormalizeLines([]LineRecord{{Message: ""}}, nil)
		if err != nil || len(out) != 1 {
			t.Fatalf("expected empty message accepted, got out=%+v err=%v", out, err)
		}
	})
	t.Run("counts message length in runes not bytes", func(t *testing.T) {
		// maxLogLineChars multibyte code points: over the byte limit but at
		// the code-point limit, so it must be accepted (matches server).
		msg := strings.Repeat("世", maxLogLineChars)
		if _, err := NormalizeLines([]string{msg}, nil); err != nil {
			t.Fatalf("multibyte line at the code-point limit should be accepted: %v", err)
		}
		if _, err := NormalizeLines([]string{strings.Repeat("世", maxLogLineChars+1)}, nil); err == nil {
			t.Fatal("expected error one rune over the limit")
		}
	})
	t.Run("rejects invalid type", func(t *testing.T) {
		_, err := NormalizeLines(123, nil)
		if err == nil {
			t.Fatal("expected error")
		}
	})
}

func TestBuildCapsuleRequestMetadata(t *testing.T) {
	t.Run("includes metadata", func(t *testing.T) {
		req, err := BuildCapsuleRequest([]string{"a"}, &RequestOptions{Metadata: map[string]any{"source": "unit"}})
		if err != nil {
			t.Fatal(err)
		}
		if req.Metadata["source"] != "unit" {
			t.Fatalf("metadata = %#v", req.Metadata)
		}
	})
	t.Run("omits nil metadata", func(t *testing.T) {
		req, err := BuildCapsuleRequest([]string{"a"}, nil)
		if err != nil {
			t.Fatal(err)
		}
		if req.Metadata != nil {
			t.Fatalf("metadata = %#v", req.Metadata)
		}
	})
	t.Run("rejects oversized metadata", func(t *testing.T) {
		_, err := BuildCapsuleRequest([]string{"a"}, &RequestOptions{Metadata: map[string]any{"x": strings.Repeat("y", maxMetadataJSONBytes)}})
		if err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("rejects unmarshalable metadata", func(t *testing.T) {
		_, err := BuildCapsuleRequest([]string{"a"}, &RequestOptions{Metadata: map[string]any{"x": func() {}}})
		if err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("does not html-escape metadata when sizing", func(t *testing.T) {
		// 60000 '<' chars serialize to ~60013 bytes without HTML escaping
		// (accepted, matching Python/TS) but ~360000 bytes if each '<' became
		// <, which would wrongly exceed the 64KB limit.
		req, err := BuildCapsuleRequest([]string{"a"}, &RequestOptions{Metadata: map[string]any{"x": strings.Repeat("<", 60000)}})
		if err != nil {
			t.Fatalf("html-heavy metadata under the limit should be accepted: %v", err)
		}
		if req.Metadata == nil {
			t.Fatal("metadata dropped")
		}
	})
}

func TestMarshalJSONNoHTMLEscape(t *testing.T) {
	raw, err := marshalJSON(map[string]any{"x": "<a>&</a>"})
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(raw, []byte("<a>&</a>")) || bytes.Contains(raw, []byte("\\u003c")) {
		t.Fatalf("expected raw <,>,& with no trailing newline: %q", raw)
	}
	if bytes.HasSuffix(raw, []byte("\n")) {
		t.Fatalf("trailing newline not trimmed: %q", raw)
	}
}

func TestAPIErrorMapping(t *testing.T) {
	cases := []struct {
		name       string
		status     int
		body       string
		headers    http.Header
		sentinel   error
		detail     string
		retryAfter string
		upgrade    string
	}{
		{"401 auth", http.StatusUnauthorized, `{"detail":"invalid API key"}`, nil, ErrAuthentication, "invalid API key", "", ""},
		{"402 billing", http.StatusPaymentRequired, `{"detail":"billing_required"}`, http.Header{"X-Codag-Upgrade": []string{"/dashboard/billing"}}, ErrBilling, "billing_required", "", "/dashboard/billing"},
		{"429 rate limit", http.StatusTooManyRequests, `{"detail":"busy"}`, http.Header{"Retry-After": []string{"5"}}, ErrRateLimited, "busy", "5", ""},
		{"500 api", http.StatusInternalServerError, `{"detail":"server_error"}`, nil, nil, "server_error", "", ""},
		{"plain body", http.StatusBadGateway, `plain failure`, nil, nil, "plain failure", "", ""},
		{"json without detail", http.StatusBadRequest, `{"error":"bad"}`, nil, nil, `{"error":"bad"}`, "", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			client, _ := newMockClient(map[string][]mockSpec{
				"/v1/compact": {jsonSpec(tc.status, []byte(tc.body), tc.headers)},
			})
			_, err := client.Compact(context.Background(), []string{"ERROR one"}, nil)
			if err == nil {
				t.Fatal("expected error")
			}
			if tc.sentinel != nil && !errors.Is(err, tc.sentinel) {
				t.Fatalf("expected sentinel %v, got %v", tc.sentinel, err)
			}
			var apiErr *APIError
			if !errors.As(err, &apiErr) {
				t.Fatalf("expected APIError, got %T", err)
			}
			if apiErr.Detail != tc.detail || apiErr.RetryAfter != tc.retryAfter || apiErr.UpgradePath != tc.upgrade {
				t.Fatalf("bad api error: %+v", apiErr)
			}
		})
	}
}

func TestTransportAndDecodeErrors(t *testing.T) {
	t.Run("missing api key fails before request", func(t *testing.T) {
		t.Setenv("CODAG_API_KEY", "")
		client := New(WithBaseURL("http://codag.test"))
		_, err := client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if !errors.Is(err, ErrMissingAPIKey) {
			t.Fatalf("expected missing key, got %v", err)
		}
	})
	t.Run("transport error returned", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/compact": {{Err: errors.New("refused")}},
		})
		_, err := client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if err == nil || !strings.Contains(err.Error(), "cannot reach Codag server") {
			t.Fatalf("bad error: %v", err)
		}
	})
	t.Run("invalid success json returns decode error", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/compact": {jsonSpec(200, []byte(`{not-json`), nil)},
		})
		_, err := client.Compact(context.Background(), []string{"ERROR one"}, nil)
		if err == nil || !strings.Contains(err.Error(), "decode response") {
			t.Fatalf("bad error: %v", err)
		}
	})
}

func TestActionCostAPI(t *testing.T) {
	t.Run("reduce action", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{
			"/v1/actions/reduce": {jsonSpec(200, []byte(`{"action_id":"a1","kind":"search","decision":"reduced","content":"one match","selectors":[{"id":"matches","type":"lines","start":1,"end":2}],"usage":{"bytes_in":100,"bytes_out":9}}`), nil)},
		})
		out, err := client.ReduceAction(context.Background(), ActionEnvelope{
			ID: "a1", Kind: ActionSearch, Tool: ToolCall{Name: "grep", Arguments: map[string]any{"q": "needle"}},
			Result: "many matches", RetrievalHandle: "local-a1",
		})
		if err != nil || out.Decision != "reduced" || out.Selectors[0].Start != 1 {
			t.Fatalf("out=%+v err=%v", out, err)
		}
		if (*calls)[0].Method != http.MethodPost || (*calls)[0].Path != "/v1/actions/reduce" {
			t.Fatalf("bad call: %+v", (*calls)[0])
		}
	})

	t.Run("reject incomplete action", func(t *testing.T) {
		client, _ := newMockClient(nil)
		if _, err := client.ReduceAction(context.Background(), ActionEnvelope{ID: "a1"}); err == nil {
			t.Fatal("expected validation error")
		}
	})

	t.Run("metrics", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{
			"/v1/metrics/batch": {jsonSpec(200, []byte(`{"accepted":1}`), nil)},
		})
		accepted, err := client.SendMetrics(context.Background(), []MetricEvent{{
			ID: "e1", OccurredAt: time.Now(), ActionKind: ActionSearch, Decision: "passthrough",
		}})
		if err != nil || accepted != 1 {
			t.Fatalf("accepted=%d err=%v", accepted, err)
		}
		if bytes.Contains((*calls)[0].Body, []byte(`"result"`)) {
			t.Fatalf("metrics unexpectedly contain result: %s", (*calls)[0].Body)
		}
	})

	t.Run("metrics reject content-like labels", func(t *testing.T) {
		client, _ := newMockClient(nil)
		_, err := client.SendMetrics(context.Background(), []MetricEvent{{
			ID: "e1", OccurredAt: time.Now(), ActionKind: ActionSearch,
			Decision: "passthrough", Model: "/Users/alice/private.bin",
		}})
		if err == nil {
			t.Fatal("expected contentless token validation error")
		}
	})

	t.Run("usage summary", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/usage/summary": {jsonSpec(200, []byte(`{"period_start":"2026-08-01T00:00:00Z","period_end":"2026-09-01T00:00:00Z","plan_tier":"pro","estimated_provider_spend_microusd":50,"estimated_saved_microusd":60}`), nil)},
		})
		out, err := client.UsageSummary(context.Background())
		if err != nil || out.PlanTier != "pro" || out.EstimatedProviderSpendMicroUSD != 50 || out.EstimatedSavedMicroUSD != 60 {
			t.Fatalf("out=%+v err=%v", out, err)
		}
	})

	t.Run("model prices", func(t *testing.T) {
		client, _ := newMockClient(map[string][]mockSpec{
			"/v1/model-prices": {jsonSpec(200, []byte(`{"currency":"USD","unit":"per_million_tokens","models":[{"provider":"openai","model_pattern":"gpt-5.6-sol","input_usd_per_mtok":5,"cached_input_usd_per_mtok":0.5,"cache_write_usd_per_mtok":6.25,"output_usd_per_mtok":30,"as_of":"2026-08-12","source_url":"https://developers.openai.com/api/docs/models"}]}`), nil)},
		})
		out, err := client.ModelPrices(context.Background())
		if err != nil || out.Currency != "USD" || len(out.Models) != 1 || out.Models[0].ModelPattern != "gpt-5.6-sol" || out.Models[0].OutputUSDPerMTok != 30 {
			t.Fatalf("out=%+v err=%v", out, err)
		}
	})

	t.Run("breakdown", func(t *testing.T) {
		client, calls := newMockClient(nil)
		if _, err := client.UsageBreakdown(context.Background(), &UsageQuery{Days: 14, Dimension: "member"}); err != nil {
			t.Fatal(err)
		}
		if (*calls)[0].Path != "/v1/usage/breakdown" {
			t.Fatalf("path=%q", (*calls)[0].Path)
		}
	})

	t.Run("invalid days", func(t *testing.T) {
		client, _ := newMockClient(nil)
		if _, err := client.UsageTimeseries(context.Background(), &UsageQuery{Days: 91}); err == nil {
			t.Fatal("expected validation error")
		}
	})

	t.Run("policy put", func(t *testing.T) {
		client, calls := newMockClient(map[string][]mockSpec{
			"/v1/workspace/policy": {jsonSpec(200, []byte(`{"mode":"audit","enabled_actions":["search"],"required_metrics":true}`), nil)},
		})
		out, err := client.SetWorkspacePolicy(context.Background(), WorkspacePolicy{
			Mode: "audit", EnabledActions: []ActionKind{ActionSearch}, RequiredMetrics: true,
		})
		if err != nil || out.Mode != "audit" || (*calls)[0].Method != http.MethodPut {
			t.Fatalf("out=%+v call=%+v err=%v", out, (*calls)[0], err)
		}
	})

	t.Run("service status", func(t *testing.T) {
		client, calls := newMockClient(nil)
		out, err := client.ServiceStatus(context.Background())
		if err != nil || out["ok"] != true || (*calls)[0].Header.Get("Authorization") != "Bearer cdk_test" {
			t.Fatalf("out=%v call=%+v err=%v", out, (*calls)[0], err)
		}
	})
}

func readFixture(t *testing.T, name string) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "fixtures", name))
	if err != nil {
		t.Fatal(err)
	}
	return raw
}
