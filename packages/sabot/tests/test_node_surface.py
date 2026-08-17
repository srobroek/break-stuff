#!/usr/bin/env python3
"""Tests for the node surface, guarding the two ways its fuzzer has shipped unrunnable.

Jazzer.js has now been installed, asserted, and unable to fuzz twice: first the arm64
prebuilt addon failed at dlopen behind a passing `jazzer --version` (bs-156), then a global
npm install nested the @jazzer.js peers where core does not look for them. Both times the
image reported the fuzzer present. So the build must assert a CRASH, not a version string.

Reads the Dockerfile as text. No container, no network.

Run: pytest packages/sabot/tests/test_node_surface.py
"""

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage"
DOCKERFILE = SKILL / "references/containers/Dockerfile.node"
MATRIX = SKILL / "references/tool-coverage-matrix.md"
BODY = DOCKERFILE.read_text()


def test_jazzer_is_not_installed_globally():
    """`npm i -g @jazzer.js/core` nests the peers under core/node_modules/.

    Measured, core resolves them as SIBLINGS, so every run died before its first input:
    "ENOENT ... @jazzer.js/bug-detectors/dist/internal", while --version still answered.
    """
    # Anchored past a leading `&&`, not a bare substring: the rationale comment below
    # quotes the broken command verbatim, so an unanchored search flags its own docs.
    globals_ = re.findall(r"^\s*(?:&&\s*)?npm i -g ([^\\\n]*)", BODY, re.M)
    assert globals_, "the image still installs something globally; check this test"
    for line in globals_:
        assert "jazzer" not in line, \
            "a global install puts the @jazzer.js peers where core cannot find them"


def test_jazzer_is_installed_into_a_prefix_dir_and_symlinked():
    assert "/opt/jazzer" in BODY, "install locally so the @jazzer.js peers stay siblings"
    assert re.search(r"npm i @jazzer\.js/core", BODY), "a LOCAL install, not -g"
    assert "ln -sf /opt/jazzer/node_modules/.bin/jazzer /usr/local/bin/jazzer" in BODY, \
        "the campaign invokes `jazzer`, so the local binary needs to be on PATH"


def test_the_sibling_layout_is_asserted_not_assumed():
    assert "test -d /opt/jazzer/node_modules/@jazzer.js/bug-detectors/dist/internal" in BODY, \
        "assert the exact path whose absence killed every run"


def test_the_build_requires_a_real_crash_not_a_version_string():
    """--version answered in BOTH failure modes, so it proves nothing about fuzzing."""
    assert "grep -q 'Uncaught Exception'" in BODY, \
        "the build must fuzz a seeded target and require the crash report"
    assert "-runs=" in BODY, "run the fuzzer, do not just load it"


def test_retire_is_still_pinned_by_sha_and_baked():
    """retire.js fetches its definitions per run; unbaked it finds nothing offline."""
    assert "RETIREJS_SHA=" in BODY
    assert "jsrepository-v5.json" in BODY


def test_jazzer_tmpdir_dependency_is_recorded():
    """Under --read-only with no writable TMPDIR it exits 77 and prints no crash at all.

    The wrapper supplies TMPDIR=/scratch/tmp, so the shipped path works; the risk is a
    hand-rolled docker run, where a found bug is reported as three lines of INFO noise.
    """
    matrix = MATRIX.read_text()
    assert re.search(r"writable\s+`?TMPDIR`?", matrix, re.I), \
        "record the TMPDIR dependency: without it a real crash reports as noise"
    wrapper = (SKILL / "scripts/run-contained.sh").read_text()
    assert "TMPDIR=/scratch/tmp" in wrapper, "the wrapper must supply a writable TMPDIR"


def test_measured_fixture_results_are_recorded():
    matrix = MATRIX.read_text()
    for tool in ("Jazzer.js", "fast-check"):
        row = next(l for l in matrix.splitlines() if l.startswith(f"| {tool} "))
        assert "VERIFIED" in row, f"{tool} ran against node-parser; record the measurement"
