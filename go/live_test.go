//go:build live

// Live integration checks against a real Codag API server.
//
// Opt-in: excluded from plain `go test ./...` by the live build tag. Run with:
//
//	CODAG_API_KEY=cdk_... go test -tags live ./...
//
// CODAG_SERVER overrides the target host (defaults to the hosted API).
package codag

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
	"time"
)

var liveSampleLines = []string{
	"ERROR api db pool timeout active=20 waiting=30 path=/api/orders",
	"WARN api db pool nearing capacity active=18 path=/api/orders",
	"ERROR api db pool timeout active=21 waiting=31 path=/api/checkout",
	"INFO api request completed status=200 path=/api/health elapsed_ms=3",
	"ERROR worker job retry queue=email attempt=3 err=smtp_timeout",
}

func liveClient(t *testing.T) *Client {
	t.Helper()
	if os.Getenv("CODAG_API_KEY") == "" {
		t.Skip("CODAG_API_KEY is not set")
	}
	return New()
}

func TestLiveHealthReportsOK(t *testing.T) {
	client := liveClient(t)
	out, err := client.Health(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if out["status"] != "ok" {
		t.Fatalf("health = %v", out)
	}
}

func TestLiveCompactReturnsTextAndStats(t *testing.T) {
	client := liveClient(t)
	out, err := client.Compact(context.Background(), liveSampleLines, &RequestOptions{
		Service:  "api",
		Level:    "error",
		Metadata: map[string]any{"source": "sdk-live-test"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if out.Text == "" || out.Stats.ElapsedMS < 0 || out.CompactEngine == "" {
		t.Fatalf("bad compact response: %+v", out)
	}
}

func TestLiveCompactAcceptsRecords(t *testing.T) {
	client := liveClient(t)
	records := make([]LineRecord, len(liveSampleLines))
	for i, line := range liveSampleLines {
		records[i] = LineRecord{LineID: i, Message: line, Level: "error"}
	}
	out, err := client.Compact(context.Background(), records, nil)
	if err != nil {
		t.Fatal(err)
	}
	if out.Text == "" {
		t.Fatalf("bad compact response: %+v", out)
	}
}

func TestLiveCapsuleReturnsStructuredIncident(t *testing.T) {
	client := liveClient(t)
	out, err := client.Capsule(context.Background(), liveSampleLines, &RequestOptions{Level: "error"})
	if errors.Is(err, ErrBilling) {
		t.Skipf("workspace lacks capsule access: %v", err)
	}
	if err != nil {
		t.Fatal(err)
	}
	if out.Capsule["schema_version"] == nil || out.Capsule["incident"] == nil {
		t.Fatalf("bad capsule response: %+v", out)
	}
}

func TestLiveCompactJobLifecycle(t *testing.T) {
	client := liveClient(t)
	created, err := client.CreateCompactJob(context.Background(), liveSampleLines, &RequestOptions{
		Metadata: map[string]any{"source": "sdk-live-test"},
	})
	if errors.Is(err, ErrBilling) {
		t.Skipf("workspace lacks compact job access: %v", err)
	}
	if err != nil {
		t.Fatal(err)
	}
	if created.JobID == "" || !strings.HasSuffix(created.PollURL, created.JobID) {
		t.Fatalf("bad job create response: %+v", created)
	}
	job, err := client.WaitForCompactJob(context.Background(), created.JobID, &WaitOptions{
		PollInterval: time.Second,
		Timeout:      2 * time.Minute,
	})
	if err != nil {
		t.Fatal(err)
	}
	if job.Status != "succeeded" || job.Text == "" {
		t.Fatalf("bad finished job (error=%q): %+v", job.Error, job)
	}
}

func TestLiveUnknownJobMapsTo404(t *testing.T) {
	client := liveClient(t)
	_, err := client.GetCompactJob(context.Background(), "cj_sdk_live_does_not_exist")
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.StatusCode != 404 || apiErr.Detail == "" {
		t.Fatalf("expected 404 APIError, got %v", err)
	}
}

func TestLiveInvalidKeyMapsToAuthentication(t *testing.T) {
	client := liveClient(t)
	bad := New(WithAPIKey("cdk_sdk_live_invalid"), WithBaseURL(client.BaseURL))
	_, err := bad.Compact(context.Background(), liveSampleLines[:1], nil)
	if !errors.Is(err, ErrAuthentication) {
		t.Fatalf("expected ErrAuthentication, got %v", err)
	}
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.StatusCode != 401 || apiErr.Detail == "" {
		t.Fatalf("bad auth error: %+v", apiErr)
	}
}
