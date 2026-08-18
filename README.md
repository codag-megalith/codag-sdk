# Codag SDKs

Official open-source Go, Python, and TypeScript clients for Codag's coding-agent
cost API. The SDKs expose the same cloud features used by the private Codag
CLI: action-aware reduction, contentless metrics, savings, pricing, workspace
policy, trial reports, and service status.

Operating-system setup and local encrypted retrieval belong to the CLI. Run
`codag setup` for normal Claude Code and Codex use; use an SDK when embedding
Codag in an agent harness, CI system, or vendor backend.

## Quickstart

Create a workspace API key, keep it out of source control, and install a client:

```bash
export CODAG_API_KEY="<paste your cdk_ key>"
pip install codag
npm install @codag/sdk
go get github.com/codag-megalith/codag-sdk/go
```

Every SDK reads `CODAG_API_KEY` and defaults to `https://api.codag.ai`.
`CODAG_SERVER` overrides the API host.

Python:

```python
from codag import ActionEnvelope, Codag, ToolCall

client = Codag()
response = client.reduce_action(ActionEnvelope(
    id="action-01",
    kind="test_build_lint",
    tool=ToolCall(name="exec_command", arguments={"cmd": "pytest -q"}),
    result=large_test_output,
    task="fix the failing authentication tests",
    intent="verify the patch",
    retrieval_handle="local-action-01",
))
print(response.decision, response.content)
```

TypeScript:

```ts
import { Codag } from "@codag/sdk";

const client = new Codag();
const response = await client.reduceAction({
  id: "action-01",
  kind: "search",
  tool: { name: "grep", arguments: { pattern: "TODO" } },
  result: largeSearchOutput,
  retrieval_handle: "local-action-01",
});
console.log(response.decision, response.content);
```

Go:

```go
response, err := codag.New().ReduceAction(ctx, codag.ActionEnvelope{
    ID: "action-01",
    Kind: codag.ActionSearch,
    Tool: codag.ToolCall{Name: "grep", Arguments: map[string]any{"pattern": "TODO"}},
    Result: largeSearchOutput,
    RetrievalHandle: "local-action-01",
})
```

## Public API

- `POST /v1/actions/reduce`
- `POST /v1/metrics/batch`
- `GET /v1/usage/summary`
- `GET /v1/usage/timeseries`
- `GET /v1/usage/breakdown`
- `GET /v1/usage/reliability`
- `GET /v1/trials/report`
- `GET /v1/model-prices`
- `GET` and `PUT /v1/workspace/policy`
- `GET /v1/service/status`

The versioned contract is [openapi/codag-v1.openapi.json](openapi/codag-v1.openapi.json).

## Privacy and failure behavior

Action requests carry the observed tool call/result plus minimum task context
transiently. Codag does not retain those fields. Required accounting metrics
are contentless and reject unknown fields. Exact omitted data stays encrypted
on the user's machine and is retrieved only through bounded selectors.

Clients should treat any reduction error or hard-cap response as fail-open and
continue with the original result. Free includes 50 MB/month, Pro is $19/month
with 5 GB, Team is $499/month with 200 GB plus overage, and Enterprise is
contractual.

## Development

```bash
make test
```

The local suite uses mock servers. Live tests are opt-in with
`CODAG_API_KEY=cdk_... make test-live`.
