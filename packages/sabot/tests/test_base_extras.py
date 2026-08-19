#!/usr/bin/env python3
"""Tests for the base-extras layer: mutators, the reducer, and the config scanners.

Each invariant here corresponds to a way one of these tools returns a clean it did not
earn, measured while baking the layer:

  - A MUTATOR that emits its input unchanged turns a fuzzing campaign into a
    single-input test. `radamsa --version` answers either way, so the build asserts the
    output DIFFERS from the input.
  - TruffleHog tries to overwrite its own binary at startup. On the read-only container
    that aborts the whole scan and reports zero findings, so `--no-update` is mandatory.
  - C-Reduce's interestingness test must use a relative path, or it re-reads the
    unreduced original and stops early while looking like it worked.

Reads the layer as text. No container, no network.

Run: pytest packages/sabot/tests/test_base_extras.py
"""

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage"
LAYER = SKILL / "references/containers/layers/base-extras.sh"
DOCKERFILE = SKILL / "references/containers/Dockerfile.base"
INSTALL_TOOLS = SKILL / "scripts/install-tools.sh"
ISOLATION = SKILL / "references/isolation.md"
BODY = LAYER.read_text()

PINNED = [
    "HADOLINT_VERSION",
    "KUBELINTER_VERSION",
    "TFLINT_VERSION",
    "POUTINE_VERSION",
    "TRUFFLEHOG_VERSION",
]


def test_every_downloaded_tool_is_pinned():
    """An unpinned release makes the image unreproducible."""
    for var in PINNED:
        assert re.search(rf"^{var}=[0-9][^\s]*$", BODY, re.M), f"{var} must be pinned"


def test_pins_carry_renovate_comments():
    for var in PINNED:
        assert re.search(rf"# renovate:[^\n]*\n{var}=", BODY), \
            f"{var} needs a '# renovate:' line so renovate.json can see it"


def test_radamsa_is_pinned_by_sha():
    """radamsa publishes no release tags, so a SHA is the only reproducible pin."""
    assert re.search(r"^RADAMSA_SHA=[0-9a-f]{40}$", BODY, re.M)


def test_build_proves_the_mutators_actually_mutate():
    """A mutator that echoes its input answers --version and finds nothing."""
    assert "radamsa --seed" in BODY, "assert radamsa output against a known seed input"
    assert BODY.count('!= "$seed"') >= 2, "both radamsa and zzuf need the differs-check"
    assert "the mutator is broken" in BODY, "the failure must name what is wrong"


def test_radamsa_build_installs_the_c_headers():
    """Without libc6-dev its Owl Lisp compiler fails, and the error names ol.c."""
    assert "libc6-dev" in BODY


def test_trufflehog_is_invoked_with_no_update():
    """The self-updater aborts the scan on a read-only fs and reports zero findings."""
    assert "trufflehog --no-update" in BODY
    assert "--no-update" in ISOLATION.read_text(), \
        "the invocation requirement belongs in isolation.md as a MUST"


def test_poutine_uses_its_version_subcommand():
    """`poutine --version` exits non-zero on an unknown flag and failed the build."""
    assert "poutine version" in BODY
    assert "poutine --version" not in BODY


def test_grype_is_declined_with_a_measured_reason():
    """A declined bake must record the measurement, not just the omission."""
    assert "Grype" in BODY
    assert "2.0GB" in BODY, "record the measured DB size that drove the decision"


def test_dockerfile_invokes_the_layer():
    assert "base-extras.sh" in DOCKERFILE.read_text()


def test_preflight_asserts_the_new_tools():
    body = INSTALL_TOOLS.read_text()
    m = re.search(r'^IMAGE_TOOLS_base="([^"]*)"', body, re.M)
    assert m
    tools = m.group(1).split(",")
    for t in ("radamsa", "zzuf", "creduce", "hadolint", "kube-linter",
              "tflint", "poutine", "trufflehog"):
        assert t in tools, f"{t} is in the image but not asserted by the preflight"


def test_creduce_relative_path_requirement_is_recorded():
    """Measured: an absolute path reduced 182 bytes to 163 instead of 16."""
    text = ISOLATION.read_text()
    assert "RELATIVE" in text
    assert "C-Reduce" in text
