"""The formula lint. Every assertion here corresponds to a failure bd does not report.

The anchor sweep is the reason this file exists. A step whose entire `needs` list is
filtered out by a `condition` keeps only its parent-child edge, so it pours IMMEDIATELY
READY, in parallel with step 0. `bd cook` stays clean, `bd mol pour` prints success, and
`bd ready` simply returns a step that should not have been reachable. Three real cases
were found this way while authoring the campaign formula, one of them the opt-in step
that fires live payloads through real grants.
"""

import itertools
import re
import tomllib
from pathlib import Path

import pytest

FORMULA_DIR = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage/formulas"

# Every value each var can take. The sweep is exhaustive over this product, because the
# three anchor losses found by hand testing were each invisible to single-variable
# testing: two conditional steps in a row is the shape that hides them.
VAR_VALUES = {
    "scope_mode": ["full", "quick", "audit-only", "harness-only"],
    "autonomous": ["no", "yes"],
    "live_spawn": ["no", "yes"],
    "network_stage": ["no", "yes"],
    "remediation_route": ["report only", "harden", "ticket", "both"],
}

CONDITION_RE = re.compile(r"\{\{(\w+)\}\}\s*(==|!=)\s*(.+)")


def formulas():
    return sorted(FORMULA_DIR.glob("*.formula.toml"))


def load(path):
    with path.open("rb") as fh:
        return tomllib.load(fh)


def step_is_active(condition, values):
    """Evaluate a formula condition against one var assignment.

    `condition` reads POUR-TIME vars only. It never consults filesystem state, so a step
    gated on whether a tool exists cannot be expressed this way, and the formula must not
    pretend otherwise.
    """
    if not condition:
        return True
    match = CONDITION_RE.match(condition.strip())
    assert match, f"unparseable condition: {condition!r}"
    var, op, want = match.group(1), match.group(2), match.group(3).strip()
    assert var in VAR_VALUES, f"condition reads undeclared var {var!r}"
    have = values[var]
    return have == want if op == "==" else have != want


def combinations():
    keys = list(VAR_VALUES)
    for combo in itertools.product(*[VAR_VALUES[k] for k in keys]):
        yield dict(zip(keys, combo))


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_every_active_step_keeps_an_anchor_in_every_var_combination(path):
    # The one that matters. An active step whose every `needs` entry is filtered out is
    # reachable from the start of the run, and bd reports nothing.
    doc = load(path)
    steps = doc["steps"]
    conditions = {s["id"]: s.get("condition") for s in steps}

    losses = []
    for values in combinations():
        for step in steps:
            if not step_is_active(conditions.get(step["id"]), values):
                continue
            needs = step.get("needs") or []
            if not needs:
                continue
            if not any(step_is_active(conditions.get(n), values) for n in needs):
                losses.append((step["id"], dict(values)))

    assert not losses, (
        "step(s) lose every dependency under some var combination and would pour "
        f"immediately ready: {losses[:5]} ({len(losses)} total). Add an unconditional "
        "co-anchor to each step's `needs`."
    )


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_every_needs_entry_names_a_declared_step(path):
    doc = load(path)
    ids = {s["id"] for s in doc["steps"]}
    dangling = [(s["id"], n) for s in doc["steps"]
                for n in (s.get("needs") or []) if n not in ids]
    assert not dangling, f"`needs` naming steps that do not exist: {dangling}"


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_the_formula_key_matches_its_filename(path):
    # `bd mol pour` resolves by the `formula` key, and reports every mismatch as "not
    # found as formula or proto ID" -- the same message it gives for a syntax error.
    doc = load(path)
    assert doc["formula"] == path.name.removesuffix(".formula.toml")


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_no_step_is_typed_epic(path):
    # Fatal at pour: "epics can only block other epics". A plain task parents child beads
    # with hierarchical ids, so nothing needs the epic type.
    doc = load(path)
    bad = [s["id"] for s in doc["steps"] if s.get("type") == "epic"]
    assert not bad, f"epic-typed steps are fatal at pour: {bad}"


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_every_condition_reads_a_declared_var(path):
    # An unknown TOML key is dropped silently, and a condition on an undeclared var reads
    # as an empty string rather than raising.
    doc = load(path)
    declared = set(doc.get("vars", {}))
    for step in doc["steps"]:
        cond = step.get("condition")
        if not cond:
            continue
        match = CONDITION_RE.match(cond.strip())
        assert match, f"{step['id']}: unparseable condition {cond!r}"
        assert match.group(1) in declared, (
            f"{step['id']}: condition reads undeclared var {match.group(1)!r}"
        )


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_the_sweep_covers_every_declared_var(path):
    # A var absent from VAR_VALUES is a var the anchor sweep never varies, so a whole
    # class of anchor loss would go unswept while the test still passed.
    doc = load(path)
    declared = set(doc.get("vars", {}))
    swept = set(VAR_VALUES)
    # `run_id` and `target` are free-form identifiers; no step conditions on them.
    unswept = declared - swept - {"run_id", "target"}
    assert not unswept, f"declared vars the anchor sweep never varies: {sorted(unswept)}"


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_every_gate_step_is_a_table_and_names_a_type(path):
    # `[steps.gate]` must be a TOML table; a string is dropped silently and the gate
    # simply never exists.
    doc = load(path)
    for step in doc["steps"]:
        gate = step.get("gate")
        if gate is None:
            continue
        assert isinstance(gate, dict), f"{step['id']}: gate must be a table"
        assert gate.get("type") in {"human", "timer", "gh:run", "gh:pr", "bead"}, (
            f"{step['id']}: unknown gate type {gate.get('type')!r}"
        )


