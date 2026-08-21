# Local entry point for the sabot test suite. Mirrors .github/workflows/tests.yml:
# the same two steps, and no flags here -- testpaths and addopts live in
# pyproject.toml so the local and CI invocations cannot drift apart.

.PHONY: test deps

deps:
	python3 -m pip install --quiet --group test

test: deps
	python3 -m pytest
