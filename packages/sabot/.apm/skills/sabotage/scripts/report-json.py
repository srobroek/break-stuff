#!/usr/bin/env python3
"""Export one sabot campaign from beads as a structured report JSON.

Runs `bd export` (which emits every issue with its metadata, labels, dependency
edges, and comment bodies), keeps only the beads for the given run_id, drops the
fields a report never uses (owner, timestamps, priority, created_by, counts), and
reshapes each bead into the schema the report generator and a machine reader consume.

Wisps ARE beads here (a task bead with a sab-* label), so the export already holds
them; nothing separate is persisted. The correlation edges (discovered-from,
caused-by, relates-to) ride on each bead's `dependencies`, so a finding keeps its
link to the harness, crash, or chain it came from.

Usage:
  report-json.py --run-id run-<id> [--bd bd] [-o out.json]

THE BEAD METADATA BLOB IS THE REPORT. This is a renderer over the graph, not a prose
assembler: ranking, grouping by root cause, and dedup are mechanical here because doing
them by hand does not scale and did not happen. One run produced ~251 findings with no
ranking or dedup at all, and 224 loci were collapsed onto a single boundary by hand.

Emits to stdout (or -o) a single JSON object:
  {
    "run_id", "threat", "epic": {...}, "surfaces": [...], "harnesses": [...],
    "crashes": [...], "findings": [...], "coverage": [...],
    "groups": [...],              # dedup_key collapse, ranked, one tier per group
    "systemic_patterns": [...],   # root_cause rollup, above the findings
    "not_executed": [...],        # one line per unexercised dimension, with its reason
    "stamping_gaps": [...],
    "summary": {"by_tier", "by_impact", "counts", "coverage_gaps",
                "surfaces_without_a_coverage_record", ...}
  }

`summary.counts` carries groups, instances, and wisps plus a `balances` flag: every
instance belongs to exactly one group, so a count table that has to add up is the check.

Exit codes: 0 ok; 2 usage; 3 bd missing, export failed, or the export was EMPTY (which is
the wrong cwd or an empty store, not a run without findings); 4 no beads for run_id;
5 the count table does not balance, so a finding was dropped between graph and report.
"""

import argparse
import json
import shutil
import subprocess
import sys


# Which sab-* label sorts a bead into which bucket. Order matters: the first match
# wins, so sab-surface (inherited by every child) is checked last.
LABEL_BUCKET = [
    ("sab-harness", "harnesses"),
    ("sab-crash", "crashes"),
    ("sab-finding", "findings"),
    ("sab-coverage", "coverage"),
    ("sab-surface", "surfaces"),
]

# Metadata fields kept per bucket. Everything else in metadata is dropped so the
# report schema stays stable even when a bead carries extra stamps.
KEEP_META = {
    "surfaces": ["surface", "scope"],
    "harnesses": ["entry_point", "runner", "harness_path", "input_shape"],
    # The triager's own brief prescribes nine keys; keeping two of them dropped the
    # minimization entirely. Measured: a triager minimized 6 crashes to 65/185/71/81/2880/3
    # bytes, wrote the files to disk, and stamped them under its own invented names
    # (`min_input`, `min_bytes`, `dedup`, `triage_class`). Every crash record in the report
    # rendered blank, and nothing said the seven files existed.
    "crashes": ["input_path", "stack_hash", "state", "kind", "minimized_path",
                "minimized_bytes", "original_path", "repro_cmd", "repro_rc", "dedup_key",
                "duplicate_of", "class_closed_by"],
    "findings": ["tier", "by", "source", "impact", "locus", "path", "cwe", "repro",
                 "surface", "node", "evidence", "control_passed", "dedup_key",
                 "root_cause", "not_executed_reason"],
    # entry_points_* is the ratio a harness count cannot express: "13 of 13 harnesses ran"
    # beside 706 entry points is a 2% surface reported as complete. Measured: one node
    # enumerated 199 Tauri handlers and executed 0, and with only the harness counts kept
    # here that number reached no part of the report.
    "coverage": ["scanners_run", "scanners_skipped", "harnesses_run", "harnesses_total",
                 "entry_points_total", "entry_points_executed", "surface"],
}