@pytest.mark.parametrize("path", formulas(), ids=lambda p: p.name)
def test_every_gate_has_a_wiring_row_in_the_pour_script(path):
    # A poured `[steps.gate]` bead attaches to the molecule root by parent-child ALONE,
    # with no blocking edge, so the approval blocks nothing (verified on bd 1.2.2).
    # `scripts/pour-campaign.sh` adds the missing edges, and it can only wire a gate it
    # has a row for -- so a gate added to the formula and not to the script is an
    # approval that silently does not gate.
    doc = load(path)
    gates = [s for s in doc["steps"] if s.get("gate")]
    if not gates:
        pytest.skip("no gates in this formula")
    script = (FORMULA_DIR.parent / "scripts/pour-campaign.sh").read_text()
    for step in gates:
        # The script's GATE_TARGETS rows key on a leading "step N gate" fragment, which is
        # what `bd list` can match a poured title against.
        match = re.match(r"(step \d+ gate)", step["title"])
        assert match, (
            f"{step['id']}: a gate step's title must start with 'step N gate' so the "
            f"pour script can match the poured bead; got {step['title']!r}"
        )
        assert match.group(1) in script, (
            f"{step['id']}: no wiring row in pour-campaign.sh for {match.group(1)!r}; "
            "the gate would pour inert"
        )


def _report_json():
    """Load report-json.py as a module. It is a script, not a package member."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / ".apm/skills/sabotage/scripts/report-json.py"
    spec = importlib.util.spec_from_file_location("report_json", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_declared_field_is_also_kept_by_its_bucket():
    # The failure this prevents: a field is declared mandatory, an agent stamps it, and the
    # renderer drops it because its bucket's keep-list never named it. Thirteen fields were
    # in that state at once -- stamped correctly and discarded one function later -- and
    # each looked from the report like an agent that had ignored a MUST.
    mod = _report_json()
    dropped = [
        (bucket, key, src)
        for bucket, fields in mod.DECLARED_FIELDS.items()
        for key, src in fields
        if key not in set(mod.KEEP_META.get(bucket, []))
    ]
    assert not dropped, (
        f"declared-mandatory field(s) not in their bucket's KEEP_META: {dropped}. "
        "A field that is required and then dropped cannot be reported either way."
    )


def test_every_declared_epic_field_is_kept():
    mod = _report_json()
    dropped = [(k, src) for k, src in mod.DECLARED_EPIC_FIELDS if k not in mod.EPIC_KEEP]
    assert not dropped, f"declared epic field(s) missing from EPIC_KEEP: {dropped}"


def test_every_declared_field_names_a_real_bucket():
    mod = _report_json()
    buckets = {b for _, b in mod.LABEL_BUCKET}
    unknown = [b for b in mod.DECLARED_FIELDS if b not in buckets]
    assert not unknown, f"DECLARED_FIELDS names bucket(s) with no label mapping: {unknown}"
