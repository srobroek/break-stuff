#!/usr/bin/env python3
"""Delete a run's ephemeral paths. Dry-run by default; deletion is opt-in.

    run-teardown.py --run-root DIR [--apply] [--check-ceiling-mb N]
                    [--include-legacy-scratch] [--json]

Callable MID-CAMPAIGN, not only at the end. The correct response to a disk abort is stop,
report, teardown, verify headroom, resume -- so this has to work while a run is live.

WHAT IT WILL DELETE is decided by `run-layout.py classify`, never by a judgment call: a
path is deletable only if it classifies as `ephemeral`, which means it sits under
`<run-root>/ephemeral/` or under the run's host scratch. Anything else, including anything
that resolves outside the run root, is REFUSED. There is no `rm -rf` on a variable
anywhere here; `shutil.rmtree` is given an already-resolved path that has passed
`classify`.

A DENIED DELETION IS NOT RETRIED. Two deletions were denied by a permission layer
mid-campaign; the correct behaviour is to report them as outstanding teardown items and
stop touching them, not to reach the same bytes by another path. They are listed, the exit
code says so, and nothing is attempted twice.

ORPHANS from previous runs are reported. One campaign left ~1.0 GiB spread over five
differently-named `~/tmp/sabot-*` dirs that nothing could enumerate. Those legacy paths
sit outside any run root, so they are reported by default and deleted only under
`--include-legacy-scratch`.

--check-ceiling-mb is the mid-run watch that did not exist: nothing watched a growing
target dir, and the growth is what filled the host volume.

EXIT CODES: 0 clean, 2 usage, 3 the run root is not one, 4 a path was refused,
5 outstanding items remain (a denied deletion, or the ceiling is exceeded).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXIT_USAGE = 2
EXIT_PRECONDITION = 3
EXIT_REFUSED = 4
EXIT_OUTSTANDING = 5

_spec = importlib.util.spec_from_file_location("sabot_run_layout", HERE / "run-layout.py")
layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(layout)


def dir_bytes(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def ephemeral_targets(root: Path) -> list[Path]:
    """Top-level entries under the run's ephemeral roots, per-node dirs included.

    Enumerating the children rather than the parent keeps the parent dirs in place so a
    live campaign's writers do not lose their destination mid-run.
    """
    out: list[Path] = []
    for parent in (root / layout.EPHEMERAL_SEGMENT, layout.host_scratch(root)):
        if parent.is_dir():
            out.extend(sorted(parent.iterdir()))
    return out


def orphans(root: Path, home: Path | None = None) -> list[dict]:
    """Residue from other runs and from the pre-standard scratch locations."""
    home = home or Path.home()
    found: list[dict] = []
    runs_parent = root.parent
    if runs_parent.is_dir():
        for sibling in sorted(runs_parent.iterdir()):
            if sibling == root or not sibling.is_dir():
                continue
            eph = sibling / layout.EPHEMERAL_SEGMENT
            if eph.is_dir() and any(eph.iterdir()):
                found.append({"path": str(eph), "bytes": dir_bytes(eph), "kind": "other-run"})
    scratch_parent = home / layout.HOST_SCRATCH_PARENT
    if scratch_parent.is_dir():
        for sibling in sorted(scratch_parent.iterdir()):
            if sibling.resolve() == layout.host_scratch(root).resolve():
                continue
            found.append({"path": str(sibling), "bytes": dir_bytes(sibling),
                          "kind": "other-run-scratch"})
    for pattern in layout.LEGACY_HOST_SCRATCH_GLOBS:
        for hit in sorted(home.glob(pattern)):
            found.append({"path": str(hit), "bytes": dir_bytes(hit), "kind": "legacy-scratch"})
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run-teardown.py")
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; without it nothing is removed")
    ap.add_argument("--check-ceiling-mb", type=int,
                    help="report non-zero when ephemeral bytes exceed this")
    ap.add_argument("--include-legacy-scratch", action="store_true",
                    help="also delete ~/tmp/sabot-* and ~/.sabot/stage-* residue")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = layout.run_root(args.run_root)
    if not root.is_dir():
        print(f"run-teardown: no such run root: {root}", file=sys.stderr)
        return EXIT_PRECONDITION
    if not (root / layout.PREFLIGHT_NAME).exists() and not (root / "artifacts").is_dir():
        print(
            f"run-teardown: {root} has neither {layout.PREFLIGHT_NAME} nor artifacts/, so it "
            "is not a sabot run root. Refusing to treat an arbitrary directory as one.",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION

    planned: list[dict] = []
    refused: list[dict] = []
    for target in ephemeral_targets(root):
        try:
            kind = layout.classify(target, root)
        except ValueError as exc:
            refused.append({"path": str(target), "reason": str(exc)})
            continue
        if kind != "ephemeral":
            refused.append({"path": str(target), "reason": f"classifies as {kind}"})
            continue
        planned.append({"path": str(target), "bytes": dir_bytes(target)})

    legacy = [o for o in orphans(root) if o["kind"] == "legacy-scratch"]
    if args.include_legacy_scratch:
        # A legacy path lies OUTSIDE the run root by definition, so layout.classify() cannot
        # vouch for it. It therefore gets its own explicit gate rather than being appended
        # to `planned` unchecked: it must sit directly under $HOME, carry the sabot name
        # prefix, and not be a symlink pointing somewhere else entirely.
        home = Path.home().resolve()
        # Derived from the glob list rather than restated, so the gate cannot drift from
        # the patterns that produced the candidates.
        allowed = set()
        for pattern in layout.LEGACY_HOST_SCRATCH_GLOBS:
            head, _, tail = pattern.rpartition("/")
            allowed.add(((home / head).resolve() if head else home, tail.rstrip("*")))
        for o in legacy:
            candidate = Path(o["path"])
            resolved = candidate.resolve()
            ok = not candidate.is_symlink() and resolved != home and any(
                resolved.parent == parent and resolved.name.startswith(prefix) and prefix
                for parent, prefix in allowed
            )
            if not ok:
                refused.append({
                    "path": o["path"],
                    "reason": "legacy scratch must be a non-symlink path matching one of "
                              f"{list(layout.LEGACY_HOST_SCRATCH_GLOBS)} under {home}; "
                              "refusing to delete it",
                })
                continue
            planned.append({"path": o["path"], "bytes": o["bytes"], "legacy": True})

    if refused:
        for r in refused:
            print(f"run-teardown: REFUSED {r['path']}: {r['reason']}", file=sys.stderr)
        print(
            "run-teardown: refusing the whole teardown. A cleanup that can delete outside "
            "its own ephemeral paths is worse than no cleanup.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    freed = 0
    outstanding: list[dict] = []
    if args.apply:
        for item in planned:
            path = Path(item["path"])
            denied: list[str] = []

            def note(_func, target_path, exc_info):
                # Collected, never re-attempted: a permission layer that denied one path
                # will deny it again, and reaching the same bytes another way is exactly
                # the behaviour that must not happen.
                denied.append(f"{target_path}: {exc_info[1].__class__.__name__}")

            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path, onerror=note)
                else:
                    path.unlink(missing_ok=True)
            except OSError as exc:
                denied.append(f"{path}: {exc.__class__.__name__}")
            if denied or path.exists():
                outstanding.append({"path": str(path), "bytes": item["bytes"],
                                    "denied": denied or ["still present after deletion"]})
            else:
                freed += item["bytes"]

    remaining_mb = sum(dir_bytes(p) for p in ephemeral_targets(root)) // (1024 * 1024)
    ceiling_exceeded = (
        args.check_ceiling_mb is not None and remaining_mb > args.check_ceiling_mb
    )

    report = {
        "schema": "sabot-teardown/1",
        "run_root": str(root),
        "applied": args.apply,
        "planned": planned,
        "planned_mb": sum(p["bytes"] for p in planned) // (1024 * 1024),
        "freed_mb": freed // (1024 * 1024),
        "freed_bytes": freed,
        "remaining_ephemeral_mb": remaining_mb,
        "ceiling_mb": args.check_ceiling_mb,
        "ceiling_exceeded": ceiling_exceeded,
        "outstanding": outstanding,
        "orphans": orphans(root),
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        verb = "deleted" if args.apply else "would delete (dry-run; pass --apply)"
        print(f"run-teardown: {verb} {len(planned)} ephemeral path(s), "
              f"{report['planned_mb']} MiB")
        for p in planned:
            print(f"  {p['bytes'] // (1024 * 1024)} MiB  {p['path']}")
        if args.apply:
            print(f"run-teardown: freed {report['freed_mb']} MiB")
        for o in report["orphans"]:
            print(f"  ORPHAN {o['bytes'] // (1024 * 1024)} MiB  {o['path']}  ({o['kind']})")
        if legacy and not args.include_legacy_scratch:
            print("run-teardown: legacy scratch above is outside the run root and was not "
                  "touched; pass --include-legacy-scratch to remove it")
    # Warnings go to stderr in BOTH modes. A JSON caller that reads stdout and ignores the
    # exit code would otherwise see a teardown that looks complete while bytes remain --
    # the same silence that let a growing build tree reach 100% of the host volume.
    for o in outstanding:
        print(f"run-teardown: OUTSTANDING teardown item, not retried: {o['path']} "
              f"({'; '.join(o['denied'])})", file=sys.stderr)
    if ceiling_exceeded:
        print(f"run-teardown: ephemeral bytes {remaining_mb} MiB exceed the ceiling "
              f"{args.check_ceiling_mb} MiB; stop the run and free space before it "
              "reaches the disk", file=sys.stderr)

    if outstanding or ceiling_exceeded:
        return EXIT_OUTSTANDING
    return 0


if __name__ == "__main__":
    sys.exit(main())
