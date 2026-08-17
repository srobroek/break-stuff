#!/usr/bin/env python3
"""Tests for the scanners surface, guarding the ways each tool reports a clean it did not earn.

Every tool in this layer has a data or exit-code trap: nuclei runs with zero templates,
bearer runs with zero rules, guarddog exits 0 on a high-risk verdict. The layer's probes
and the matrix rows have to keep saying so.

Reads the layer and the matrix as text. No container, no network.

Run: pytest packages/sabot/tests/test_scanners.py
"""

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage"
CONTAINERS = SKILL / "references/containers"
LAYER = CONTAINERS / "layers/scanners.sh"
DOCKERFILE = CONTAINERS / "Dockerfile.scanners"
MATRIX = SKILL / "references/tool-coverage-matrix.md"
BODY = LAYER.read_text()


def test_every_version_is_pinned_and_tracked():
    for var in (
        "CHECKOV_VERSION",
        "GUARDDOG_VERSION",
        "KINGFISHER_VERSION",
        "NUCLEI_VERSION",
        "BEARER_VERSION",
    ):
        assert re.search(rf"^{var}=\S", BODY, re.M), f"{var} must be pinned"
    renovate = len(re.findall(r"^# renovate:", BODY, re.M))
    assert renovate >= 5, "each release pin needs a '# renovate:' line"


def test_the_data_trees_are_pinned_by_sha():
    """A moving tree means an unreproducible bake, and a silent coverage change."""
    for var in ("NUCLEI_TEMPLATES_SHA", "BEARER_RULES_SHA"):
        assert re.search(rf"^{var}=[0-9a-f]{{40}}$", BODY, re.M), \
            f"{var} must be a full 40-char commit SHA"


def test_the_arch_map_covers_both_arches():
    """kingfisher spells x64 where nuclei and bearer say amd64."""
    assert re.search(r"^arm64\)", BODY, re.M)
    assert re.search(r"^amd64\)", BODY, re.M)
    assert "kf=x64" in BODY, "kingfisher's amd64 asset is named x64"


def test_nuclei_gets_both_templates_and_ud():
    """Measured: -templates alone left ~5000 templates uncompilable.

    nuclei resolves a template's helpers/ payload files against its DEFAULT template
    directory, so the baked tree has to be BOTH the source and the default.
    """
    # Join continuations first: the invocation spans two lines, so a per-line search
    # reports a missing flag that is present on the next one.
    joined = BODY.replace("\\\n", " ")
    probe = next(l for l in joined.splitlines() if l.startswith("nuclei -templates"))
    assert "-ud /opt/sabot-db/nuclei-templates" in probe, \
        "without -ud the helper payload files resolve outside the baked tree"
    assert "-duc" in probe, "the updater reaches the network and writes to its config dir"


def test_the_nuclei_gate_requires_zero_errors():
    """Grepping for a success string in output that also carries errors passes silently."""
    assert 'grep -q "All templates validated successfully"' in BODY, \
        "match the exact all-clear line, not a substring that coexists with errors"


def test_the_quarantine_is_a_list_with_a_reason():
    assert "QUARANTINE" in BODY
    assert "CVE-2026-3395" in BODY, "name the template that fails to unmarshal"
    assert re.search(r"^for bad in ", BODY, re.M), \
        "keep it a list so entries can be dropped as upstream repairs them"


def test_both_data_trees_have_a_count_floor():
    """`test -d` passes on an empty tree, which loads zero rules and reports a clean."""
    assert re.search(r'\[ "\$tmpl_count" -gt 1000 \]', BODY)
    assert re.search(r'\[ "\$rule_count" -gt 100 \]', BODY)


def test_bearer_probe_points_at_the_baked_rules():
    assert "--external-rule-dir /opt/sabot-db/bearer-rules" in BODY, \
        "without it bearer downloads rules, which offline means zero"


def test_kingfisher_probe_disables_validation():
    """The default path opens outbound connections per candidate."""
    assert "--no-validate" in BODY


def test_checkov_probe_asserts_a_finding_not_a_version():
    assert "checkov --version" in BODY, "the version check is fine as a smoke test"
    assert 'grep -q "CKV_AWS"' in BODY, \
        "and it is not sufficient: require a policy to match on a seeded resource"


def test_chmod_is_the_last_write():
    """The campaign runs as uid 1000; anything written after the chmod is root-only."""
    lines = [l for l in BODY.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert lines[-1].startswith("chmod -R a+rX"), \
        f"chmod must be the last command, found: {lines[-1]!r}"


def test_it_is_its_own_image_not_stacked_on_base():
    """base is inherited by all four language surfaces; none needs a Terraform policy set."""
    body = DOCKERFILE.read_text()
    assert "ARG BASE=sabot/base:1" in body
    assert "USER breaker" in body, "the campaign must not run as root"
    base_dockerfile = (CONTAINERS / "Dockerfile.base").read_text()
    assert "scanners.sh" not in base_dockerfile, \
        "stacking this on base pays for it once per surface"


def test_the_exit_code_traps_are_recorded():
    matrix = MATRIX.read_text()
    assert "EXITS 0 ON A HIGH-RISK VERDICT" in matrix, \
        "guarddog's exit code is 0 at 8.0/10; a wrapper gating on it records a clean"
    assert "fails-loud without baked rules" in matrix, \
        "bearer's zero-rule case is loud, which is the safe half; say so"


def test_measured_fixture_results_are_recorded():
    matrix = MATRIX.read_text()
    for tool in ("Checkov", "GuardDog", "Bearer"):
        row = next(l for l in matrix.splitlines() if l.startswith(f"| {tool} "))
        assert "VERIFIED" in row, f"{tool} ran against a fixture; record the measurement"
    kf = next(l for l in matrix.splitlines() if l.startswith("| Kingfisher "))
    assert "MEASURED" in kf and "FEWER than gitleaks" in kf, \
        "kingfisher found less than gitleaks on the same fixture; that is the finding"
