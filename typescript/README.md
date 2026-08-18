# Codag TypeScript SDK

TypeScript client for Codag's coding-agent cost API.

```bash
npm install @codag/sdk
export CODAG_API_KEY="<paste your cdk_ key>"
```

```ts
import { Codag } from "@codag/sdk";

const client = new Codag();
const result = await client.reduceAction({
  id: "action-1",
  kind: "search",
  tool: { name: "grep", arguments: { pattern: "TODO" } },
  result: largeSearchOutput,
  retrieval_handle: "local-action-1",
});
console.log(result.content);
console.log((await client.usageSummary()).estimated_saved_microusd);
```

SDK authentication is API-key only. Local harness attachment and encrypted
retrieval are handled by `codag setup` in the CLI.
