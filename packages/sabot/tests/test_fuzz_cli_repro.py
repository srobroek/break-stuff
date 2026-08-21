#!/usr/bin/env python3
"""fuzz-cli.py must produce repros that reproduce, and refuse unusable vectors.

Two measured fail-opens live here. In argv mode the harness moved the payload into
argv and then blanked it, so every `.input` it wrote afterwards was ZERO BYTES -- a
crash whose saved repro is empty cannot be minimized, which is the triager's whole
job, and it was caught only because one reader distrusted the artifacts and
re-persisted 21 payloads by hand. Separately, `expect` defaulted to `no-crash` and
`why` to `""`, so a misspelled key silently downgraded a bypass vector to the weakest
assertion in the set: it ran, it passed, and it proved nothing.

Stdlib plus pytest only. No network.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

HARNESS = (
    Path(__file__).resolve().parents[1]
    / ".apm" / "skills" / "sabotage" / "scripts" / "fuzz-cli.py"
)


def run_harness(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HARNESS), *args],
        capture_output=True, text=True, timeout=180,
    )


def write_exec(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return path


ALWAYS_CRASHES = "#!/bin/sh\nexit 139\n"


def vectors_file(tmp_path: Path, vectors) -> Path:
    p = tmp_path / "vectors.json"
    p.write_text(json.dumps(vectors))
    return p


# --- repro integrity --------------------------------------------------------


def test_argv_mode_repros_are_not_zero_byte(tmp_path):
    target = write_exec(tmp_path / "crash.sh", ALWAYS_CRASHES)
    vecs = vectors_file(tmp_path, [
        {"name": "wrapper", "payload": "env rm -rf /", "expect": "deny",
         "why": "a wrapper prefix must not move the command out of guard position"},
        {"name": "traversal", "payload": "../../etc/passwd", "expect": "deny",
         "why": "traversal must not escape the root"},
    ])
    art = tmp_path / "artifacts"
    r = run_harness("--target", str(target), "--mode", "argv", "--vectors", str(vecs),
                    "--skip-structural", "--artifacts-dir", str(art), "--json-report")
    report = json.loads(r.stdout)
    saved = [f["input"] for f in report["findings"] if f["input"]]
    assert saved, "argv mode persisted no repro at all"
    for path in saved:
        data = Path(path).read_bytes()
        assert data, f"zero-byte repro: {path}"


def test_a_persisted_repro_round_trips_to_the_payload_that_produced_it(tmp_path):
    target = write_exec(tmp_path / "crash.sh", ALWAYS_CRASHES)
    payload = "env rm -rf /"
    vecs = vectors_file(tmp_path, [
        {"name": "wrapper", "payload": payload, "expect": "deny", "why": "bypass probe"},
    ])
    art = tmp_path / "artifacts"
    r = run_harness("--target", str(target), "--mode", "argv", "--vectors", str(vecs),
                    "--skip-structural", "--artifacts-dir", str(art), "--json-report")
    saved = [f["input"] for f in json.loads(r.stdout)["findings"] if f["input"]]
    assert any(Path(p).read_bytes() == payload.encode() for p in saved), (
        "no repro round-tripped to the payload that produced the finding"
    )


def test_the_delivery_channel_is_recorded_beside_the_repro(tmp_path):
    # An argv payload replayed on stdin does not reproduce anything, so the channel is
    # part of the repro.
    target = write_exec(tmp_path / "crash.sh", ALWAYS_CRASHES)
    vecs = vectors_file(tmp_path, [
        {"name": "wrapper", "payload": "env rm -rf /", "expect": "deny", "why": "probe"},
    ])
    art = tmp_path / "artifacts"
    run_harness("--target", str(target), "--mode", "argv", "--vectors", str(vecs),
                "--skip-structural", "--artifacts-dir", str(art), "--json-report")
    delivery = list(art.glob("*.delivery"))
    assert delivery, "no delivery record beside the repro"
    assert delivery[0].read_text().strip() == "argv"


def test_a_genuinely_empty_payload_reports_no_repro_rather_than_an_empty_file(tmp_path):
    target = write_exec(tmp_path / "crash.sh", ALWAYS_CRASHES)
    vecs = vectors_file(tmp_path, [
        {"name": "empty", "payload": "", "expect": "deny",
         "why": "an empty command must not be allowed"},
    ])
    art = tmp_path / "artifacts"
    r = run_harness("--target", str(target), "--mode", "argv", "--vectors", str(vecs),
                    "--skip-structural", "--artifacts-dir", str(art), "--json-report")
    findings = json.loads(r.stdout)["findings"]
    assert findings, "the empty vector produced no finding"
    for f in findings:
        assert f["input"] == "", "an empty payload must not be presented as a repro path"
    assert not list(art.glob("*.input")), "a zero-byte .input was written anyway"


# --- vectors validation -----------------------------------------------------


def test_a_vector_without_expect_is_refused_not_downgraded(tmp_path):
    target = write_exec(tmp_path / "ok.sh", "#!/bin/sh\nexit 0\n")
    vecs = vectors_file(tmp_path, [{"name": "wrapper", "payload": "x", "why": "probe"}])
    r = run_harness("--target", str(target), "--vectors", str(vecs), "--skip-structural")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "expect" in r.stderr


def test_a_misspelled_expect_is_refused(tmp_path):
    target = write_exec(tmp_path / "ok.sh", "#!/bin/sh\nexit 0\n")
    vecs = vectors_file(tmp_path, [
        {"name": "w", "payload": "x", "expect": "denyy", "why": "probe"},
    ])
    r = run_harness("--target", str(target), "--vectors", str(vecs), "--skip-structural")
    assert r.returncode == 2
    assert "denyy" in r.stderr


def test_a_vector_without_why_is_refused(tmp_path):
    target = write_exec(tmp_path / "ok.sh", "#!/bin/sh\nexit 0\n")
    vecs = vectors_file(tmp_path, [{"name": "w", "payload": "x", "expect": "deny"}])
    r = run_harness("--target", str(target), "--vectors", str(vecs), "--skip-structural")
    assert r.returncode == 2
    assert "why" in r.stderr


def test_an_unknown_vector_key_is_refused_rather_than_ignored(tmp_path):
    # A typo'd key that is silently dropped is the same failure as a typo'd `expect`.
    target = write_exec(tmp_path / "ok.sh", "#!/bin/sh\nexit 0\n")
    vecs = vectors_file(tmp_path, [
        {"name": "w", "payload": "x", "expect": "deny", "why": "probe", "expects": "deny"},
    ])
    r = run_harness("--target", str(target), "--vectors", str(vecs), "--skip-structural")
    assert r.returncode == 2
    assert "expects" in r.stderr


def test_a_fully_specified_vectors_file_still_runs(tmp_path):
    target = write_exec(tmp_path / "deny.sh", (
        "#!/bin/sh\n"
        'printf \'{"permissionDecision":"deny"}\'\n'
    ))
    vecs = vectors_file(tmp_path, [
        {"name": "w", "payload": {"tool_name": "Bash"}, "expect": "deny", "why": "probe"},
    ])
    r = run_harness("--target", str(target), "--mode", "json", "--vectors", str(vecs),
                    "--skip-structural", "--artifacts-dir", str(tmp_path / "a"),
                    "--json-report")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["runs"] == 1
