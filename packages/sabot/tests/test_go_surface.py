#!/usr/bin/env python3
"""Tests for the go surface: layers/go.sh, Dockerfile.go, and its preflight manifest.

The go surface differs from the others in three ways that each caused a real failure,
so each is pinned here:

  - Its FUZZER is the toolchain. `go test -fuzz` is built in, so there is no separate
    fuzz binary to assert and nothing to bake for it. The assertion that the surface
    can fuzz at all is the `go` executable answering.
  - `go --version` exits 2. The preflight probe therefore needs a bare `<tool> version`
    fallback, or a working image reports its toolchain missing.
  - Go refuses to read a `go.mod` in the system temp root, so `TMPDIR` must be a
    subdirectory of the scratch tmpfs. With TMPDIR at the root, every contained go
    command failed "does not contain main module" while `go vet` still exited 0.

Reads the scripts as text. No container, no network, no go toolchain needed.

Run: pytest packages/sabot/tests/test_go_surface.py
"""

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage"
LAYER = SKILL / "references/containers/layers/go.sh"
DOCKERFILE = SKILL / "references/containers/Dockerfile.go"
RUN_CONTAINED = SKILL / "scripts/run-contained.sh"
INSTALL_TOOLS = SKILL / "scripts/install-tools.sh"


def test_layer_pins_every_version():
    """An unpinned tool makes the image unreproducible and renovate blind to it."""
    body = LAYER.read_text()
    for var in ("GO_VERSION", "GOSEC_VERSION", "GOLANGCI_VERSION"):
        m = re.search(rf"^{var}=([0-9][^\s]*)$", body, re.M)
        assert m, f"{var} must be pinned to a literal version in {LAYER.name}"


def test_pins_carry_renovate_comments():
    """Without the comment, containers/renovate.json cannot see the pin."""
    body = LAYER.read_text()
    for var in ("GO_VERSION", "GOSEC_VERSION", "GOLANGCI_VERSION"):
        m = re.search(rf"# renovate:[^\n]*\n{var}=", body)
        assert m, f"{var} needs a '# renovate:' line above it"


def test_layer_proves_gosec_loads_rules_not_just_its_version():
    """`gosec --version` answers with zero rules loaded: the degraded-silent case."""
    body = LAYER.read_text()
    assert "G404" in body, "the build must scan a seeded module and assert a real finding"
    assert "grep -q G404" in body


def test_go_probe_module_is_not_under_tmp():
    """Go ignores a go.mod in the system temp root, so mktemp -d cannot hold it."""
    # Match the assignment, not the word: the comment above it explains why mktemp is
    # wrong here, so a bare substring check flags its own rationale.
    body = LAYER.read_text()
    m = re.search(r"^probe=(\S+)$", body, re.M)
    assert m, "the gosec probe module needs an explicit path"
    assert not m.group(1).startswith("/tmp"), \
        "a probe module under /tmp fails 'does not contain main module'"
    assert "$(mktemp" not in body


def test_dockerfile_sets_goproxy_off():
    """Offline contract: a missing module must fail loudly, not block on a proxy dial."""
    assert "GOPROXY=off" in DOCKERFILE.read_text()


def test_dockerfile_leaves_gocache_to_the_wrapper():
    """run-contained.sh points GOCACHE at the writable tmpfs; /deps is read-only."""
    assert "GOCACHE=" not in DOCKERFILE.read_text(), \
        "a baked GOCACHE is never read (the wrapper overrides it) and breaks bare runs"


def test_tmpdir_is_below_the_scratch_root():
    """TMPDIR=/scratch made every contained go command fail while go vet exited 0."""
    body = RUN_CONTAINED.read_text()
    m = re.search(r"--env TMPDIR=(\S+)", body)
    assert m, "run-contained.sh must set TMPDIR"
    assert m.group(1) != "/scratch", \
        "TMPDIR must be a subdirectory of the scratch tmpfs, not its root"
    assert m.group(1).startswith("/scratch/")


def test_assert_probe_accepts_a_bare_version_subcommand():
    """`go --version` exits 2, so a --version-only probe reports a good image broken."""
    body = RUN_CONTAINED.read_text()
    assert "version >/dev/null" in body
    assert re.search(r"\$t version", body), \
        "the probe needs a bare `<tool> version` fallback for go"


def test_preflight_asserts_the_go_surface():
    body = INSTALL_TOOLS.read_text()
    m = re.search(r'^IMAGE_TOOLS_go="([^"]*)"', body, re.M)
    assert m, "install-tools.sh must carry an IMAGE_TOOLS_go manifest"
    tools = m.group(1).split(",")
    # `go` IS the fuzzer assertion for this surface: `go test -fuzz` is built in.
    assert "go" in tools
    assert "gosec" in tools
    assert "golangci-lint" in tools
    assert re.search(r'^SURFACES=".*\bgo\b.*"', body, re.M), \
        "go must be in SURFACES or --probe never checks it"


def test_go_surface_asserts_its_offline_contract():
    """No DB to bake here, so the assertion is that GOPROXY is actually off."""
    body = INSTALL_TOOLS.read_text()
    m = re.search(r"^IMAGE_DB_go='([^']*)'", body, re.M)
    assert m, "install-tools.sh must carry an IMAGE_DB_go assertion"
    assert "GOPROXY" in m.group(1)
