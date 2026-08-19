#!/usr/bin/env python3
"""Tests for the rust-toolchain.toml override in run-contained.sh.

A target that pins `channel = "stable"` matches no toolchain in the images, which install
their stable by version, so rustup tries to fetch one and dies on the read-only rustup dir.
Measured on a real crate, that stopped every cargo invocation before any work. The preamble
export is what keeps such a target runnable, so the three properties that make it safe are
asserted here: it reads settings.toml rather than `rustup toolchain list` (which honours the
pin and re-triggers the sync), it does not clobber a value a recipe already set, and it is a
no-op on an image with no rustup.

Reads the wrapper and the references as text. No container, no network.

Run: pytest packages/sabot/tests/test_toolchain_override.py
"""

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage"
WRAPPER = SKILL / "scripts/run-contained.sh"
ISOLATION = SKILL / "references/isolation.md"
MATRIX = SKILL / "references/tool-coverage-matrix.md"
BODY = WRAPPER.read_text()


def test_preamble_exports_the_toolchain():
    assert "export RUSTUP_TOOLCHAIN=" in BODY, \
        "without this, any target pinning a toolchain stops the campaign"


def test_toolchain_is_read_from_settings_not_from_rustup():
    """`rustup toolchain list` honours rust-toolchain.toml too, so using it to discover the
    default re-triggers the channel sync the override exists to avoid."""
    assert "/usr/local/rustup/settings.toml" in BODY
    assert "default_toolchain" in BODY
    preamble = BODY.split("RUSTUP_TOOLCHAIN")[0].rsplit("PREAMBLE", 1)[-1]
    assert "rustup toolchain list" not in preamble


def test_override_does_not_clobber_an_explicit_choice():
    """A recipe may need a specific toolchain; the preamble must yield to it."""
    assert '[ -z "${RUSTUP_TOOLCHAIN:-}" ]' in BODY


def test_override_is_a_no_op_without_rustup():
    """The same preamble runs on the python and node surfaces, which have no rustup."""
    assert "[ -r /usr/local/rustup/settings.toml ]" in BODY


def test_isolation_records_the_failure_and_the_nightly_escape():
    doc = ISOLATION.read_text()
    assert "syncing channel updates for stable" in doc, \
        "the measured error must stay recorded or the MUST reads as a preference"
    assert "Read-only file system" in doc
    assert "`+nightly` on the command line outranks the variable" in doc, \
        "cargo-fuzz and Miri depend on this, so it must be stated"


def test_matrix_records_the_real_crate_result():
    matrix = MATRIX.read_text()
    assert "not a char boundary" in matrix, \
        "the end-to-end finding is the evidence the rust surface works on real code"
    assert "from_utf8_lossy" in matrix, "the cause belongs next to the panic"
    assert "unexpected argument" in matrix, \
        "cargo fuzz rejects --offline; a recipe passing it fails on argument parsing"
