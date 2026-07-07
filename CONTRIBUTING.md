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
3. Tag the commit `vX.Y.Z` and push the tag.
4. Publish the artifacts:
   - **PyPI:** `cd python && python -m build && twine upload dist/*`
   - **npm:** `cd typescript && npm publish --access public`
   - **Go:** no publish step — `go get` resolves the pushed tag through the
     module proxy. The import path is `github.com/codag-megalith/codag-sdk/go`,
     so the tag the proxy needs is `go/vX.Y.Z` (module-subdirectory tagging).
