#!/usr/bin/env bash
# Offline smoke test of the *packaged* artifacts (not the source tree).
#
# `make test` imports each SDK straight from its source directory, so it cannot
# catch packaging regressions: a broken package.json "exports" map, a file
# missing from the sdist/tarball, an unresolvable module path, or a py.typed
# that never ships. This script builds each distribution the way `publish`
# would, installs it into a throwaway consumer project, and exercises an
# import + a pre-network validation path. No API key or network is required.
#
# Each language is skipped (not failed) when its toolchain is absent.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
failures=0

step() { printf '\n=== %s ===\n' "$1"; }
ok()   { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; failures=$((failures + 1)); }
skip() { printf 'SKIP: %s\n' "$1"; }

# ---------- Python: build wheel, install, import, validate ----------
step "Python packaged wheel"
if command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then
  py="$WORK/py"
  python3 -m venv "$py"
  "$py/bin/pip" install -q build >/dev/null
  "$py/bin/python" -m build --wheel --outdir "$WORK/wheels" "$ROOT/python" >/dev/null
  "$py/bin/pip" install -q "$WORK"/wheels/codag-*.whl
  if "$py/bin/python" - <<'PY'
import sys, importlib.util
import codag
from codag import Codag, ValidationError
# py.typed must ship so downstream type checkers trust the annotations.
spec = importlib.util.find_spec("codag")
pkg_dir = spec.submodule_search_locations[0]
import os
assert os.path.exists(os.path.join(pkg_dir, "py.typed")), "py.typed missing from installed package"
try:
    Codag(api_key="cdk_x").compact([])
except ValidationError:
    sys.exit(0)
sys.exit("expected ValidationError")
PY
  then ok "wheel installs, imports, ships py.typed, validates"
  else fail "python wheel smoke test"
  fi
else
  skip "python (python3/pip not available)"
fi

# ---------- TypeScript: pack tarball, install, ESM import, validate ----------
step "TypeScript packaged tarball"
if command -v npm >/dev/null 2>&1; then
  ts="$WORK/ts"
  mkdir -p "$ts"
  (cd "$ROOT/typescript" && npm pack --pack-destination "$ts" >/dev/null 2>&1)
  tarball="$(ls "$ts"/codag-sdk-*.tgz)"
  (cd "$ts" && npm init -y >/dev/null 2>&1 && npm pkg set type=module >/dev/null 2>&1 && npm install "$tarball" >/dev/null 2>&1)
  cat > "$ts/run.mjs" <<'JS'
import { Codag, ValidationError } from "@codag/sdk";
const client = new Codag({ apiKey: "cdk_x" });
try {
  await client.compact([]);
  process.exit("expected ValidationError");
} catch (e) {
  if (!(e instanceof ValidationError)) process.exit(`wrong error: ${e}`);
}
JS
  if (cd "$ts" && node run.mjs); then ok "tarball installs, ESM import resolves, validates"
  else fail "typescript tarball smoke test"
  fi

  # d.ts must typecheck for a modern (NodeNext) consumer.
  (cd "$ts" && npm install -D typescript >/dev/null 2>&1)
  cat > "$ts/check.ts" <<'TS'
import { Codag, CompactResponse } from "@codag/sdk";
const c = new Codag({ apiKey: "cdk_x" });
export async function go(): Promise<number> {
  const r: CompactResponse = await c.compact(["ERROR one"], { service: "api" });
  return r.stats.elapsed_ms;
}
TS
  cat > "$ts/tsconfig.json" <<'JSON'
{ "compilerOptions": { "strict": true, "module": "nodenext", "moduleResolution": "nodenext", "noEmit": true } }
JSON
  if (cd "$ts" && ./node_modules/.bin/tsc >/dev/null 2>&1); then ok "shipped .d.ts typechecks (NodeNext, strict)"
  else fail "typescript .d.ts typecheck"
  fi
else
  skip "typescript (npm not available)"
fi

# ---------- Go: consume the module via a replace directive, build + run ----------
step "Go module as a downstream dependency"
if command -v go >/dev/null 2>&1; then
  gg="$WORK/go"
  mkdir -p "$gg"
  cat > "$gg/go.mod" <<EOF
module example.com/consumer

go 1.21

require github.com/codag-megalith/codag-sdk/go v0.0.0

replace github.com/codag-megalith/codag-sdk/go => $ROOT/go
EOF
  cat > "$gg/main.go" <<'GO'
package main

import (
	"context"
	"errors"
	"fmt"

	codag "github.com/codag-megalith/codag-sdk/go"
)

func main() {
	client := codag.New(codag.WithAPIKey("cdk_x"))
	_, err := client.Compact(context.Background(), []string{}, nil)
	if err == nil {
		panic("expected validation error")
	}
	// A packaging/link problem would surface before this point.
	_ = errors.Is(err, codag.ErrMissingAPIKey)
	fmt.Println("ok")
}
GO
  if (cd "$gg" && GOCACHE="$ROOT/.gocache" GOFLAGS=-mod=mod go run . >/dev/null 2>&1); then
    ok "module builds and links as a downstream dependency"
  else fail "go consumer build"
  fi
else
  skip "go (toolchain not available)"
fi

step "Summary"
if [ "$failures" -ne 0 ]; then
  printf '%d packaging check(s) failed\n' "$failures"
  exit 1
fi
echo "all packaged-artifact checks passed"
