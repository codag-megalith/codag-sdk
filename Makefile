.PHONY: test contract test-python test-typescript test-go test-counts test-dist test-live

test: contract test-python test-typescript test-go test-counts

contract:
	python3 scripts/check_openapi.py

test-python:
	PYTHONPATH=python/src python3 -m unittest discover -s python/tests

test-typescript:
	node --test typescript/test/*.mjs

test-go:
	cd go && GOCACHE=$$(pwd)/../.gocache go test ./...

test-counts:
	python3 scripts/check_test_counts.py

test-dist:
	bash scripts/check_dist.sh

test-live:
	@test -n "$$CODAG_API_KEY" || { echo "CODAG_API_KEY must be set for live tests"; exit 1; }
	PYTHONPATH=python/src python3 -m unittest discover -s python/tests_live -v
	node --test typescript/test_live/*.mjs
	cd go && GOCACHE=$$(pwd)/../.gocache go test -tags live -run TestLive -v ./...
