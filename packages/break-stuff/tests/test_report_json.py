#!/usr/bin/env python3
"""Tests for the shipped report-json.py campaign exporter.

The report is generated from this script's output, so a bug here silently drops or
misfiles findings. The tests feed a synthetic `bd export` (a stub `bd` on PATH) so
they need no live beads database, and assert the run is bucketed, filtered, and
correlated correctly.

Run: pytest packages/break-stuff/tests/test_report_json.py
Stdlib plus pytest only. No network, no bd.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".apm" / "skills" / "break-stuff" / "scripts" / "report-json.py"
)

# A synthetic two-run export: run-A is the campaign under test, run-B must be
# filtered out entirely, and one infra bead with no run_id must be ignored.
EXPORT_LINES = [
    {"_type": "issue", "id": "e", "issue_type": "epic", "title": "run",
     "status": "open", "metadata": {"run_id": "run-A", "target": "repo", "base_sha": "abc",
                                     "budget": {"wall_s": 60}, "artifacts": "/tmp/a"}},
    {"id": "e.1", "issue_type": "task", "title": "surface: shell", "status": "open",
     "metadata": {"run_id": "run-A", "surface": "shell", "scope": ["**/*.sh"]},
     "labels": ["brk-surface"],
     "dependencies": [{"depends_on_id": "e", "type": "parent-child"}]},
    {"id": "e.1.1", "issue_type": "task", "title": "harness", "status": "open",
     "metadata": {"run_id": "run-A", "entry_point": "guard.py:1", "runner": "fuzz-cli",
                  "harness_path": "t/v.json", "input_shape": "json"},
     "labels": ["brk-harness", "brk-surface", "non-work"],
     "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}]},
    {"id": "e.1.2", "issue_type": "task", "title": "finding", "status": "open",
     "metadata": {"run_id": "run-A", "tier": "PROVEN", "by": "challenger",
                  "source": "harness", "impact": "CRITICAL", "locus": "guard.py:88"},
     "labels": ["brk-finding", "brk-surface"],
     "dependencies": [
         {"depends_on_id": "e.1", "type": "parent-child"},
         {"depends_on_id": "e.1.1", "type": "discovered-from"},
     ],
     "comments": [{"text": "TIERED evidence=guard.py:88"}]},
    {"id": "e.1.3", "issue_type": "task", "title": "coverage", "status": "open",
     "metadata": {"run_id": "run-A", "scanners_run": "shellcheck",
                  "harnesses_run": 1, "harnesses_total": 2},
     "labels": ["brk-coverage", "brk-surface", "non-work"],
     "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}]},
    # A finding the agent filed WITHOUT run_id (the live-test bug). It must still be
    # collected via the parent-child walk, and flagged as a stamping gap.
    {"id": "e.1.4", "issue_type": "task", "title": "unstamped finding", "status": "open",
     "metadata": {"tier": "REACHABLE", "impact": "MEDIUM", "locus": "x.py:1"},
     "labels": ["brk-finding", "brk-surface"],
     "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}]},
    # A harness whose own brk-harness label the agent dropped (only inherited
    # brk-surface remains). Metadata shape still identifies it; it must bucket as a
    # harness and be flagged, not counted as a second surface.
    {"id": "e.1.5", "issue_type": "task", "title": "mislabeled harness", "status": "open",
     "metadata": {"run_id": "run-A", "entry_point": "y.py:2", "harness_path": "t/h.py"},
     "labels": ["brk-surface"],
     "dependencies": [{"depends_on_id": "e.1", "type": "parent-child"}]},
    # run-B: must not appear in a run-A report.
    {"id": "z", "issue_type": "epic", "title": "other", "status": "open",
     "metadata": {"run_id": "run-B"}},
    {"id": "z.1", "issue_type": "task", "title": "other finding", "status": "open",
     "metadata": {"run_id": "run-B", "tier": "HIGH"}, "labels": ["brk-finding"]},
    # infra bead with no run_id: ignored.
    {"id": "infra", "issue_type": "task", "title": "noise", "status": "open",
     "metadata": {}, "labels": ["role"]},
]


@pytest.fixture
def stub_bd(tmp_path):
    """A fake `bd` on PATH whose `export` prints the synthetic JSONL."""
    jsonl = "\n".join(json.dumps(o) for o in EXPORT_LINES)
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


def run_script(bd, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--bd", bd, *args],
        capture_output=True, text=True,
    )


def test_buckets_and_filters_to_run(stub_bd):
    r = run_script(stub_bd, "--run-id", "run-A")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["run_id"] == "run-A"
    assert out["epic"]["target"] == "repo"
    assert len(out["surfaces"]) == 1  # only the real surface node; the mislabeled harness is not counted here
    assert len(out["harnesses"]) == 2  # the labeled one + the mislabeled-but-metadata-classified one
    assert len(out["findings"]) == 2  # the stamped one + the unstamped one, both under the epic
    assert len(out["coverage"]) == 1
    # run-B and the infra bead are gone.
    ids = [f["id"] for f in out["findings"]]
    assert "z.1" not in ids


def test_selects_by_epic_directly(stub_bd):
    """The preferred API: pass the epic id, collect its descendants by parentage."""
    out = json.loads(run_script(stub_bd, "--epic", "e").stdout)
    assert out["epic_id"] == "e"
    assert out["run_id"] == "run-A"
    assert {f["id"] for f in out["findings"]} == {"e.1.2", "e.1.4"}


def test_unstamped_finding_is_collected_and_flagged(stub_bd):
    """The live-test bug: a finding with no run_id must NOT be silently dropped.
    It is collected via the parent-child walk and reported as a stamping gap."""
    out = json.loads(run_script(stub_bd, "--epic", "e").stdout)
    ids = {f["id"] for f in out["findings"]}
    assert "e.1.4" in ids  # collected despite missing run_id
    gap_ids = {g["id"] for g in out["stamping_gaps"]}
    assert "e.1.4" in gap_ids  # and flagged
    assert out["summary"]["stamping_gaps"] >= 1


def test_mislabeled_harness_bucketed_by_metadata_and_flagged(stub_bd):
    """Bug 3: a harness that lost its brk-harness label (only inherited brk-surface)
    must still bucket as a harness via its metadata shape, not inflate surfaces."""
    out = json.loads(run_script(stub_bd, "--epic", "e").stdout)
    hids = {h["id"] for h in out["harnesses"]}
    assert "e.1.5" in hids  # bucketed as a harness despite the missing label
    assert "e.1.5" not in {s["id"] for s in out["surfaces"]}  # not counted as a surface
    gap_ids = {g["id"] for g in out["stamping_gaps"]}
    assert "e.1.5" in gap_ids  # and flagged as a mislabel


def test_finding_keeps_metadata_and_edges(stub_bd):
    out = json.loads(run_script(stub_bd, "--run-id", "run-A").stdout)
    f = next(f for f in out["findings"] if f["id"] == "e.1.2")
    assert f["tier"] == "PROVEN"
    assert f["by"] == "challenger"
    assert f["impact"] == "CRITICAL"
    # the discovered-from correlation edge survives; parent-child does not double up.
    assert {"type": "discovered-from", "to": "e.1.1"} in f["edges"]
    assert all(e["type"] != "parent-child" for e in f["edges"])
    assert f["parent"] == "e.1"
    assert "TIERED evidence=guard.py:88" in f["notes"]


def test_summary_counts_and_gaps(stub_bd):
    out = json.loads(run_script(stub_bd, "--run-id", "run-A").stdout)
    assert out["summary"]["by_tier"]["PROVEN"] == 1
    assert out["summary"]["by_impact"]["CRITICAL"] == 1
    # coverage with harnesses_run != harnesses_total is a gap.
    assert "e.1.3" in out["summary"]["coverage_gaps"]


def test_harness_keeps_input_shape(stub_bd):
    out = json.loads(run_script(stub_bd, "--run-id", "run-A").stdout)
    assert out["harnesses"][0]["input_shape"] == "json"


def test_unknown_run_id_exits_4(stub_bd):
    r = run_script(stub_bd, "--run-id", "run-NONE")
    assert r.returncode == 4


def test_unknown_epic_exits_4(stub_bd):
    r = run_script(stub_bd, "--epic", "nonexistent")
    assert r.returncode == 4


def test_drops_noise_fields(stub_bd):
    out = json.loads(run_script(stub_bd, "--run-id", "run-A").stdout)
    f = out["findings"][0]
    for noise in ("owner", "created_by", "priority", "updated_at", "dependency_count", "_type"):
        assert noise not in f
