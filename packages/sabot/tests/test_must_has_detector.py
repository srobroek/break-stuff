"""Every metadata field a MUST names must be readable by the report generator.

This test is the sweep that found `partial_parse_files`, `total_s`, and
`budget_exhausted`, promoted out of a throwaway campaign. All three had the same shape:
a rule in this package told an agent to stamp a field, the agent stamped it, and nothing
ever read it -- so a compliant run and a non-compliant one produced identical reports.
Each was found by hand, months apart, by querying a live store.

The sweep ran three times and found a defect on all three passes. The third only
surfaced because the first two dismissals had been eyeball judgements, and one of those
was wrong: `budget_exhausted` was waved off twice as "a status value, not a field"
without checking whether any reader existed.

So the allowlist below is the load-bearing part. Every entry states WHY the key is not a
metadata field, and adding an entry is a claim that has to be true rather than a way to
silence the test. A key that is genuinely a field belongs in KEEP_META or a required
list, not here.
"""

import importlib.util
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
SKILL = PKG / ".apm/skills/sabotage"
RULE_PREFIXES = ("MUST ", "NOT ", "DEFAULT ")

# Keys that look like metadata and are not. Every entry carries its reason, because an
# unexplained entry is indistinguishable from a silenced defect -- which is how
# `budget_exhausted` survived two passes.
NOT_A_METADATA_FIELD = {
    # Enum VALUES of the `state` dimension. The field is `state`; these are what it holds,
    # and `bd set-state` writes them as `state:<value>` labels.
    "budget_exhausted": "a value of the `state` dimension, not a field of its own",
    "in_progress": "a bd issue STATUS, not campaign metadata",
    # A budget INPUT, read from the epic's `budget` blob by the agent that spends it and
    # never stamped on a record.
    "build_mem_mb": "a key inside the epic's `budget` blob, passed to run-contained.sh",
    # A directory name that happens to be snake_case.
    "node_modules": "a directory name in a launcher-resolution rule",
}


