# Contributing

Keep changes focused and keep the three SDKs behaviorally aligned.

Before opening a pull request, run:

```bash
make test        # hermetic: unit tests, contract check, test-count floor
make test-dist   # builds and installs each package, then imports the artifact
```

`make test` imports each SDK from its source tree. `make test-dist` builds the
wheel / npm tarball / Go module the way a release would and exercises the
installed artifact, so it catches packaging regressions the unit tests cannot
(missing files, a broken `exports` map, an unresolvable module path).

To exercise the hosted API end to end:

```bash
CODAG_API_KEY=cdk_... make test-live
```

When changing request or response behavior, update:

- `openapi/codag-v1.openapi.json`
- shared fixtures under `fixtures/`
- tests in Python, TypeScript, and Go

Do not commit credentials, customer logs, generated coverage reports, package
manager caches, or built release archives.

## Releasing

The three SDKs share one version. To cut a release:

1. Bump the version in `python/pyproject.toml`, `typescript/package.json`, and
   the `USER_AGENT` constants in all three clients.
2. `make test && make test-dist`.
3. Tag the commit as both `vX.Y.Z` and `go/vX.Y.Z`, then push both tags.
4. The `Release SDKs` workflow verifies the tagged source and publishes Python
   and npm through registry trusted publishing (GitHub OIDC; no stored API
   tokens). Go resolves from the pushed `go/vX.Y.Z` tag through the module
   proxy because its module lives in the `go` subdirectory.

The workflow can also republish an existing tag through `workflow_dispatch` by
entering the version without the `v` prefix. PyPI and npm must each trust
`.github/workflows/release.yml` in the `release` GitHub environment.