# Every one of these must be PRESENT on a finding wisp, with an explicit null where it
# does not apply. A missing key and a deliberate null read identically to a renderer, so
# an omission becomes a blank column that looks like a considered "not applicable".
FINDING_REQUIRED = [
    "tier", "by", "source", "impact", "locus", "surface", "node", "evidence",
    "control_passed", "dedup_key", "root_cause", "not_executed_reason",
]

# The same rule for a crash wisp, which is the one bucket whose whole value is a file on
# disk. A crash with no path to its input is unreproducible whatever its title claims, and
# a triager that stamped under non-canonical names produced exactly that shape: six wisps,
# seven minimized files present, nothing in the report reaching them.
CRASH_REQUIRED = ["state", "kind", "minimized_path", "repro_cmd", "repro_rc", "dedup_key"]

# Ranking, in order. Five keys, because a run producing hundreds of findings is read
# top-down and then abandoned; the reader's attention is the scarce resource.
TIER_RANK = {"PROVEN": 0, "REACHABLE": 1, "HARDENING": 2, "REFUTED": 4}
IMPACT_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
UNTIERED_RANK = 3          # between HARDENING and REFUTED: unjudged, not dismissed
UNRANKED_IMPACT = 4


def run_export(bd):
    """`bd export --all` from the repo root.

    An EMPTY result and a FAILED query are distinguished deliberately. `bd` discovers its
    store relative to cwd, and on a query `--labels` (plural) is accepted and silently
    returns nothing, which once made a whole wisp set read as "no work exists". So an
    empty export is reported as an empty export, never as an absence of findings.
    """
    try:
        out = subprocess.run(
            [bd, "export", "--all"],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError:
        sys.exit(f"report-json: {bd} not on PATH")  # exit 1 via message
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr or "")
        sys.stderr.write(
            f"report-json: `{bd} export --all` failed. Run it from the repo root: the "
            "store is discovered relative to cwd, so a bd that answers in $HOME and not "
            "here is the same as no bd at all.\n"
        )
        sys.exit(3)
    if not out.strip():
        sys.stderr.write(
            f"report-json: `{bd} export --all` returned NOTHING. That is an empty store "
            "or the wrong cwd, not a run with no findings. Refusing to render an empty "
            "report that would read as a clean audit.\n"
        )
        sys.exit(3)
    return out


def parse_meta(bead):
    m = bead.get("metadata")
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            m = {}
    return m or {}


def edges(bead):
    """Non-parent dependency edges, reshaped to (type, to). parent-child is the tree
    and is represented by `parent`, so it is not repeated as a correlation edge."""
    out = []
    for d in bead.get("dependencies") or []:
        etype = d.get("type", "")
        if etype == "parent-child":
            continue
        out.append({"type": etype, "to": d.get("depends_on_id")})
    return out


def parent(bead):
    for d in bead.get("dependencies") or []:
        if d.get("type") == "parent-child":
            return d.get("depends_on_id")
    return None


def comments(bead):
    return [c.get("text", "") for c in bead.get("comments") or []]


# When an agent drops a wisp's own label, only the inherited `sab-surface` remains.
# The metadata shape still identifies the kind, so classify by it as a fallback and
# let the caller flag the mislabel -- the same defend-in-depth as the run_id gap.
META_SIGNATURE = [
    ("harnesses", ("entry_point", "harness_path")),
    ("coverage", ("harnesses_total", "scanners_run")),
    ("crashes", ("input_path", "stack_hash")),
    ("findings", ("tier", "locus")),
]


def bucket_of(bead):
    labels = set(bead.get("labels") or [])
    own = [b for lbl, b in LABEL_BUCKET if lbl in labels and lbl != "sab-surface"]
    if own:
        return own[0], False  # a real own-label match
    meta = parse_meta(bead)
    for bucket, keys in META_SIGNATURE:
        if any(k in meta for k in keys):
            return bucket, True  # inferred from metadata: the own label was dropped
    if "sab-surface" in labels:
        return "surfaces", False
    return None, False


def shape(bead, bucket):
    meta = parse_meta(bead)
    kept = {k: meta[k] for k in KEEP_META.get(bucket, []) if k in meta}
    rec = {
        "id": bead.get("id"),
        "title": bead.get("title"),
        "status": bead.get("status"),
        "parent": parent(bead),
        **kept,
    }
    ce = edges(bead)
    if ce:
        rec["edges"] = ce
    cm = comments(bead)
    if cm:
        rec["notes"] = cm
    return rec


