#!/usr/bin/env python3
"""Tests for detect-stacks.py, the deterministic manifest-discovery script.

The image is provisioned from what this script finds, so a missed manifest leaves a
member crate or a frontend unprovisioned and its harness cannot run under
--network none. The tests build real git repos so `git ls-files` behaves as it will
in a campaign, and cover the cases a repo-root guess misses: workspace, monorepo,
multi-language, and .gitignore'd files.

Run: pytest packages/sabot/tests/test_detect_stacks.py
Stdlib plus pytest; needs `git` on PATH.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".apm" / "skills" / "sabotage" / "scripts" / "detect-stacks.py"
)


def make_repo(root: Path, files: dict[str, str]):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    # --no-gpg-sign: see test_build_ext_image.py. A global `commit.gpgsign=true` with an
    # agent-backed signer hangs here forever, and pytest shows nothing while it does.
    subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=t",
         "commit", "--no-gpg-sign", "-qm", "init"],
        cwd=root, check=True,
    )


def run(root: Path, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(root), *args],
        capture_output=True, text=True,
    )


def test_single_rust_crate(tmp_path):
    make_repo(tmp_path, {"Cargo.toml": "[package]\nname='x'\n", "Cargo.lock": "", "src/lib.rs": ""})
    out = json.loads(run(tmp_path).stdout)
    assert out["stacks"] == ["rust"]
    assert out["multi_language"] is False
    assert len(out["bake_units"]) == 1
    assert out["bake_units"][0]["fetch"] == "cargo fetch"


def test_cargo_workspace_collapses_members(tmp_path):
    make_repo(tmp_path, {
        "Cargo.toml": "[workspace]\nmembers=['crates/*']\n",
        "Cargo.lock": "",
        "crates/a/Cargo.toml": "[package]\nname='a'\n",
        "crates/b/Cargo.toml": "[package]\nname='b'\n",
    })
    out = json.loads(run(tmp_path).stdout)
    # all three manifests discovered...
    assert len(out["manifests"]) == 3
    # ...but only the workspace root is a bake unit (root fetch provisions members)
    assert len(out["bake_units"]) == 1
    assert out["bake_units"][0]["dir"] == "."


def test_multi_language_tauri_shape(tmp_path):
    make_repo(tmp_path, {
        "Cargo.toml": "[workspace]\nmembers=['src-tauri']\n",
        "Cargo.lock": "",
        "src-tauri/Cargo.toml": "[package]\nname='app'\n",
        "frontend/package.json": '{"name":"f","devDependencies":{"vite":"^5"}}',
        "frontend/package-lock.json": "{}",
    })
    out = json.loads(run(tmp_path).stdout)
    assert out["multi_language"] is True
    assert set(out["stacks"]) == {"rust", "node"}
    fetches = {(u["stack"], u["dir"]) for u in out["bake_units"]}
    assert ("rust", ".") in fetches          # workspace root
    assert ("node", "frontend") in fetches   # frontend provisioned separately
    assert len(out["bake_units"]) == 2       # src-tauri member collapsed into root


def test_gitignored_manifest_is_skipped(tmp_path):
    make_repo(tmp_path, {
        "Cargo.toml": "[package]\nname='x'\n",
        ".gitignore": "vendor/\n",
    })
    # an ignored, untracked vendor manifest must not appear
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "package.json").write_text('{"name":"v"}')
    out = json.loads(run(tmp_path).stdout)
    assert out["stacks"] == ["rust"]
    assert all("vendor" not in m["manifest"] for m in out["manifests"])


def test_bake_emits_command_lines(tmp_path):
    make_repo(tmp_path, {"go.mod": "module x\n", "go.sum": ""})
    r = run(tmp_path, "--bake")
    assert r.returncode == 0
    assert "go mod download" in r.stdout
    # command lines for a Dockerfile RUN, not a standalone script -> no shebang
    assert "#!" not in r.stdout


def test_not_a_repo_exits_3(tmp_path):
    r = run(tmp_path)  # tmp_path is not git-init'd
    assert r.returncode == 3
