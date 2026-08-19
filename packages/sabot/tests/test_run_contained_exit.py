#!/usr/bin/env python3
"""Tests that run-contained.sh propagates the contained command's exit code.

The wrapper is the only sanctioned way a campaign executes anything, and a caller reads
its verdict from the exit code alone. That made a one-token bug in the EXIT trap
expensive: `cleanup()` ended with `[ -n "${STAGE:-}" ] && rm -rf "$STAGE"`, and under
`set -e` an EXIT trap's final status REPLACES the script's exit code. STAGE is set only
when the target lives outside $HOME, so on the normal in-$HOME path that test returned 1
and collapsed every run -- clean or broken -- to exit 1. A passing scan and a crashed
scanner became indistinguishable, and the script's own documented `exit 4` (INVALID
copy-out) was unreachable.

Measured before the fix: inner `exit 0` -> wrapper rc 1. After: inner 0 -> 0, inner 7 -> 7.

Reads the wrapper as text. No container, no network.

Run: pytest packages/sabot/tests/test_run_contained_exit.py
"""

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage"
WRAPPER = SKILL / "scripts/run-contained.sh"
BODY = WRAPPER.read_text()

CLEANUP = next(line for line in BODY.splitlines() if line.startswith("cleanup()"))


def test_cleanup_cannot_decide_the_exit_code():
    """The trap must end on a command that always succeeds, or its status becomes the
    script's. A bare test as the last statement is the bug this guards."""
    assert CLEANUP.rstrip().endswith(":; }"), (
        "cleanup() must end with `:` so the EXIT trap cannot overwrite the real exit "
        f"code; got: {CLEANUP}"
    )


def test_the_staging_test_is_still_what_makes_this_necessary():
    """Documents WHY the `:` is load-bearing: the preceding test is false on the common
    path. If the staging branch ever goes away, so does the hazard."""
    assert '[ -n "${STAGE:-}" ]' in CLEANUP, (
        "the trailing `:` guards against this test's status leaking into the exit code"
    )


def test_the_hazard_is_explained_at_the_call_site():
    """A future edit that drops the `:` as noise reintroduces a silent false-clean, so the
    reason has to sit next to the code rather than only in a commit message."""
    assert "REPLACES the script's exit code" in BODY


def test_the_documented_invalid_exit_is_reachable():
    """`exit 4` signals an INVALID copy-out. With the trap clobbering the status it could
    never reach a caller, so the contract only holds while the fix is in place."""
    assert "exit 4" in BODY


COPY_SRC = next(line for line in BODY.splitlines() if "mkdir -p /scratch/src" in line)


def test_the_staging_tar_is_checked_through_the_pipe():
    """The creating tar is the LEFT side of a pipe, so without `pipefail` the preamble's
    status comes from the EXTRACTING tar -- which succeeds on whatever bytes it got. That
    is the false-clean this wrapper exists to prevent: `cd /scratch/src` works and the
    build scans a partial repo. Measured in sabot/base:1 (tar 1.35): SRC_RC=1 while the
    pipeline reported 0."""
    assert "set -o pipefail" in COPY_SRC, (
        "the staging tar's failure is invisible without pipefail; a partial source copy "
        "then reads as a clean scan"
    )
    assert "exit 5" in COPY_SRC, (
        "a failed staging tar must exit 5 -- distinct from 2/3/4 -- so a caller can tell "
        "'staging failed' from 'the contained command failed'"
    )


def test_the_run_s_own_state_dirs_are_excluded():
    """`.sabot` (artifacts) and `.beads` (a live sqlite WAL) are written BY the campaign
    while it runs, so tarring them churns the tree under tar and fails the check above on
    the wrapper's own activity. Measured on a live target mid-campaign: 1/6 runs failed
    with `.beads` included, 0/6 with it excluded."""
    for path in ("./target", "./.git", "./.sabot", "./.beads"):
        assert f"--exclude={path}" in COPY_SRC, f"staging tar must exclude {path}"


def test_the_staging_tar_retries_before_declaring_failure():
    """GNU tar returns the same exit 1 for a file that changed mid-read and for an
    unrelated sibling appearing at the repo root (which bumps `.`'s mtime). Measured after
    the excludes: 1/20 live runs still failed, always on `.`, while a static tree failed
    0/40. Hard-failing on that aborts a campaign for nothing; a source genuinely being
    rewritten keeps failing and still exits 5."""
    assert "for _try in 1 2 3" in COPY_SRC, (
        "a single attempt makes benign root churn abort the run"
    )
    assert "failed 3 times" in COPY_SRC, (
        "the give-up message must say the retries were exhausted, not that one tar failed"
    )