def parent_of(bead):
    """The parent-child dependency target, else None. Falls back to the id prefix
    (bd ids are hierarchical: a child of `sab-x.1` is `sab-x.1.n`), so parentage is
    recoverable even from a bead whose edge did not serialize."""
    for d in bead.get("dependencies") or []:
        if d.get("type") == "parent-child" and d.get("depends_on_id"):
            return d["depends_on_id"]
    bid = bead.get("id") or ""
    return bid.rsplit(".", 1)[0] if "." in bid else None


def resolve_epic(beads, epic_id, run_id):
    """Find the epic by id, or by run_id when only that was given."""
    for b in beads:
        if epic_id and b.get("id") == epic_id:
            return b
    if run_id:
        for b in beads:
            if b.get("issue_type") == "epic" and parse_meta(b).get("run_id") == run_id:
                return b
    return None


def descendants(beads, epic_id):
    """Every bead under the epic, by walking parent-child edges (with id-prefix
    fallback). Structure is the scope: a finding belongs to the run because it
    descends from the epic, not because an agent remembered to stamp run_id."""
    children = {}
    for b in beads:
        p = parent_of(b)
        if p:
            children.setdefault(p, []).append(b.get("id"))
    by_id = {b.get("id"): b for b in beads}
    out, stack = {}, [epic_id]
    while stack:
        node = stack.pop()
        for cid in children.get(node, []):
            if cid not in out and cid in by_id:
                out[cid] = by_id[cid]
                stack.append(cid)
    return out


def threat_terms(threat):
    """The epic's stamped threat, split into comparable terms.

    The threat has been stamped on the epic since the interview and has never once been
    used for ordering, so a run aimed at one fear reported its findings in bead order.
    """
    if not threat:
        return []
    out = []
    for term in str(threat).replace("/", " ").replace(",", " ").split():
        term = term.strip().lower()
        if len(term) > 3:
            out.append(term)
    return out


def threat_aligned(finding, terms):
    """Whether a finding matches the user's stated threat. Cheap and textual on purpose:
    a CWE-to-threat ontology would be a guess dressed as a mapping."""
    if not terms:
        return False
    haystack = " ".join(
        str(finding.get(k) or "").lower()
        for k in ("title", "cwe", "root_cause", "surface", "locus", "path")
    )
    return any(term in haystack for term in terms)


def dedup_key_of(finding):
    """The wisp's own key, or a derived fallback.

    Derived is recorded as derived: the finder knows the vulnerability class and a later
    pass reconstructing it from a one-line title is guessing, so a group built on a
    fallback key must be visible as such rather than presented as the finder's judgment.
    """
    key = finding.get("dedup_key")
    if isinstance(key, str) and key.strip():
        return key.strip().lower(), False
    derived = ":".join(
        str(finding.get(k) or "?").strip().lower()
        for k in ("surface", "locus", "cwe")
    )
    return derived, True


def group_findings(findings, threat):
    """Collapse instances onto dedup_key, then onto root_cause.

    224 loci were collapsed onto a single boundary BY HAND in one run. Both collapses are
    now data: a dedup_key on more than one wisp is the same finding found twice, which is
    independent confirmation rather than two findings, and a shared root_cause is one
    defect with many loci.
    """
    terms = threat_terms(threat)
    by_key = {}
    for f in findings:
        key, derived = dedup_key_of(f)
        slot = by_key.setdefault(key, {"instances": [], "derived_key": derived})
        slot["instances"].append(f)
        slot["derived_key"] = slot["derived_key"] or derived

    groups = []
    for key, slot in by_key.items():
        instances = sorted(
            slot["instances"],
            key=lambda f: (
                TIER_RANK.get(f.get("tier"), UNTIERED_RANK),
                IMPACT_RANK.get(f.get("impact"), UNRANKED_IMPACT),
                str(f.get("locus") or ""),
                str(f.get("id") or ""),
            ),
        )
        rep = instances[0]
        tiers = sorted({i.get("tier") or "UNTIERED" for i in instances})
        groups.append({
            "dedup_key": key,
            "dedup_key_derived": slot["derived_key"],
            "representative": rep.get("id"),
            "title": rep.get("title"),
            # One tier per group: the strongest evidence any instance carries, because a
            # group reported at its weakest instance understates what was proven.
            "tier": min(tiers, key=lambda t: TIER_RANK.get(t, UNTIERED_RANK)),
            "tiers_seen": tiers,
            "impact": rep.get("impact"),
            "surface": rep.get("surface"),
            "root_cause": rep.get("root_cause"),
            "locus": rep.get("locus"),
            "cwe": rep.get("cwe"),
            "evidence": rep.get("evidence"),
            "instance_count": len(instances),
            "instances": [i.get("id") for i in instances],
            "loci": sorted({str(i.get("locus")) for i in instances if i.get("locus")}),
            "confirmed_independently": len(instances) > 1,
            "threat_aligned": any(threat_aligned(i, terms) for i in instances),
        })

    groups.sort(key=lambda g: (
        TIER_RANK.get(g["tier"], UNTIERED_RANK),          # 1 evidence tier
        IMPACT_RANK.get(g["impact"], UNRANKED_IMPACT),     # 2 impact
        0 if g["threat_aligned"] else 1,                   # 3 the epic's stamped threat
        -g["instance_count"],                              # 4 how many loci it covers
        str(g["locus"] or ""),                             # 5 locus, for a stable order
    ))
    for i, g in enumerate(groups, 1):
        g["rank"] = i
        g["group_role"] = "representative"
    return groups


