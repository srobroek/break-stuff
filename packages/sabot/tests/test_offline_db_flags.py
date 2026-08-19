#!/usr/bin/env python3
"""Tests for the DB-consuming scanners whose bake was present but unread.

trivy and osv-scanner both shipped a correct, non-empty database that the tool did not read.
trivy ignores the bake unless `--cache-dir` names it and dies on a registry pull;
osv-scanner's `--offline` parses every lockfile, loads no database, and reports zero
vulnerabilities. Both passed a file-presence assertion, which is why the build now scans a
known-vulnerable probe lockfile instead. Semgrep is the third: pointed at the rules parent
rather than a `<lang>` subdir it aborts the whole scan on one non-rule file.

Reads the wrapper, the installer, and the references as text. No container, no network.

Run: pytest packages/sabot/tests/test_offline_db_flags.py
"""

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage"
INSTALL = (SKILL / "scripts/install-tools.sh").read_text()
ISOLATION = (SKILL / "references/isolation.md").read_text()
MATRIX = (SKILL / "references/tool-coverage-matrix.md").read_text()
SURFACES = {p.name: p.read_text() for p in (SKILL / "references/surfaces").glob("*.md")}
JOINED = INSTALL.replace("\\\n", " ")


def test_base_db_assertion_scans_a_probe_lockfile():
    """A file-presence check passed on both tools while neither read the db, so the build
    has to assert an advisory count instead."""
    assert "requirements.txt" in JOINED, "the assertion must scan something, not stat a file"
    assert "Django==2.2.0" in JOINED, "the probe pin has to be known-vulnerable"
    assert "grep -c VulnerabilityID" in JOINED, "trivy's finding count must be asserted"
    assert "grep -c PYSEC" in JOINED, "osv-scanner's finding count must be asserted"


def test_trivy_assertion_passes_the_cache_dir():
    """Without --cache-dir trivy ignores the bake and tries to pull trivy-db from a
    registry, which fails on DNS."""
    assert "--cache-dir /opt/sabot-db/trivy" in JOINED
    assert "--skip-db-update" in JOINED


def test_osv_assertion_passes_the_db_location_in_the_environment():
    """`--offline` alone loads no db; the cache dir has to come from the environment."""
    assert "XDG_CACHE_HOME=/opt/sabot-db/osv" in JOINED


def test_semgrep_assertion_requires_a_language_subdir():
    """One invalid file in the rules parent aborts the entire scan, so the subdir the
    recipes name must be asserted to exist."""
    assert "/opt/sabot-db/semgrep-rules/python" in JOINED


def test_isolation_records_all_three_traps():
    for claim in (
        "--cache-dir /opt/sabot-db/trivy",
        "no offline version of the OSV database is available",
        "Loaded ... local db",
        "missing 'rules' as top-level",
    ):
        assert claim in ISOLATION, f"isolation.md does not record: {claim}"


def test_surface_recipes_pass_the_flags_they_need():
    """A recipe an agent copies verbatim must not be the invocation that reports zero."""
    infra = SURFACES["infra.md"]
    assert "--skip-check-update" in infra, \
        "without it the misconfig scanner stalls on a failed bundle download"
    for name in ("infra.md", "build.md"):
        assert "XDG_CACHE_HOME=/opt/sabot-db/osv osv-scanner" in SURFACES[name]
        assert "MANDATORY" in SURFACES[name], \
            f"{name} must flag that the env var is not optional"


def test_matrix_records_the_measured_counts():
    for claim in (
        "CVE-2019-14234",
        "130 advisories",
        "no offline version of the OSV database is available",
        "13 of 40 bytes changed",
        "wrong type string",
        "4/4 unsafe expressions",
        "action can't be pinned",
    ):
        assert claim in MATRIX, f"matrix does not record: {claim}"


def test_matrix_has_no_unmeasured_rows():
    """Every tool row carries a verdict. A row naming only a fixture is what let trivy and
    osv-scanner ship unread databases."""
    verdicts = ("VERIFIED", "MEASURED", "declined", "DECLINED", "fragment-pending",
                "BLOCKED", "gap")
    bad = []
    for line in MATRIX.splitlines():
        if not line.startswith("| ") or line.startswith("|---") or line.startswith("| Tool"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        # A deliberate non-goal carries its verdict in the bake column instead
        # (declined, fragment-pending, BLOCKED), so both columns count.
        if not any(v in cells[2] or v in cells[3] for v in verdicts):
            bad.append(cells[0])
    assert not bad, f"tool rows with no offline verdict: {bad}"
