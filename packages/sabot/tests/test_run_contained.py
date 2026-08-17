#!/usr/bin/env python3
"""Tests for run-contained.sh, the container isolation wrapper.

Every target-touching tool runs through this script, so its EXIT CODE is the
campaign's only signal that a phase succeeded. The invariant this file guards: the
wrapper reports the contained command's own status, unchanged. A wrapper that
always exits non-zero makes a real finding indistinguishable from a broken run;
one that always exits zero hides a scanner that never ran.

The tests drive the real script against a stub `docker` on PATH that echoes the
exit code it is told to (the stub pattern from test_build_ext_image.py). No real
docker, no network, no container.

Run: pytest packages/sabot/tests/test_run_contained.py
Stdlib plus pytest.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage/scripts/run-contained.sh"

# A stub `docker` covering the four subcommands the wrapper drives: `run` (whose
# exit code is the one under test), plus the volume/create/cp/rm calls of the
# findings copy-out. `run` exits with $STUB_RC so a test can demand any status.
STUB_DOCKER = """#!/usr/bin/env bash
case "$1" in
  run)     exit "${STUB_RC:-0}" ;;
  volume)  echo stub-vol ;;
  create)  echo stubcid ;;
  cp)      exit 0 ;;
  rm)      exit 0 ;;
  context) echo stub-ctx ;;
  *)       exit 0 ;;
esac
"""


@pytest.fixture
def stub_env(tmp_path):
    """PATH with a stub docker ahead of any real one, plus target/artifacts dirs.

    HOME is repointed at tmp_path and the target placed UNDER it, so the script
    takes its in-$HOME branch and leaves STAGE unset. That is the path a real
    campaign takes, and the one where a falsy final command in the cleanup trap
    silently rewrites the exit status.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text(STUB_DOCKER)
    stub.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    target = home / "target"
    target.mkdir()
    (target / "Cargo.toml").write_text("[package]\nname='x'\n")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(home))
    return env, target, artifacts


def run_wrapper(stub_env, rc, extra=()):
    env, target, artifacts = stub_env
    env = dict(env, STUB_RC=str(rc))
    r = subprocess.run(
        ["bash", str(SCRIPT), "--image", "sabot/base:1",
         "--target", str(target), "--artifacts", str(artifacts),
         *extra, "--", "sh", "-c", "true"],
        capture_output=True, text=True, env=env,
    )
    return r


def test_propagates_success(stub_env):
    """A contained command that succeeds must not read as a failed phase."""
    r = run_wrapper(stub_env, 0)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("rc", [1, 7, 77, 101])
def test_propagates_failure_status(stub_env, rc):
    """The contained command's own status survives, not a flattened 1."""
    r = run_wrapper(stub_env, rc)
    assert r.returncode == rc, r.stderr


def test_propagates_success_with_copy_src(stub_env):
    """--copy-src sets no STAGE; the cleanup trap must not clobber the status."""
    r = run_wrapper(stub_env, 0, extra=("--copy-src", "--workdir", "/scratch"))
    assert r.returncode == 0, r.stderr


def test_rejects_bad_workdir(stub_env):
    """Only /target and /scratch are allowed; anything else is a usage error."""
    env, target, artifacts = stub_env
    r = subprocess.run(
        ["bash", str(SCRIPT), "--image", "sabot/base:1",
         "--target", str(target), "--artifacts", str(artifacts),
         "--workdir", "/etc", "--", "sh", "-c", "true"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 2
    assert "--workdir" in r.stderr


def test_assert_tools_rejects_injection(stub_env):
    """A tool name is interpolated into an in-container sh -c, so reject shell meta."""
    env, _, _ = stub_env
    r = subprocess.run(
        ["bash", str(SCRIPT), "--assert-tools", "sabot/base:1", "ripgrep;id"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 2
    assert "illegal tool name" in r.stderr
