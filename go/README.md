# Codag Go SDK

Go client for Codag's coding-agent cost API.

```bash
export CODAG_API_KEY="<paste your cdk_ key>"
go get github.com/codag-megalith/codag-sdk/go
```

```go
client := codag.New()
result, err := client.ReduceAction(ctx, codag.ActionEnvelope{
    ID: "action-1",
    Kind: codag.ActionSearch,
    Tool: codag.ToolCall{Name: "grep", Arguments: map[string]any{"pattern": "TODO"}},
    Result: largeSearchOutput,
    RetrievalHandle: "local-action-1",
})
```

SDK authentication is API-key only. Local harness attachment and encrypted
retrieval are handled by `codag setup` in the CLI.
