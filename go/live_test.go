//go:build live

// Opt-in integration checks against the hosted Codag action-cost API.
// Run with CODAG_API_KEY=cdk_... go test -tags live ./....
package codag

import (
	"context"
	"errors"
	"os"
	"testing"
)

const liveFileList = "README.md\ngo/client.go\ngo/client_test.go"

func liveClient(t *testing.T) *Client {
	t.Helper()
	if os.Getenv("CODAG_API_KEY") == "" {
		t.Skip("CODAG_API_KEY is not set")
	}
	return New()
}

func TestLiveHealthReportsOK(t *testing.T) {
	out, err := liveClient(t).Health(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if out["status"] != "ok" {
		t.Fatalf("health = %v", out)
	}
}

func TestLiveServiceStatusReportsReducerState(t *testing.T) {
	out, err := liveClient(t).ServiceStatus(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if out["status"] != "ok" {
		t.Fatalf("service status = %v", out)
	}
	if _, ok := out["reducer_configured"].(bool); !ok {
		t.Fatalf("reducer_configured is not a bool: %v", out)
	}
}

func TestLiveActionPassthroughDecodes(t *testing.T) {
	out, err := liveClient(t).ReduceAction(context.Background(), ActionEnvelope{
		ID:            "sdk-live-go-v020",
		Kind:          ActionFileList,
		Tool:          ToolCall{Name: "list_files", Arguments: map[string]any{}},
		Result:        liveFileList,
		Harness:       "openai_compatible",
		ClientVersion: "0.2.0",
	})
	if err != nil {
		t.Fatal(err)
	}
	if out.ActionID != "sdk-live-go-v020" || out.Kind != ActionFileList {
		t.Fatalf("bad action identity: %+v", out)
	}
	if out.Decision != "passthrough" || out.Reason != "conservative_passthrough" {
		t.Fatalf("bad passthrough decision: %+v", out)
	}
	if out.Usage.BytesIn != int64(len([]byte(liveFileList))) || out.Usage.BytesOut != out.Usage.BytesIn {
		t.Fatalf("bad passthrough usage: %+v", out.Usage)
	}
}

func TestLiveUsageAndPricingContractsDecode(t *testing.T) {
	client := liveClient(t)
	usage, err := client.UsageSummary(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if usage.PeriodStart.IsZero() || usage.PeriodEnd.IsZero() || usage.BytesUsed < 0 {
		t.Fatalf("bad usage summary: %+v", usage)
	}
	prices, err := client.ModelPrices(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if prices.Currency != "USD" || len(prices.Models) == 0 {
		t.Fatalf("bad price catalog: %+v", prices)
	}
}

func TestLiveWorkspacePolicyDecodes(t *testing.T) {
	policy, err := liveClient(t).GetWorkspacePolicy(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if policy.Mode != "disabled" && policy.Mode != "audit" && policy.Mode != "optimize" {
		t.Fatalf("bad workspace policy: %+v", policy)
	}
	if !policy.RequiredMetrics {
		t.Fatalf("required metrics unexpectedly disabled: %+v", policy)
	}
}

func TestLiveInvalidKeyMapsToAuthentication(t *testing.T) {
	client := liveClient(t)
	bad := New(WithAPIKey("cdk_sdk_live_invalid"), WithBaseURL(client.BaseURL))
	_, err := bad.ServiceStatus(context.Background())
	if !errors.Is(err, ErrAuthentication) {
		t.Fatalf("expected ErrAuthentication, got %v", err)
	}
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.StatusCode != 401 || apiErr.Detail == "" {
		t.Fatalf("bad auth error: %+v", apiErr)
	}
}

func TestLiveInvalidActionFailsBeforeNetwork(t *testing.T) {
	_, err := liveClient(t).ReduceAction(context.Background(), ActionEnvelope{ID: "incomplete"})
	if err == nil {
		t.Fatal("expected validation error")
	}
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		t.Fatalf("validation unexpectedly reached the API: %+v", apiErr)
	}
}
