#!/usr/bin/env python3
"""Discover every dependency manifest in a target repo, deterministically.

The image is provisioned from the target's manifests (isolation.md, Provisioning),
and a real target is often a workspace, a monorepo, or multi-language (a Tauri app is
Rust under src-tauri/ plus a JS frontend). Guessing "the manifest" misses one. This
script enumerates them from `git ls-files`, so it honors .gitignore for free, sees
every member of a workspace, and never depends on an agent globbing correctly.

Usage:
  detect-stacks.py [--repo <dir>] [--bake]

  (default) with no --bake, emit the manifest map + detected stacks as JSON.
          bake_units carry {stack, dir, fetch}, so a caller has everything structured.
  --bake  emit the provision command lines (`cd <dir> && <fetch>`), one per bake
          unit, for a Dockerfile RUN or an `sh -c` at image build. These are command
          content, not a standalone script: the caller runs them where Docker RUN
          semantics already provide the shell.

Exit: 0 ok; 2 usage; 3 not a git repo / git absent.
"""

import argparse
import json
import os
import subprocess
import sys

# manifest filename -> (stack, lockfiles, the fetch command that provisions its deps).
# The fetch runs at image build with the network up; it reads the manifest the repo
# already ships, so the dep set is declared, never guessed.
MANIFESTS = {
    "Cargo.toml": ("rust", ["Cargo.lock"], "cargo fetch"),
    "package.json": ("node", ["package-lock.json", "pnpm-lock.yaml", "yarn.lock"],
                     "npm ci || npm install"),  # refined by node_fetch() from the lockfile
    "pyproject.toml": ("python", ["uv.lock", "poetry.lock", "requirements-dev.txt"],
                       "uv sync --frozen || pip install -e '.[dev]' || true"),
    "requirements-dev.txt": ("python", [], "pip install -r requirements-dev.txt"),
    "go.mod": ("go", ["go.sum"], "go mod download"),
}


def tracked_files(repo):
    """Every tracked file, so .gitignore is honored and untracked scratch is skipped."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError:
        sys.exit(3)
    except subprocess.CalledProcessError:
        sys.exit(3)
    return [line for line in out.splitlines() if line]


def is_cargo_workspace(repo, rel):
    """A Cargo.toml with [workspace] provisions all members from one `cargo fetch`."""
    try:
        with open(os.path.join(repo, rel)) as fh:
            return "[workspace]" in fh.read()
    except OSError:
        return False


# A node manifest's fetch is decided by its LOCKFILE, not by npm being the default.
# `npm ci` on a pnpm workspace fails twice over: there is no package-lock.json, and
# `workspace:` specifiers are not npm-resolvable. The fallback `npm install` then
# silently re-resolves a different tree than the one the repo pinned.
NODE_FETCH = {
    "pnpm-lock.yaml": "pnpm install --frozen-lockfile",
    "yarn.lock": "yarn install --immutable || yarn install --frozen-lockfile",
    "package-lock.json": "npm ci",
}


def node_fetch(found_locks):
    for lock, cmd in NODE_FETCH.items():
        if lock in found_locks:
            return cmd
    return "npm install"


def is_node_workspace(repo, rel):
    """True when this package.json is a workspace root (pnpm, npm, or yarn)."""
    directory = os.path.dirname(rel)
    if os.path.exists(os.path.join(repo, directory, "pnpm-workspace.yaml")):
        return True
    try:
        with open(os.path.join(repo, rel), encoding="utf-8") as fh:
            return "workspaces" in json.load(fh)
    except (OSError, ValueError):
        return False


def in_dot_dir(rel):
    """Manifests under a dot-directory are agent/editor tooling, not the audited code.

    A repo vendoring skills under .claude/ or .specify/ ships their package.json too.
    Baking those installs a native-addon build chain the campaign never exercises and
    fails the whole ext image on an unrelated dep.
    """
    return any(part.startswith(".") for part in rel.split("/")[:-1])


def detect(repo):
    files = tracked_files(repo)
    present = set(files)
    manifests = []
    for rel in files:
        name = os.path.basename(rel)
        if name not in MANIFESTS or in_dot_dir(rel):
            continue
        stack, locks, fetch = MANIFESTS[name]
        directory = os.path.dirname(rel) or "."
        found_locks = [lk for lk in locks
                       if (os.path.join(directory, lk) if directory != "." else lk) in present]
        entry = {
            "manifest": rel,
            "dir": directory,
            "stack": stack,
            "lockfiles": found_locks,
            "fetch": fetch,
        }
        if name == "Cargo.toml":
            entry["workspace_root"] = is_cargo_workspace(repo, rel)
        if name == "package.json":
            entry["workspace_root"] = is_node_workspace(repo, rel)
            entry["fetch"] = node_fetch(found_locks)
        manifests.append(entry)

    # Collapse Cargo workspace members: if a workspace root exists, its members are
    # provisioned by the root fetch, so a member Cargo.toml needs no separate bake.
    ws_roots = {}
    for m in manifests:
        if m.get("workspace_root"):
            ws_roots.setdefault(m["stack"], set()).add(m["dir"])

    def under_ws_root(m):
        if m.get("workspace_root"):
            return False
        roots = ws_roots.get(m["stack"], set())
        return any(m["dir"] == r or m["dir"].startswith(r.rstrip("/") + "/")
                   for r in roots if r != ".") or ("." in roots and m["dir"] != ".")

    bake_units = [m for m in manifests if not under_ws_root(m)]
    stacks = sorted({m["stack"] for m in manifests})
    return {
        "repo": repo,
        "stacks": stacks,
        "multi_language": len(stacks) > 1,
        "manifests": manifests,
        "bake_units": bake_units,
    }


def bake_lines(result):
    """One provision command line per bake unit: `cd <dir> && <fetch>`.

    The build context is the manifest+lock only (isolation.md), so these run against
    a copied-in manifest at build time (network up), then the target is mounted
    read-only at run. These are command lines for a Dockerfile RUN or `sh -c`, not a
    standalone script, so there is no shebang: the caller supplies the shell.
    """
    lines = ["# provision commands from detect-stacks.py; run at image build (network up)"]
    for m in result["bake_units"]:
        cd = "" if m["dir"] == "." else f'cd "{m["dir"]}" && '
        lines.append(f"{cd}{m['fetch']}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--bake", action="store_true", help="emit bake shell commands")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        # allow a worktree/submodule where .git is a file, or a subdir of a repo
        rc = subprocess.run(["git", "-C", repo, "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
        if rc.returncode != 0 or rc.stdout.strip() != "true":
            # Say why. A bare exit 3 sent every caller hunting the wrong fault:
            # build-ext-image.sh could only report "detect-stacks.py failed", which
            # reads as a broken script rather than a target that is not a git repo.
            print(f"detect-stacks: not a git repository: {repo}\n"
                  "  Stack detection reads `git ls-files` so .gitignore is honored.\n"
                  "  Point --repo at a checkout, or `git init` the target first.",
                  file=sys.stderr)
            sys.exit(3)

    result = detect(repo)
    if args.bake:
        sys.stdout.write(bake_lines(result))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