def systemic_patterns(groups):
    """Roll groups up by root_cause. The most valuable conclusion of one whole campaign
    -- eight independent built-but-never-wired instances -- was produced by no step at
    all, so the rollup is a section rather than a reader's inference."""
    by_cause = {}
    for g in groups:
        cause = (g.get("root_cause") or "").strip()
        if not cause:
            continue
        slot = by_cause.setdefault(cause, {
            "root_cause": cause, "groups": [], "instance_count": 0,
            "surfaces": set(), "tiers": set(),
        })
        slot["groups"].append(g["representative"])
        slot["instance_count"] += g["instance_count"]
        if g.get("surface"):
            slot["surfaces"].add(g["surface"])
        slot["tiers"].add(g["tier"])
    out = []
    for slot in by_cause.values():
        out.append({
            "root_cause": slot["root_cause"],
            "group_count": len(slot["groups"]),
            "instance_count": slot["instance_count"],
            "groups": slot["groups"],
            "surfaces": sorted(slot["surfaces"]),
            "tier": min(slot["tiers"], key=lambda t: TIER_RANK.get(t, UNTIERED_RANK)),
            # A defect appearing on more than one surface is a systemic pattern rather
            # than a local bug, and that is the distinction a reader acts on.
            "cross_surface": len(slot["surfaces"]) > 1,
        })
    out.sort(key=lambda r: (-r["instance_count"], -r["group_count"], r["root_cause"]))
    return out


