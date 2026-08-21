#!/usr/bin/env python3
"""report-json.py must rank, dedup, and group mechanically rather than editorially.

One run produced ~251 findings with no ranking or dedup mechanism at all, and 224 loci
were collapsed onto a single boundary BY HAND. Its most valuable conclusion -- eight
independent built-but-never-wired instances -- was produced by no step at all. These
tests assert that the collapse, the ordering, the count balance, and the NOT-EXECUTED
register fall out of the bead graph.

Stdlib plus pytest only. No network, no bd.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".apm" / "skills" / "sabotage" / "scripts" / "report-json.py"
)

FULL_FIELDS = {
    "run_id": "run-A", "tier": "PROVEN", "by": "challenger", "source": "harness",
    "impact": "HIGH", "locus": "a.rs:1", "surface": "code", "node": "e.1",
    "evidence": "/art/x.json", "control_passed": True,
    "dedup_key": "code:a.rs:1:cwe-190", "root_cause": "unchecked arithmetic",
    "not_executed_reason": None, "cwe": "CWE-190",
}


def finding(bid, **over):
    meta = dict(FULL_FIELDS)
    meta.update(over)
    return {
        "id": bid, "issue_type": "task", "title": over.pop("title", f"finding {bid}"),
        "status": "open", "metadata": meta,
        "labels": ["sab-finding", "sab-surface"],
        "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}],
    }


def export(extra, threat="memory safety at the IPC boundary", coverage=True,
           surfaces=("code",)):
    lines = [{
        "_type": "issue", "id": "e", "issue_type": "epic", "title": "run",
        "status": "open",
        "metadata": {"run_id": "run-A", "target": "repo", "threat": threat},
    }]
    for i, name in enumerate(surfaces, 1):
        lines.append({
            "id": f"e.{i}", "issue_type": "task", "title": f"surface: {name}",
            "status": "open",
            "metadata": {"run_id": "run-A", "surface": name, "scope": ["**/*"]},
            "labels": ["sab-surface"],
            "dependencies": [{"depends_on_id": "e", "type": "parent-child"}],
        })
    if coverage:
        lines.append({
            "id": "e.1.90", "issue_type": "task", "title": "coverage", "status": "open",
            "metadata": {"run_id": "run-A", "surface": "code",
                         "scanners_run": ["opengrep"], "scanners_skipped": [],
                         "harnesses_run": 2, "harnesses_total": 2},
            "labels": ["sab-coverage", "sab-surface", "non-work"],
            "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}],
        })
    return lines + list(extra)


@pytest.fixture
def bd_factory(tmp_path):
    def make(lines):
        jsonl = "\n".join(json.dumps(o) for o in lines)
        bd = tmp_path / "bd"
        bd.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"payload = {jsonl!r}\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'export':\n"
            "    print(payload)\n"
            "else:\n"
            "    sys.exit(0)\n"
        )
        bd.chmod(bd.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return str(bd)
    return make


def report(bd_factory, lines, expect_rc=0):
    bd = bd_factory(lines)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--bd", bd, "--run-id", "run-A"],
        capture_output=True, text=True,
    )
    assert r.returncode == expect_rc, r.stdout + r.stderr
    return json.loads(r.stdout), r


# --- dedup ------------------------------------------------------------------


def test_a_dedup_key_on_two_wisps_is_one_group_and_independent_confirmation(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1"),
        finding("e.1.2", by="self", source="stock-pack"),
    ]))
    assert len(doc["groups"]) == 1
    g = doc["groups"][0]
    assert g["instance_count"] == 2
    assert g["confirmed_independently"] is True
    assert sorted(g["instances"]) == ["e.1.1", "e.1.2"]


def test_a_group_reports_one_tier_the_strongest_any_instance_carries(bd_factory):
    # A group reported at its weakest instance understates what was proven.
    doc, _ = report(bd_factory, export([
        finding("e.1.1", tier="HARDENING"),
        finding("e.1.2", tier="PROVEN"),
    ]))
    g = doc["groups"][0]
    assert g["tier"] == "PROVEN"
    assert g["tiers_seen"] == ["HARDENING", "PROVEN"]


def test_a_derived_dedup_key_is_marked_as_derived(bd_factory):
    # The finder knows the class; a later pass reconstructing it from a title guesses, so
    # a group built on a fallback key must not read as the finder's judgment.
    doc, _ = report(bd_factory, export([finding("e.1.1", dedup_key=None)]))
    assert doc["groups"][0]["dedup_key_derived"] is True


def test_the_summary_counts_groups_resting_on_a_derived_key(bd_factory):
    """A per-group flag nothing totals is invisible in a 383-finding report.

    Measured: one campaign filed 383 findings and stamped `dedup_key` on none of them,
    so every group was built from a key this script reconstructed at report time and the
    challenger's prescribed `uniq -d` dedup returned nothing over seven real
    cross-surface duplicate loci. The per-group `dedup_key_derived` flag was already
    correct; nobody reading the summary could see that it was set everywhere.
    """
    doc, _ = report(bd_factory, export([
        finding("e.1.1", dedup_key=None),
        finding("e.1.2", dedup_key="code:b.rs:9:cwe-22", locus="b.rs:9"),
    ]))
    assert doc["summary"]["groups_on_a_derived_dedup_key"] == 1
    assert doc["summary"]["counts"]["groups"] == 2


def test_distinct_keys_stay_distinct_groups(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1", dedup_key="code:a.rs:1:cwe-190"),
        finding("e.1.2", dedup_key="code:b.rs:9:cwe-22", locus="b.rs:9"),
    ]))
    assert len(doc["groups"]) == 2


# --- ranking ----------------------------------------------------------------


def test_tier_outranks_impact(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1", tier="HARDENING", impact="CRITICAL",
                dedup_key="k1", locus="a.rs:1"),
        finding("e.1.2", tier="PROVEN", impact="LOW", dedup_key="k2", locus="b.rs:2"),
    ]))
    assert [g["dedup_key"] for g in doc["groups"]] == ["k2", "k1"]
    assert doc["groups"][0]["rank"] == 1


def test_the_epics_stamped_threat_orders_groups_that_tie(bd_factory):
    # The threat has been stamped since the interview and had never been used to order
    # anything, so a run aimed at one fear reported in bead order.
    doc, _ = report(bd_factory, export([
        finding("e.1.1", dedup_key="unrelated", root_cause="a slow loop",
                cwe="CWE-400", locus="z.rs:1"),
        finding("e.1.2", dedup_key="aligned", root_cause="unchecked write at the IPC boundary",
                cwe="CWE-787", locus="a.rs:1"),
    ], threat="memory safety at the IPC boundary"))
    assert [g["dedup_key"] for g in doc["groups"]] == ["aligned", "unrelated"]
    assert doc["groups"][0]["threat_aligned"] is True
    assert doc["summary"]["threat_aligned_groups"] == 1


def test_instance_count_breaks_a_tie_before_locus(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1", dedup_key="one", locus="a.rs:1", root_cause="x"),
        finding("e.1.2", dedup_key="many", locus="b.rs:1", root_cause="x"),
        finding("e.1.3", dedup_key="many", locus="b.rs:2", root_cause="x"),
    ], threat=None))
    assert [g["dedup_key"] for g in doc["groups"]] == ["many", "one"]


def test_a_refuted_group_sorts_below_an_untiered_one(bd_factory):
    # Refuted is a decision; untiered is an unfinished job, and burying it hides work.
    doc, _ = report(bd_factory, export([
        finding("e.1.1", tier="REFUTED", dedup_key="refuted", locus="a.rs:1"),
        finding("e.1.2", tier=None, dedup_key="untiered", locus="b.rs:1"),
    ], threat=None))
    assert [g["dedup_key"] for g in doc["groups"]] == ["untiered", "refuted"]


# --- systemic patterns ------------------------------------------------------


def test_root_cause_rollup_sits_above_the_findings_and_counts_instances(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1", dedup_key="a", locus="a.rs:1",
                root_cause="built but never wired"),
        finding("e.1.2", dedup_key="b", locus="b.rs:1",
                root_cause="built but never wired"),
        finding("e.1.3", dedup_key="c", locus="c.rs:1", root_cause="a different defect"),
    ]))
    top = doc["systemic_patterns"][0]
    assert top["root_cause"] == "built but never wired"
    assert top["group_count"] == 2
    assert top["instance_count"] == 2
    assert doc["summary"]["systemic_pattern_count"] == 2


def test_a_root_cause_spanning_surfaces_is_flagged_cross_surface(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1", dedup_key="a", surface="code", locus="a.rs:1",
                root_cause="built but never wired"),
        finding("e.1.2", dedup_key="b", surface="infra", locus="ci.yml:1",
                root_cause="built but never wired"),
    ], surfaces=("code", "infra")))
    assert doc["systemic_patterns"][0]["cross_surface"] is True
    assert doc["systemic_patterns"][0]["surfaces"] == ["code", "infra"]


# --- counts that balance ----------------------------------------------------


def test_the_three_counts_are_derived_and_balance(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1", dedup_key="a", locus="a.rs:1"),
        finding("e.1.2", dedup_key="a", locus="a.rs:1"),
        finding("e.1.3", dedup_key="b", locus="b.rs:1"),
    ]))
    counts = doc["summary"]["counts"]
    assert counts["groups"] == 2
    assert counts["instances"] == 3
    assert counts["grouped_instances"] == 3
    assert counts["balances"] is True
    assert counts["wisps"] >= counts["instances"]


# --- the NOT-EXECUTED register ---------------------------------------------


def test_a_not_executed_reason_is_a_register_line_not_an_absence(bd_factory):
    doc, _ = report(bd_factory, export([
        finding("e.1.1", tier=None, impact=None,
                not_executed_reason="opengrep stock packs cannot load under --network none"),
    ]))
    kinds = {r["kind"]: r for r in doc["not_executed"]}
    assert "finding-placeholder" in kinds
    assert "--network none" in kinds["finding-placeholder"]["reason"]
    assert doc["summary"]["not_executed_count"] >= 1


def test_a_failed_control_marks_the_locus_untested(bd_factory):
    # A benign control that also failed means the harness proved nothing about the code.
    doc, _ = report(bd_factory, export([finding("e.1.1", control_passed=False)]))
    assert any(r["kind"] == "control-failed" for r in doc["not_executed"])


def test_a_surface_with_no_coverage_record_is_a_gap_not_an_empty_list(bd_factory):
    # The fail-open: gaps were derived only from the coverage records that EXIST, so a
    # surface that filed none produced coverage_gaps: [] and exit 0.
    doc, _ = report(bd_factory, export(
        [finding("e.1.1")], surfaces=("code", "infra"), coverage=True,
    ))
    assert doc["summary"]["surfaces_without_a_coverage_record"] == ["infra"]
    assert any(r["kind"] == "no-coverage-record" and r["surface"] == "infra"
               for r in doc["not_executed"])


def test_unrun_harnesses_and_skipped_scanners_reach_the_register(bd_factory):
    lines = export([finding("e.1.1")], coverage=False)
    lines.append({
        "id": "e.1.90", "issue_type": "task", "title": "coverage", "status": "open",
        "metadata": {"run_id": "run-A", "surface": "code",
                     "scanners_run": ["opengrep"], "scanners_skipped": ["codeql"],
                     "harnesses_run": 0, "harnesses_total": 13},
        "labels": ["sab-coverage", "sab-surface", "non-work"],
        "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}],
    })
    doc, _ = report(bd_factory, lines)
    kinds = {r["kind"] for r in doc["not_executed"]}
    assert {"scanner-skipped", "harnesses-unrun"} <= kinds
    assert any("13 of 13" in r["reason"] or "13 authored" in r["reason"]
               for r in doc["not_executed"] if r["kind"] == "harnesses-unrun")


def test_entry_points_never_executed_reach_the_register_though_every_harness_ran(bd_factory):
    """A harness ratio measures the harnesses, not the surface.

    Measured: one node reported 13 of 13 harnesses run against 706 entry points, and
    another enumerated 199 Tauri command handlers and executed 0 of them because the
    image could not compile the crate. Both read as complete coverage from
    `harnesses_run == harnesses_total` alone, and with only the harness counts kept in
    KEEP_META the 199 reached no part of the report.
    """
    lines = export([finding("e.1.1")], coverage=False)
    lines.append({
        "id": "e.1.90", "issue_type": "task", "title": "coverage", "status": "open",
        "metadata": {"run_id": "run-A", "surface": "code",
                     "scanners_run": ["opengrep"], "scanners_skipped": [],
                     # every authored harness ran, so the harness ratio is silent
                     "harnesses_run": 13, "harnesses_total": 13,
                     "entry_points_total": 199, "entry_points_executed": 0},
        "labels": ["sab-coverage", "sab-surface", "non-work"],
        "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}],
    })
    doc, _ = report(bd_factory, lines)
    assert not any(r["kind"] == "harnesses-unrun" for r in doc["not_executed"])
    gaps = [r for r in doc["not_executed"] if r["kind"] == "entry-points-unexecuted"]
    assert gaps, doc["not_executed"]
    assert "199 of 199" in gaps[0]["reason"]
    # and the raw ratio survives shape() into the coverage record itself
    cov = next(c for c in doc["coverage"] if c["id"] == "e.1.90")
    assert cov["entry_points_total"] == 199
    assert cov["entry_points_executed"] == 0


# --- stamping discipline ----------------------------------------------------


def test_a_missing_required_field_is_a_stamping_gap_not_a_blank_column(bd_factory):
    lines = export([finding("e.1.1")])
    del lines[-1]["metadata"]["evidence"]        # omitted, not null
    del lines[-1]["metadata"]["control_passed"]
    doc, _ = report(bd_factory, lines)
    issues = " ".join(g["issue"] for g in doc["stamping_gaps"])
    assert "evidence" in issues and "control_passed" in issues


def test_an_explicit_null_is_accepted_where_a_field_does_not_apply(bd_factory):
    doc, _ = report(bd_factory, export([finding("e.1.1", repro=None, path=None)]))
    assert not any("required field" in g["issue"] for g in doc["stamping_gaps"])


# --- bd query discipline ----------------------------------------------------


def test_an_empty_export_is_refused_rather_than_rendered_as_a_clean_audit(tmp_path):
    # `bd` discovers its store relative to cwd, and `--labels` silently returns nothing
    # on a query, which once made a whole wisp set read as "no work exists".
    bd = tmp_path / "bd"
    bd.write_text("#!/bin/sh\nexit 0\n")
    bd.chmod(bd.stat().st_mode | stat.S_IEXEC)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--bd", str(bd), "--run-id", "run-A"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3
    assert "returned NOTHING" in r.stderr


def test_a_failing_bd_names_the_repo_root_requirement(tmp_path):
    bd = tmp_path / "bd"
    bd.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
    bd.chmod(bd.stat().st_mode | stat.S_IEXEC)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--bd", str(bd), "--run-id", "run-A"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3
    assert "repo root" in r.stderr
