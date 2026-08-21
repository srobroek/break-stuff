#!/usr/bin/env python3
"""Reject invocations that are measured to fail open. Runs over the skill tree, or a recipe.

    lint-recipes.py PATH [PATH...] [--json] [--include-prose]

Each rule below is an invocation that a campaign copied verbatim and that returned a clean
result while running nothing, or ran less than it reported. Every one was measured. The
lint exists because the rule forbidding it already existed in prose and was violated
anyway.

WHAT COUNTS AS A RECIPE. Only lines that can be copied and run: fenced code blocks in
Markdown, and non-comment lines in `.sh`/`.py`. Reference prose has to QUOTE a forbidden
invocation in order to forbid it, and a Markdown table row saying "never do X" is not an
instance of X. Flagging those made the first real-tree pass 54 violations of which 40 were
the documentation of the rules themselves -- and a lint that is mostly noise gets
suppressed rather than fixed, which is the same fail-open this file exists to close.
`--include-prose` scans everything for an auditor who wants every mention.

EXIT CODES: 0 clean, 1 a violation was found, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXIT_VIOLATION = 1
EXIT_USAGE = 2

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}
TEXT_SUFFIXES = {".md", ".sh", ".py", ".yml", ".yaml", ".json", ".toml", ""}

# (id, regex, why). `why` names the observable symptom, because a lint message that only
# says "forbidden" gets suppressed rather than fixed.
RULES: list[tuple[str, str, str]] = [
    (
        "bd-plural-label",
        r"bd\s+(list|ready|show)\b[^\n]*--labels\b",
        "`--labels` is not the query flag (`--label` is) and SILENTLY returns nothing on a "
        "query. A whole wisp set once read as 'no work exists'.",
    ),
    (
        "bd-set-metadata",
        r"bd\s+update\b[^\n]*--set-metadata\b",
        "`--set-metadata` clobbers the whole object; concurrent stamps lose each other. "
        "Use `--metadata` so keys merge.",
    ),
    (
        "cargo-test-fail-fast",
        r"cargo\s+(\+\S+\s+)?test\b(?![^\n]*--no-fail-fast)",
        "without `--no-fail-fast` a workspace stops at the first failing binary. Measured: "
        "3 of 22 test binaries reached, and the remaining 19 read as unrun-but-fine.",
    ),
    (
        "cargo-locked",
        # `cargo install X --locked` is the CORRECT way to pin a tool build and is not
        # what this rule is about; the hazard is `--locked` on the target's own workspace.
        r"cargo\s+(\+\S+\s+)?(?!install\b)\S+[^\n]*\s--locked\b",
        "`--locked` fails BEFORE compilation, so the surface reports zero findings and "
        "looks clean. The skill's own fuzzer adds dev-dependencies (30 Cargo.toml files "
        "gained proptest), so Cargo.lock is dirty by design.",
    ),
    (
        "gitleaks-git-mode",
        r"gitleaks\s+(detect|git)\b(?![^\n]*--no-git)",
        "git mode on a worktree whose `.git` is a pointer file saw 0 commits and exited 0. "
        "Use `gitleaks dir` for a tree scan (`detect --no-git` is also filesystem mode).",
    ),
    (
        "opengrep-config-auto",
        r"(opengrep|semgrep)\b[^\n]*--config[= ]auto\b",
        "stock registry packs cannot load under `--network none`: OG_RC=2, and across a "
        "15-node campaign no stock ruleset ever executed. Point --config at a baked dir.",
    ),
    (
        "opengrep-metrics",
        r"(opengrep|semgrep)\b[^\n]*--metrics\b",  # lint-recipes: allow (own pattern)
        "`--metrics` exits 2 with zero findings; four nodes hit it independently.",
    ),
    (
        "login-shell",
        r"\bbash\s+-[a-zA-Z]*l[a-zA-Z]*c\b",
        "a login shell re-reads the profile and resets PATH, so `cargo` vanishes inside "
        "the container. `bash -c` and `sh -c` work.",
    ),
    (
        "tee-swallows-status",
        r"\|\s*tee\b(?![^\n]*PIPESTATUS)",
        "a pipeline reports its LAST stage, so `cmd | tee log` discards the failure. "  # lint-recipes: allow
        "Redirect to a file and read `$?`.",
    ),
    (
        "rm-rf-unexpanded",
        r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\s+\"?\$",
        "an unset variable collapses the path toward `/`. Resolve and validate the path, "
        "then delete a literal.",
    ),
    (
        "shared-cargo-target",
        r"CARGO_TARGET_DIR=(?![^\n]*(\$\{?SABOT_BUILD_DIR|/artifacts/\.build))[^\n]*",  # lint-recipes: allow
        "a shared target dir produced phantom compile errors when a concurrent build "
        "erased branch-new symbols. Use $SABOT_BUILD_DIR (per-node) or /artifacts/.build.",
    ),
]

COMPILED = [(rid, re.compile(pat), why) for rid, pat, why in RULES]

# A line carrying this marker is a documented counter-example rather than a recipe. Both
# the lint's own source and the reference prose need to name the bad invocation to forbid
# it, so without an opt-out the linter would flag its own rules.
ALLOW_MARKER = "lint-recipes: allow"


FENCE = re.compile(r"^\s*(```|~~~)")


def scan_text(text: str, label: str, include_prose: bool = False) -> list[dict]:
    """Flag runnable recipe lines. `include_prose` drops the context filter entirely."""
    out = []
    is_markdown = label.endswith((".md", ".markdown"))
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if is_markdown and FENCE.match(line):
            in_fence = not in_fence
            continue
        if ALLOW_MARKER in line:
            continue
        if not include_prose:
            if is_markdown and not in_fence:
                continue
            # A comment is an explanation, not an invocation. Every rule here has to be
            # named in a comment somewhere for the message to be readable at all.
            if not is_markdown and line.lstrip().startswith("#"):
                continue
        for rid, rx, why in COMPILED:
            if rx.search(line):
                out.append({"rule": rid, "file": label, "line": n,
                            "text": line.strip()[:160], "why": why})
    return out


def iter_files(paths: list[Path]):
    for p in paths:
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if any(part in SKIP_DIRS for part in f.parts):
                    continue
                if f.is_file() and f.suffix in TEXT_SUFFIXES:
                    yield f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lint-recipes.py")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--include-prose", action="store_true",
                    help="also scan prose and comments: every mention, not every recipe")
    args = ap.parse_args(argv)

    roots = [Path(p).expanduser() for p in args.paths]
    for r in roots:
        if not r.exists():
            print(f"lint-recipes: no such path: {r}", file=sys.stderr)
            return EXIT_USAGE

    hits: list[dict] = []
    for f in iter_files(roots):
        try:
            hits.extend(scan_text(f.read_text(errors="replace"), str(f),
                                  include_prose=args.include_prose))
        except OSError:
            pass

    if args.json:
        print(json.dumps({"schema": "sabot-recipe-lint/1", "violations": hits}, indent=2))
    else:
        for h in hits:
            print(f"{h['file']}:{h['line']}: [{h['rule']}] {h['text']}")
            print(f"    {h['why']}")
        print(f"lint-recipes: {len(hits)} violation(s) across "
              f"{len({h['file'] for h in hits})} file(s)")
    return EXIT_VIOLATION if hits else 0


if __name__ == "__main__":
    sys.exit(main())
