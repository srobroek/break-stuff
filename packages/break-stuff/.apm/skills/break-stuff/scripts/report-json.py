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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--bd", default="bd")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    if not shutil.which(args.bd):
        sys.exit(3)

    raw = run_export(args.bd)
    report = {
        "run_id": args.run_id,
        "epic": None,
        "surfaces": [], "harnesses": [], "crashes": [],
        "findings": [], "coverage": [],
    }

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            bead = json.loads(line)
        except ValueError:
            continue
        if parse_meta(bead).get("run_id") != args.run_id:
            continue
        if bead.get("issue_type") == "epic":
            report["epic"] = shape(bead, "epic")
            report["epic"].update(
                {k: parse_meta(bead).get(k)
                 for k in ("target", "base_sha", "budget", "artifacts")
                 if k in parse_meta(bead)}
            )
            continue
        bucket = bucket_of(bead.get("labels"))
        if bucket:
            report[bucket].append(shape(bead, bucket))

    total = sum(len(report[b]) for b in ("surfaces", "harnesses", "crashes", "findings", "coverage"))
    if report["epic"] is None and total == 0:
        sys.exit(4)  # no beads for this run_id

    # Summary the report headline reads without re-walking the findings.
    by_tier, by_impact = {}, {}
    for f in report["findings"]:
        by_tier[f.get("tier", "UNTIERED")] = by_tier.get(f.get("tier", "UNTIERED"), 0) + 1
        if f.get("impact"):
            by_impact[f["impact"]] = by_impact.get(f["impact"], 0) + 1
    gaps = [c["id"] for c in report["coverage"]
            if c.get("harnesses_run") != c.get("harnesses_total")]
    report["summary"] = {"by_tier": by_tier, "by_impact": by_impact, "coverage_gaps": gaps}

    out = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out + "\n")
    else:
        print(out)


if __name__ == "__main__":
    main()
