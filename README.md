# Codag SDKs

Official open-source SDKs for the Codag hosted API.

This repository contains the Python, TypeScript, and Go clients. The SDKs call
the same backend used by the Codag CLI, but they are intended for applications,
agents, CI systems, and vendor backends that need to compress logs inside their
own pipelines.

## Repository Shape

The SDKs live together in one repository so they share one contract snapshot,
fixtures, error semantics, docs, and CI:

```text
codag-sdk/
  openapi/codag-v1.openapi.json
  fixtures/
  python/
  typescript/
  go/
```

The hosted API, billing system, model-serving code, and evaluation harness do
not live here. The human CLI and MCP server remain in `codag-cli`.

## Auth

SDK v1 is API-key only.

Resolution order:

1. Constructor option
2. `CODAG_API_KEY`

The default API host is `https://api.codag.ai`. Override it with a constructor
option or `CODAG_SERVER`.

SDKs do not read CLI OAuth config, launch device-flow login, or use anonymous
free compact fallback. Those flows belong to the CLI.

## Installation status

The published packages are cut from tagged releases of this repository. Until a
release is tagged you can install any SDK directly from a local checkout (see
each language section). The registry commands below assume a published release:

| Language   | Command                                         | Registry |
| ---------- | ----------------------------------------------- | -------- |
| Python     | `pip install codag`                             | PyPI     |
| TypeScript | `npm install @codag/sdk`                         | npm      |
| Go         | `go get github.com/codag-megalith/codag-sdk/go` | proxy    |

## Python

Install a published release from PyPI:

```bash
pip install codag
```

Or from a local checkout of this repository:

```bash
cd python
python -m pip install -e .
```

```python
from codag import Codag

client = Codag(api_key="cdk_...")
result = client.compact([
    "ERROR api db pool timeout active=20 waiting=30 path=/api/orders",
])

print(result.text)
print(result.stats.elapsed_ms)
```

Async convenience methods are available through `AsyncCodag`. They wrap the
sync implementation without adding runtime dependencies.

## TypeScript

```bash
cd typescript
npm install @codag/sdk
```

```ts
import { Codag } from "@codag/sdk";

const client = new Codag({ apiKey: process.env.CODAG_API_KEY });
const result = await client.compact([
  "ERROR api db pool timeout active=20 waiting=30 path=/api/orders",
]);

console.log(result.text);
console.log(result.stats.elapsed_ms);
```

The TypeScript SDK ships as dependency-free ESM JavaScript plus `.d.ts` types
and uses the platform `fetch` implementation.

## Go

```bash
go get github.com/codag-megalith/codag-sdk/go
```

```go
package main

import (
	"context"
	"fmt"
	"log"

	codag "github.com/codag-megalith/codag-sdk/go"
)

func main() {
	client := codag.New()
	result, err := client.Compact(context.Background(), []string{
		"ERROR api db pool timeout active=20 waiting=30 path=/api/orders",
	}, nil)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(result.Text)
}
```

## Supported API

- `POST /v1/compact`
- `POST /v1/capsule`
- `POST /v1/compact/jobs`
- `GET /v1/compact/jobs/{job_id}`
- `GET /health`

`/v1/capsule` and compact jobs may require a Codag Pro workspace. The SDKs
surface backend `402` responses as billing errors with the upgrade path when
the server provides one.

Compact jobs report `status` values `queued`, `running`, `succeeded`, or
`failed`. The `wait_for_compact_job` helpers return as soon as the job leaves
the `queued`/`running` states.

## Development

Run all local checks:

```bash
make test
```

The tests use only local mock servers and fixtures.

To exercise the hosted service end to end, run the opt-in live suite in all
three languages:

```bash
CODAG_API_KEY=cdk_... make test-live
```

Set `CODAG_SERVER` to point the live suite at staging or a self-hosted API
instead of the hosted default.