def report_json():
    spec = importlib.util.spec_from_file_location(
        "report_json", SKILL / "scripts/report-json.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rule_lines():
    """Every MUST/NOT/DEFAULT line in the package, with its source location."""
    files = sorted(SKILL.glob("references/**/*.md")) + [SKILL / "SKILL.md"]
    for path in files:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith(RULE_PREFIXES):
                yield path, lineno, line


def keys_named_by_rules():
    """Backticked snake_case identifiers on rule lines, mapped to where they are declared.

    snake_case is the filter that makes this tractable: every metadata key in this package
    is snake_case, while CLI flags are `--dashed`, labels are `sab-dashed`, and filenames
    carry an extension.
    """
    found = {}
    for path, lineno, line in rule_lines():
        for key in re.findall(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`", line):
            found.setdefault(key, f"{path.name}:{lineno}")
    return found


def readable_keys(mod):
    """Every key the report generator keeps or checks.

    The declared tables are not the whole answer. Some keys live inside a nested blob and
    are checked by a hand-written rule rather than a table entry -- `total_s` sits in the
    epic's `budget` and is checked directly -- so the source is scanned for a literal
    reference too. Without that, this sweep reports a key as orphaned while a check for it
    sits ten lines below the table, which is a false positive that trains the reader to
    add allowlist entries.
    """
    kept = {k for keys in mod.KEEP_META.values() for k in keys}
    kept |= set(mod.EPIC_KEEP)
    checked = set(mod.FINDING_REQUIRED) | set(mod.CRASH_REQUIRED) | set(mod.HARNESS_REQUIRED)
    checked |= {k for fields in mod.DECLARED_FIELDS.values() for k, _ in fields}
    checked |= {k for k, _ in mod.DECLARED_EPIC_FIELDS}

    # A key read out of a nested blob: `.get("<key>")` or `["<key>"]` in the source.
    source = (SKILL / "scripts/report-json.py").read_text()
    nested = set(re.findall(r'(?:\.get\(|\[)["\']([a-z][a-z0-9_]+)["\']', source))

    return kept | checked | nested


def test_every_metadata_key_a_rule_names_is_readable():
    mod = report_json()
    readable = readable_keys(mod)
    named = keys_named_by_rules()

    orphaned = {
        key: src for key, src in named.items()
        if key not in readable and key not in NOT_A_METADATA_FIELD
    }
    assert not orphaned, (
        "rule(s) name a metadata field that report-json.py neither keeps nor checks, so a "
        f"compliant stamp and a missing one produce the same report: {orphaned}. Add the "
        "key to KEEP_META or a required list, or -- only if it is genuinely not a bead "
        "field -- to NOT_A_METADATA_FIELD with the reason."
    )


def test_the_allowlist_has_no_stale_entries():
    # An entry that no rule names any more is dead weight, and dead weight in an allowlist
    # is where the next real orphan hides.
    named = set(keys_named_by_rules())
    mod = report_json()
    readable = readable_keys(mod)
    stale = sorted(k for k in NOT_A_METADATA_FIELD
                   if k not in named and k not in readable)
    assert not stale, (
        f"NOT_A_METADATA_FIELD entries no rule names any more: {stale}. Remove them; a "
        "stale allowlist entry silences a key nobody is asking about."
    )


def test_no_allowlist_entry_is_also_a_real_field():
    # The contradiction that would make the allowlist lie: a key both excused as "not a
    # field" and read as one. Whichever is right, the two cannot both be.
    mod = report_json()
    readable = readable_keys(mod)
    both = sorted(set(NOT_A_METADATA_FIELD) & readable)
    assert not both, (
        f"key(s) are excused as not-a-field AND read as one: {both}. If the report reads "
        "it, it is a field, so drop the allowlist entry."
    )


def test_every_allowlist_entry_states_a_reason():
    blank = sorted(k for k, why in NOT_A_METADATA_FIELD.items() if not why.strip())
    assert not blank, f"allowlist entries with no reason: {blank}"


def test_every_state_value_a_rule_names_has_a_reader():
    # The sweep above is blind here BY CONSTRUCTION, and this is the gap that let
    # `budget_exhausted` survive two passes. It is an enum VALUE of the `state` dimension,
    # so the key-presence check sees only `state` -- which is read -- and reports nothing,
    # while the handler for that particular value may not exist at all.
    #
    # Verified: removing the `budget_exhausted` branch from the register leaves the
    # key sweep entirely green. This test fails instead.
    source = (SKILL / "scripts/report-json.py").read_text()
    table = (SKILL / "references/beads-store.md").read_text()

    # Rows of the state table, keyed on the `state:<value>` column so no other table in the
    # file can match: | `pending` | `open` | `state:pending` | set by ... |
    values = set(re.findall(r"\|\s*`state:([a-z_]+)`\s*\|", table))
    assert values, "the state table in beads-store.md parsed to zero values"

    # A value needs a reader only when the rules say it means something the report must
    # state. `pending`, `claimed`, and `tiered` are lifecycle positions with no distinct
    # reporting consequence; the rest each name a coverage claim.
    LIFECYCLE_ONLY = {"pending", "claimed", "tiered", "reported", "minimized", "patched",
                      "executed"}
    unread = sorted(v for v in values - LIFECYCLE_ONLY if f'"{v}"' not in source)
    assert not unread, (
        f"state value(s) the report never reads: {unread}. Each names a distinct coverage "
        "claim -- an invalid run and an exhausted budget are not clean results -- so each "
        "needs a branch that states it, or a row in LIFECYCLE_ONLY saying it carries no "
        "reporting consequence."
    )


def test_the_sweep_actually_finds_keys():
    # A sweep whose regex silently stops matching passes forever. `dedup_key` and
    # `root_cause` are named by rules in this package and read by the report, so both must
    # appear on every run.
    named = keys_named_by_rules()
    assert len(named) >= 10, f"the sweep found only {len(named)} keys; the regex is broken"
    for canary in ("dedup_key", "root_cause"):
        assert canary in named, f"{canary} is named by a rule and the sweep missed it"
