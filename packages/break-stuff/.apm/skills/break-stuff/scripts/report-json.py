#!/usr/bin/env python3
"""Export one break-stuff campaign from beads as a structured report JSON.

Runs `bd export` (which emits every issue with its metadata, labels, dependency
edges, and comment bodies), keeps only the beads for the given run_id, drops the
fields a report never uses (owner, timestamps, priority, created_by, counts), and
reshapes each bead into the schema the report generator and a machine reader consume.

Wisps ARE beads here (a task bead with a brk-* label), so the export already holds
them; nothing separate is persisted. The correlation edges (discovered-from,
caused-by, relates-to) ride on each bead's `dependencies`, so a finding keeps its
link to the harness, crash, or chain it came from.

Usage:
  report-json.py --run-id run-<id> [--bd bd] [-o out.json]

Emits to stdout (or -o) a single JSON object:
  {
    "run_id", "epic": {...}, "surfaces": [...], "harnesses": [...],
    "crashes": [...], "findings": [...], "coverage": [...],
    "summary": { "by_tier": {...}, "by_impact": {...}, "gaps": [...] }
  }

Exit codes: 0 ok; 2 usage; 3 bd missing or export failed; 4 no beads for run_id.
"""

import argparse
import json
import shutil
import subprocess
import sys


# Which brk-* label sorts a bead into which bucket. Order matters: the first match
# wins, so brk-surface (inherited by every child) is checked last.
LABEL_BUCKET = [
    ("brk-harness", "harnesses"),
    ("brk-crash", "crashes"),
    ("brk-finding", "findings"),
    ("brk-coverage", "coverage"),
    ("brk-surface", "surfaces"),
]

# Metadata fields kept per bucket. Everything else in metadata is dropped so the
# report schema stays stable even when a bead carries extra stamps.
KEEP_META = {
    "surfaces": ["surface", "scope"],
    "harnesses": ["entry_point", "runner", "harness_path", "input_shape"],
    "crashes": ["input_path", "stack_hash"],
    "findings": ["tier", "by", "source", "impact", "locus", "path", "cwe", "repro"],
    "coverage": ["scanners_run", "scanners_skipped", "harnesses_run", "harnesses_total"],
}


def run_export(bd):
    try:
        out = subprocess.run(
            [bd, "export", "--all"],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError:
        sys.exit(f"report-json: {bd} not on PATH")  # exit 1 via message
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr or "")
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


def bucket_of(labels):
    labels = set(labels or [])
    for label, bucket in LABEL_BUCKET:
        if label in labels:
            return bucket
    return None


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
    (bd ids are hierarchical: a child of `brk-x.1` is `brk-x.1.n`), so parentage is
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
        bucket = bucket_of(bead.get("labels"))
        if not bucket:
            continue
        report[bucket].append(shape(bead, bucket))
        bead_run = parse_meta(bead).get("run_id")
        if bead_run != run_id:
            report["stamping_gaps"].append(
                {"id": bid, "bucket": bucket, "run_id": bead_run}
            )

    # Summary the report headline reads without re-walking the findings.
    by_tier, by_impact = {}, {}
    for f in report["findings"]:
        by_tier[f.get("tier", "UNTIERED")] = by_tier.get(f.get("tier", "UNTIERED"), 0) + 1
        if f.get("impact"):
            by_impact[f["impact"]] = by_impact.get(f["impact"], 0) + 1
    gaps = [c["id"] for c in report["coverage"]
            if c.get("harnesses_run") != c.get("harnesses_total")]
    report["summary"] = {
        "by_tier": by_tier,
        "by_impact": by_impact,
        "coverage_gaps": gaps,
        "stamping_gaps": len(report["stamping_gaps"]),
    }

    out = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out + "\n")
    else:
        print(out)


if __name__ == "__main__":
    main()
