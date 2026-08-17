#!/usr/bin/env python3
"""Tests for install-tools.sh, the host preflight.

The preflight decides whether a campaign is allowed to start, so its manifests are
the guard against a surface running with a scanner that is absent, or a fuzzer that
installed and cannot load. The invariants here:

  - Nothing installs on the host (a host-side scanner would run the target's build
    code unconfined).
  - A LIBRARY is asserted by import, never by `--version`. atheris, hypothesis, and
    fast-check ship no CLI, so naming them in the executable manifest reported them
    missing whether or not they were installed -- both a false alarm and a blind
    spot (bs-156).

The tests read the script text for its manifests and drive --help/bad-arg paths.
No container, no network.

Run: pytest packages/sabot/tests/test_install_tools.py
"""

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage/scripts/install-tools.sh"
BODY = SCRIPT.read_text()

# Packages with no executable of that name. Asserting `<name> --version` on one can
# only ever fail, so the executable manifest must not name it.
LIBRARIES_ONLY = ["atheris", "hypothesis", "fast-check"]


def manifest(surface: str) -> list[str]:
    m = re.search(rf'^IMAGE_TOOLS_{surface}="([^"]*)"', BODY, re.M)
    assert m, f"no IMAGE_TOOLS_{surface} manifest in {SCRIPT.name}"
    return m.group(1).split(",")


def test_installs_nothing_on_the_host():
    """A host-side scanner would run the target's build code unconfined."""
    assert "--probe" in BODY
    for installer in ("apt-get install", "brew install", "pip install", "npm i -g"):
        assert installer not in BODY, f"preflight must not install: {installer}"


def test_executable_manifests_name_no_library():
    """A library cannot answer --version; asserting it there is always a false FAIL."""
    for surface in ("base", "rust", "python", "node"):
        for lib in LIBRARIES_ONLY:
            assert lib not in manifest(surface), \
                f"{lib} has no CLI; assert it in IMAGE_LIBS_{surface} by import instead"


def test_library_manifests_import_the_fuzz_harness_packages():
    """The packages a harness imports must be proven to LOAD, not merely installed."""
    assert 'IMAGE_LIBS_python=' in BODY
    assert "import atheris" in BODY, "atheris is the python fuzzer; assert it loads"
    assert "hypothesis" in BODY
    assert 'IMAGE_LIBS_node=' in BODY
    assert "fast-check" in BODY


def test_every_surface_keeps_its_fuzzer_asserted():
    """Each language surface must assert its coverage-guided fuzzer somehow."""
    assert "cargo-fuzz" in manifest("rust")
    assert "jazzer" in manifest("node")
    assert "import atheris" in BODY          # python's fuzzer is a library


def test_probe_failure_is_loud_and_nonzero():
    """A preflight that fails quietly lets the campaign start on a broken image."""
    assert "preflight: FAILED" in BODY
    assert "return 1" in BODY


def test_help_exits_zero():
    r = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "--probe" in r.stdout


def test_unknown_argument_is_a_usage_error():
    r = subprocess.run(["bash", str(SCRIPT), "--wat"], capture_output=True, text=True)
    assert r.returncode == 2
    assert "unknown argument" in r.stderr
