# @codag/sdk

TypeScript SDK for the Codag hosted API.

```ts
import { Codag } from "@codag/sdk";

const client = new Codag({ apiKey: process.env.CODAG_API_KEY });
const result = await client.compact([
  "ERROR api db pool timeout active=20 waiting=30",
]);

console.log(result.text);
```

This package is dependency-free **ESM** and uses the platform `fetch`.

- Import it with `import` (Node 18+, Deno, Bun, modern bundlers, browsers).
- CommonJS consumers must use dynamic `import("@codag/sdk")`; a top-level
  `require()` only works on Node 22.12+ / 20.19+ (where `require(esm)` is
  enabled). TypeScript projects should compile with `"module": "nodenext"`
  (or `"esnext"`) — `"module": "commonjs"` cannot `import` an ESM-only package.

A pinned type-checked usage example lives in `test_live/live.test.mjs`.
