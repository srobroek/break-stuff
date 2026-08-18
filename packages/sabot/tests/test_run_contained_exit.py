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