def not_executed_register(findings, coverage, surfaces):
    """One line per unexercised dimension, with its reason.

    `not_executed_reason` is a first-class field rather than an absence, because a
    scanner that failed to run was repeatedly recorded as "0 findings" -- the same bytes
    as a clean result.
    """
    register = []
    for f in findings:
        reason = f.get("not_executed_reason")
        if isinstance(reason, str) and reason.strip():
            register.append({"kind": "finding-placeholder", "id": f.get("id"),
                             "surface": f.get("surface"), "locus": f.get("locus"),
                             "reason": reason.strip()})
        elif f.get("control_passed") is False:
            # A control that did not fire means the locus is UNTESTED: the harness proved
            # nothing about the code, only that it ran.
            register.append({
                "kind": "control-failed", "id": f.get("id"),
                "surface": f.get("surface"), "locus": f.get("locus"),
                "reason": "the benign control did not pass, so this locus is UNTESTED "
                          "and the finding cannot be trusted either way",
            })
    for c in coverage:
        # `scanners_skipped` is a list of NAMES. A count in its place is not a smaller
        # version of the field: "9 skipped" identifies none of the nine, and nothing
        # downstream can say which invariant went unchecked. Measured: 21 of 22 coverage
        # wisps in one campaign stamped both scanner fields as integers and one as a comma
        # string, and iterating an int raised TypeError -- the whole report died rather
        # than naming the wisp. Register the mis-stamp instead of crashing on it, and
        # never silently coerce it into a name.
        skipped = c.get("scanners_skipped")
        if isinstance(skipped, (int, float)) or isinstance(skipped, str):
            register.append({
                "kind": "scanner-skip-list-not-stamped", "id": c.get("id"),
                "surface": c.get("surface"), "locus": None,
                "reason": f"scanners_skipped is {skipped!r}, not a list of scanner names, "
                          "so no skipped scanner can be named and no invariant traced to "
                          "the tool that went unrun",
            })
            skipped = []
        for name in (skipped or []):
            register.append({"kind": "scanner-skipped", "id": c.get("id"),
                             "surface": c.get("surface"), "locus": None,
                             "reason": str(name)})
        run, total = c.get("harnesses_run"), c.get("harnesses_total")
        if isinstance(run, int) and isinstance(total, int) and run < total:
            register.append({
                "kind": "harnesses-unrun", "id": c.get("id"),
                "surface": c.get("surface"), "locus": None,
                "reason": f"{total - run} of {total} authored harness(es) never executed",
            })
        # A harness ratio measures the harnesses, not the surface. "13 of 13 ran" beside
        # 706 entry points is 2% coverage reported as complete, and one node enumerated
        # 199 handlers and executed 0 of them.
        ep_run, ep_total = c.get("entry_points_executed"), c.get("entry_points_total")
        if isinstance(ep_run, int) and isinstance(ep_total, int) and ep_run < ep_total:
            register.append({
                "kind": "entry-points-unexecuted", "id": c.get("id"),
                "surface": c.get("surface"), "locus": None,
                "reason": f"{ep_total - ep_run} of {ep_total} entry point(s) on this "
                          "surface were never executed, whatever the harness count says",
            })
    covered = {c.get("surface") for c in coverage if c.get("surface")}
    for s in surfaces:
        name = s.get("surface")
        if name and name not in covered:
            # The fail-open this closes: gaps used to be derived only from the coverage
            # records that EXIST, so a surface that filed none produced an empty gap list
            # and a clean exit.
            register.append({
                "kind": "no-coverage-record", "id": s.get("id"), "surface": name,
                "locus": None,
                "reason": "the surface node filed no sab-coverage record, so nothing "
                          "states what ran on it. Absence of a record is not coverage.",
            })
    register.sort(key=lambda r: (r["kind"], str(r["surface"]), str(r["id"])))
    return register


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epic", help="the run epic bead id (preferred)")
    ap.add_argument("--run-id", help="the run_id metadata (resolves the epic when --epic is absent)")
    ap.add_argument("--bd", default="bd")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    if not args.epic and not args.run_id:
        sys.exit("report-json: --epic or --run-id is required")
    if not shutil.which(args.bd):
        sys.exit(3)

    beads = []
    for line in run_export(args.bd).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            beads.append(json.loads(line))
        except ValueError:
            continue

    epic = resolve_epic(beads, args.epic, args.run_id)
    if epic is None:
        sys.exit(4)  # epic not found
    epic_id = epic.get("id")
    run_id = parse_meta(epic).get("run_id")

    report = {
        "run_id": run_id,
        "epic_id": epic_id,
        "epic": None,
        "surfaces": [], "harnesses": [], "crashes": [],
        "findings": [], "coverage": [],
        "stamping_gaps": [],
    }
    report["epic"] = shape(epic, "epic")
    report["epic"].update(
        {k: parse_meta(epic).get(k)
         for k in ("target", "base_sha", "budget", "artifacts")
         if k in parse_meta(epic)}
    )

    # Select by descent from the epic, not by a run_id stamp: a properly parented
    # finding is never silently dropped, even when its run_id was not stamped.
    for bid, bead in descendants(beads, epic_id).items():
        bucket, mislabeled = bucket_of(bead)
        if not bucket:
            continue
        report[bucket].append(shape(bead, bucket))
        bead_run = parse_meta(bead).get("run_id")
        if bead_run != run_id:
            report["stamping_gaps"].append(
                {"id": bid, "bucket": bucket, "run_id": bead_run, "issue": "missing run_id"}
            )
        if mislabeled:
            want = {"harnesses": "sab-harness", "crashes": "sab-crash",
                    "findings": "sab-finding", "coverage": "sab-coverage"}.get(bucket, bucket)
            report["stamping_gaps"].append(
                {"id": bid, "bucket": bucket, "issue": f"classified as {bucket} by metadata; {want} label missing"}
            )

    # A field missing from a finding wisp is a blank column the report cannot fill, and
    # it is indistinguishable from a deliberate null unless it is named here.
    for f in report["findings"]:
        missing = [k for k in FINDING_REQUIRED if k not in f]
        if missing:
            report["stamping_gaps"].append({
                "id": f.get("id"), "bucket": "findings",
                "issue": f"finding wisp missing required field(s): {missing}. Use an "
                         "explicit null where a field does not apply; an omission reads "
                         "as a considered 'not applicable'.",
            })

    # A crash whose input the report cannot name is unreproducible, and it renders exactly
    # like a crash that was never minimized. Named rather than blanked, so a triager that
    # stamped under its own key names is visible instead of silently discarded.
    for c in report["crashes"]:
        missing = [k for k in CRASH_REQUIRED if k not in c]
        if missing:
            report["stamping_gaps"].append({
                "id": c.get("id"), "bucket": "crashes",
                "issue": f"crash wisp missing required field(s): {missing}. The minimized "
                         "input may well exist on disk; without these keys no part of this "
                         "report can reach it, and the crash reads as untriaged.",
            })

    threat = parse_meta(epic).get("threat")
    report["threat"] = threat
    report["groups"] = group_findings(report["findings"], threat)
    report["systemic_patterns"] = systemic_patterns(report["groups"])
    report["not_executed"] = not_executed_register(
        report["findings"], report["coverage"], report["surfaces"]
    )

    by_tier, by_impact = {}, {}
    for f in report["findings"]:
        by_tier[f.get("tier", "UNTIERED")] = by_tier.get(f.get("tier", "UNTIERED"), 0) + 1
        if f.get("impact"):
            by_impact[f["impact"]] = by_impact.get(f["impact"], 0) + 1

    # Coverage gaps come from a set DIFFERENCE against the detected surfaces, not from a
    # walk of the records that happen to exist: a surface that filed no coverage record
    # used to produce an empty gap list and exit 0.
    covered = {c.get("surface") for c in report["coverage"] if c.get("surface")}
    surface_names = {s.get("surface") for s in report["surfaces"] if s.get("surface")}
    gaps = [c["id"] for c in report["coverage"]
            if c.get("harnesses_run") != c.get("harnesses_total")]
    missing_records = sorted(surface_names - covered)

    # Three counts that must balance. Derived, never asserted: a table that has to add up
    # is the check, and a hand-written count cannot disagree with itself.
    instance_count = len(report["findings"])
    grouped_instances = sum(g["instance_count"] for g in report["groups"])
    report["summary"] = {
        "by_tier": by_tier,
        "by_impact": by_impact,
        "counts": {
            "groups": len(report["groups"]),
            "instances": instance_count,
            "wisps": len(report["findings"]) + len(report["crashes"])
                     + len(report["harnesses"]) + len(report["coverage"]),
            "grouped_instances": grouped_instances,
            "balances": grouped_instances == instance_count,
            "note": "every instance belongs to exactly one group, so grouped_instances "
                    "must equal instances. A mismatch means a finding was dropped "
                    "between the graph and the report.",
        },
        # A group built on a key this script derived is the finder's judgment reconstructed
        # from a title, and it reads in the report exactly like a stamped one. Measured: a
        # 383-finding campaign stamped `dedup_key` on none of them, so every group was
        # derived and the challenger's prescribed `uniq -d` dedup returned nothing over
        # seven real cross-surface duplicate loci.
        "groups_on_a_derived_dedup_key": sum(
            1 for g in report["groups"] if g["dedup_key_derived"]
        ),
        "coverage_gaps": gaps,
        "surfaces_without_a_coverage_record": missing_records,
        "not_executed_count": len(report["not_executed"]),
        "systemic_pattern_count": len(report["systemic_patterns"]),
        "stamping_gaps": len(report["stamping_gaps"]),
        "threat_aligned_groups": sum(1 for g in report["groups"] if g["threat_aligned"]),
    }

    out = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out + "\n")
    else:
        print(out)

    if not report["summary"]["counts"]["balances"]:
        sys.stderr.write(
            "report-json: the count table does not balance: "
            f"{grouped_instances} grouped instance(s) against {instance_count} "
            "finding(s). A finding was dropped between the graph and the report; the "
            "report above understates the run.\n"
        )
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
