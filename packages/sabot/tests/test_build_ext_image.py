#!/usr/bin/env python3
"""Tests for build-ext-image.sh, the dev-dep bake into a surface image.

The ext image lets a --network none campaign use the target's dev-deps (a
`cargo test` that pulls `proptest`). The invariant this file guards: the build
context copies ONLY manifests + lockfiles, never the target source, so no audited
code enters a persisted layer (isolation.md, "Never COPY the target source").

The tests read the generated Dockerfile via --dry-run (no build), and drive a real
build path against a stub `docker` on PATH that records its args (the pattern from
test_report_json.py's stub bd / test_detect_stacks.py's real git repos).

Run: pytest packages/sabot/tests/test_build_ext_image.py
Stdlib plus pytest; needs `git` on PATH. No real docker, no network.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".apm" / "skills" / "sabotage" / "scripts" / "build-ext-image.sh"
)


def make_repo(root: Path, files: dict[str, str]):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root, check=True,
    )


def dry_run(target: Path, base="sabot/rust:1", tag="sabot/rust-ext:1"):
    r = subprocess.run(
        ["bash", str(SCRIPT), "--target", str(target), "--base", base, "--tag", tag, "--dry-run"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_froms_the_given_base(tmp_path):
    make_repo(tmp_path, {"Cargo.toml": "[package]\nname='x'\n", "Cargo.lock": "", "src/lib.rs": "fn x(){}"})
    df = dry_run(tmp_path, base="sabot/rust:1")
    assert df.splitlines()[0] == "FROM sabot/rust:1"


def test_copies_only_manifest_and_lock_never_source(tmp_path):
    make_repo(tmp_path, {
        "Cargo.toml": "[package]\nname='x'\n",
        "Cargo.lock": "# lock\n",
        "src/lib.rs": "fn secret(){}",
        "src/main.rs": "fn main(){}",
    })
    df = dry_run(tmp_path)
    copy_lines = [l for l in df.splitlines() if l.startswith("COPY")]
    assert copy_lines, df
    joined = "\n".join(copy_lines)
    assert "Cargo.toml" in joined
    assert "Cargo.lock" in joined
    # The invariant is about CONTENT, not filenames. Rust needs a src/lib.rs to exist
    # or `cargo fetch` aborts with no targets, so the script writes an EMPTY stub into
    # the build context and copies that. Asserting on the path (`".rs" not in joined`)
    # rejected the legitimate stub; assert the audited bytes stay out instead.
    assert "src/main.rs" not in joined
    assert 'open(os.path.join(stub_dir, "lib.rs"), "a").close()' in SCRIPT.read_text(), \
        "the rust src/lib.rs stub must be CREATED empty, never copied from the target"


def test_one_run_per_bake_unit(tmp_path):
    # multi-language: rust workspace root + a JS frontend => two bake units
    make_repo(tmp_path, {
        "Cargo.toml": "[workspace]\nmembers=['src-tauri']\n",
        "Cargo.lock": "",
        "src-tauri/Cargo.toml": "[package]\nname='app'\n",
        "frontend/package.json": '{"name":"f","devDependencies":{"vite":"^5"}}',
        "frontend/package-lock.json": "{}",
    })
    df = dry_run(tmp_path)
    run_lines = [l for l in df.splitlines() if l.startswith("RUN ") and ("fetch" in l or "npm" in l or "download" in l or "sync" in l)]
    assert len(run_lines) == 2, df
    assert any("cargo fetch" in l for l in run_lines)
    assert any("npm ci" in l for l in run_lines)
    # the src-tauri member is collapsed into the workspace root: not copied separately
    assert "src-tauri/Cargo.toml" not in df


def test_copy_precedes_its_run_so_layer_caches_on_lock(tmp_path):
    make_repo(tmp_path, {"Cargo.toml": "[package]\nname='x'\n", "Cargo.lock": ""})
    df = dry_run(tmp_path)
    lines = df.splitlines()
    copy_idx = next(i for i, l in enumerate(lines) if l.startswith("COPY"))
    run_idx = next(i for i, l in enumerate(lines) if l.startswith("RUN cargo fetch") or l == "RUN cargo fetch")
    assert copy_idx < run_idx


def test_every_copy_chowns_to_the_build_uid(tmp_path):
    """A fetch REWRITES the lock it was copied, and COPY writes root-owned files.

    Measured: without --chown, `cargo fetch` as uid 1000 aborted the ext build with
    "failed to write /scratch/Cargo.lock: Permission denied".
    """
    make_repo(tmp_path, {"Cargo.toml": "[package]\nname='x'\n", "Cargo.lock": ""})
    df = dry_run(tmp_path)
    copies = [l for l in df.splitlines() if l.startswith("COPY")]
    assert copies
    for l in copies:
        assert l.startswith("COPY --chown=1000:1000 "), f"unowned copy: {l}"


def test_dep_cache_is_persistent_not_scratch(tmp_path):
    # /scratch is a fresh tmpfs per run (run-contained.sh); baking there is masked.
    make_repo(tmp_path, {"Cargo.toml": "[package]\nname='x'\n", "Cargo.lock": ""})
    df = dry_run(tmp_path)
    assert "CARGO_HOME=/deps/cargo" in df
    assert "/scratch" not in df


@pytest.fixture
def stub_docker(tmp_path):
    """A fake `docker` on PATH: image inspect ok, build records its argv to a file."""
    rec = tmp_path / "docker-argv.txt"
    dk = tmp_path / "docker"
    dk.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{rec}"\n'
        'case "$1" in\n'
        '  image) exit 0 ;;\n'          # inspect: base present
        '  build) exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    dk.chmod(dk.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return dk, rec


def test_build_invokes_runtime_with_tag(tmp_path, stub_docker):
    dk, rec = stub_docker
    repo = tmp_path / "repo"
    repo.mkdir()
    make_repo(repo, {"go.mod": "module x\n", "go.sum": ""})
    env = dict(os.environ, PATH=f"{dk.parent}:{os.environ['PATH']}")
    r = subprocess.run(
        ["bash", str(SCRIPT), "--target", str(repo),
         "--base", "sabot/base:1", "--tag", "sabot/base-ext:1"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    argv = rec.read_text()
    assert "build" in argv
    assert "-t sabot/base-ext:1" in argv


def test_missing_target_exits_2(tmp_path):
    r = subprocess.run(
        ["bash", str(SCRIPT), "--base", "b", "--tag", "t"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
