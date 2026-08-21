"""run-layout.py is the single source for paths, slugs, env, and the ignore file."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / ".apm" / "skills" / "sabotage"
SCRIPT = SKILL / "scripts" / "run-layout.py"


def load():
    spec = importlib.util.spec_from_file_location("sabot_run_layout_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


layout = load()


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def make_root(tmp_path: Path) -> Path:
    root = layout.run_root(tmp_path / ".sabot" / "run-20260820a")
    layout.init(root)
    return root


# --- slugging ---------------------------------------------------------------


def test_node_id_colon_becomes_hyphen():
    # Node ids carry `:`; filenames carry `-`. A producer and consumer that disagree
    # produce a missing file, and a missing rules file read as "0 findings".
    assert layout.slug("code:metadata") == "code-metadata"


def test_slug_is_idempotent():
    for value in ("code:metadata", "Frontend TS", "infra//ci", "  spaced  "):
        once = layout.slug(value)
        assert layout.slug(once) == once


def test_slug_refuses_a_value_with_no_alphanumeric():
    with pytest.raises(ValueError):
        layout.slug(":::")


def test_slug_cli_exits_nonzero_on_an_empty_slug():
    p = run("slug", "///")
    assert p.returncode != 0


def test_no_subcommand_is_a_usage_error_not_a_silent_zero():
    p = run()
    assert p.returncode == 2


# --- durability -------------------------------------------------------------


def test_ephemeral_and_durable_are_decided_by_one_path_segment(tmp_path):
    root = make_root(tmp_path)
    assert layout.classify(root / "ephemeral" / "code-metadata" / "build", root) == "ephemeral"
    assert layout.classify(root / "artifacts" / "recon-code-metadata.md", root) == "durable"
    assert layout.classify(root / "logs", root) == "durable"
    assert layout.classify(root / "preflight.json", root) == "durable"


def test_host_scratch_is_ephemeral_though_it_lives_outside_the_run_root(tmp_path):
    root = make_root(tmp_path)
    assert layout.classify(layout.host_scratch(root), root) == "ephemeral"


def test_a_path_outside_the_run_root_is_refused(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(ValueError):
        layout.classify(tmp_path / "elsewhere", root)


def test_classify_resolves_a_not_yet_existing_path_under_a_symlinked_ancestor(tmp_path):
    # `Path.resolve()` on a missing path can leave an ancestor symlink unexpanded, which
    # once made an in-root deletion target compare as outside the root.
    real = tmp_path / "real"
    (real / ".sabot").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    root = layout.run_root(link / ".sabot" / "run-x")
    layout.init(root)
    assert layout.classify(root / "ephemeral" / "n" / "build" / "deep", root) == "ephemeral"


def test_classify_cli_exits_3_outside_the_root(tmp_path):
    root = make_root(tmp_path)
    p = run("classify", str(tmp_path / "elsewhere"), "--run-root", str(root))
    assert p.returncode == 3


# --- paths and env ----------------------------------------------------------


def test_paths_are_per_node_so_no_two_nodes_share_a_build_dir(tmp_path):
    root = make_root(tmp_path)
    a = layout.paths(root, node="code:metadata")
    b = layout.paths(root, node="code:frontend-ts")
    assert a["SABOT_BUILD_DIR"] != b["SABOT_BUILD_DIR"]
    # A shared CARGO_TARGET_DIR produced phantom compile errors when a concurrent build
    # erased branch-new symbols.
    for key in ("SABOT_BUILD_DIR", "SABOT_CACHE_DIR", "SABOT_CORPORA_DIR", "SABOT_SRC_DIR"):
        assert layout.EPHEMERAL_SEGMENT in a[key]


def test_every_emitted_variable_documents_its_lifetime_and_owner(tmp_path):
    root = make_root(tmp_path)
    names = layout.paths(root, node="code:metadata").keys()
    for name in names:
        assert name in layout.LIFETIMES, f"{name} is emitted with no documented lifetime"
        lifetime, owner = layout.LIFETIMES[name]
        assert lifetime and owner


def test_paths_json_reports_durability_per_variable(tmp_path):
    root = make_root(tmp_path)
    p = run("paths", "--run-root", str(root), "--node", "code:metadata", "--json")
    assert p.returncode == 0
    by_var = {row["var"]: row for row in json.loads(p.stdout)["paths"]}
    assert by_var["SABOT_ARTIFACTS"]["durability"] == "durable"
    assert by_var["SABOT_BUILD_DIR"]["durability"] == "ephemeral"
    for row in by_var.values():
        assert row["lifetime"] and row["owner"]


def test_env_emits_shell_exports(tmp_path):
    root = make_root(tmp_path)
    p = run("env", "--run-root", str(root), "--node", "code:metadata")
    assert p.returncode == 0
    assert "export SABOT_BUILD_DIR=" in p.stdout
    assert "export SABOT_ARTIFACTS=" in p.stdout


def test_init_creates_durable_dirs_and_the_ignore_file(tmp_path):
    root = make_root(tmp_path)
    for sub in layout.DURABLE_SUBDIRS:
        assert (root / sub).is_dir()
    assert (root / ".gitignore").is_file()


# --- artifact naming --------------------------------------------------------


def test_artifact_names_match_the_names_the_campaign_actually_produced(tmp_path):
    root = make_root(tmp_path)
    got = layout.artifact_path(root, "recon", "code:metadata")
    assert got.name == "recon-code-metadata.md"
    assert got.parent == root / "artifacts"
    assert layout.artifact_path(root, "rules", "code:metadata", ".yml").name == (
        "rules-code-metadata.yml"
    )


def test_artifact_without_a_node_has_no_trailing_separator(tmp_path):
    root = make_root(tmp_path)
    assert layout.artifact_path(root, "operational-notes", None).name == "operational-notes.md"


def test_artifact_cli_tolerates_an_extension_without_a_dot(tmp_path):
    root = make_root(tmp_path)
    p = run("artifact", "--run-root", str(root), "--kind", "rules",
            "--node", "code:metadata", "--ext", "yml")
    assert p.returncode == 0
    assert p.stdout.strip().endswith("rules-code-metadata.yml")


# --- the ignore file --------------------------------------------------------


def test_gitignore_ignores_ephemeral_and_leaves_evidence_visible(tmp_path):
    root = make_root(tmp_path)
    p = run("gitignore", "--run-root", str(root))
    assert p.returncode == 0
    body = Path(p.stdout.strip()).read_text()
    assert "/ephemeral/" in body
    # Durable evidence must stay visible in `git status` so the user can choose to commit
    # it. An ignore rule on a durable path hides findings, so no line may match one.
    rules = [ln.strip() for ln in body.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    for durable in ("/artifacts", "/logs", "/preflight.json"):
        assert not any(r.startswith(durable) for r in rules), rules
    assert "artifacts" in body  # documented as deliberately not ignored


def test_gitignore_says_it_is_generated(tmp_path):
    root = make_root(tmp_path)
    out = run("gitignore", "--run-root", str(root)).stdout.strip()
    assert "run-layout.py gitignore" in Path(out).read_text()


def test_a_git_repo_with_a_run_root_shows_no_ephemeral_noise(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    root = make_root(tmp_path)
    build = root / "ephemeral" / "code-metadata" / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "libhuge.rlib").write_bytes(b"0" * 4096)
    (root / "artifacts" / "recon-code-metadata.md").write_text("finding\n")
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout
    assert "ephemeral" not in out
    assert "recon-code-metadata.md" in out
