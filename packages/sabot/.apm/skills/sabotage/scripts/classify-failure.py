#!/usr/bin/env python3
"""One verdict for a failed contained run: resource fault, not-executed, or target defect.

    classify-failure.py --rc N [--log FILE] [--mem-mb N] [--host-mem-mb N]
                        [--attempt N] [--json]

A resource fault is an INVALID run. It is not a finding and it is not a target defect.
A campaign lost a whole pass to getting this wrong once: `ld` was SIGKILLed by the 2 GiB
memory cgroup while linking a single cdylib, the failure was read as a missing system
library, and nine harnesses went unexecuted while the wrong cause was investigated. The
same package linked at 6 GiB with `CARGO_PROFILE_TEST_DEBUG=0` (`codegen-units=1` and
`-C link-arg=-Wl,--no-keep-memory` were tried and proved unnecessary).

RETRY POLICY, and the asymmetry is the point.

  memory -> ONE escalation, to a computed size, recorded as a budget deviation. Never
    past what the host can supply: asking 6 GiB of a 4 GiB VM must fail at preflight,
    not at the linker. `--attempt 2` or higher gets no further escalation.
  disk, or a corrupt container store -> NEVER retried. Retrying into a full disk is what
    broke the runtime: containerd could not grow its sparse disk, image blobs began
    returning `input/output error`, and no container would start on any image. The
    sequence is stop, report, `run-teardown.py --apply`, verify headroom, resume.

Every resource verdict sets `outstanding_teardown`, because a run that dies on ENOSPC is
exactly the run whose residue nobody cleans up.

EXIT CODES encode the verdict so a shell caller branches on `$?` instead of grepping:
0 target-defect or inconclusive, 2 usage, 10 resource fault, 11 not-executed.

Stdlib only. No container, no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXIT_USAGE = 2
EXIT_RESOURCE = 10
EXIT_NOT_EXECUTED = 11

# Fraction of host memory a single contained run may claim. Leaves room for the VM's own
# page cache and for concurrent nodes; escalating to the whole host trades one node's
# evidence for every node's.
HOST_MEM_FRACTION = 0.75

# 2048 MiB SIGKILLed the linker; 6144 MiB linked. 3x is the smallest multiplier that
# clears the one measured data point in a single escalation.
MEM_ESCALATION_FACTOR = 3

_MEMORY_SIGNS = (
    (r"signal:\s*9", "a child was SIGKILLed (cargo reports 101 when its linker is killed)"),
    (r"\bSIGKILL\b", "SIGKILL"),
    (r"out of memory|Out of memory", "kernel OOM message"),
    (r"oom[-_ ]?kill", "OOM killer"),
    (r"[Cc]annot allocate memory", "allocation failure"),
    (r"ld terminated with signal", "the linker was killed"),
    (r"memory allocation of \d+ bytes failed", "Rust allocator abort"),
)

_DISK_SIGNS = (
    (r"No space left on device", "ENOSPC"),
    (r"\bENOSPC\b", "ENOSPC"),
    (r"no space left", "ENOSPC"),
    (r"below --min-free-mb", "run-contained.sh refused to start on low host disk"),
    (r"write /var/lib/(docker|containerd)", "the container store could not be written"),
)

# Downstream of a full disk, not a separate cause: containerd cannot grow its sparse disk,
# so content blobs it already wrote start reading back short. Presents as a missing image.
_STORE_SIGNS = (
    (r"input/output error", "a container-store blob is unreadable"),
    (r"failed to register layer", "layer unpack failed"),
    (r"content digest .*not found", "missing content blob"),
    (r"image not found", "image absent, or a corrupt blob presenting as absent"),
)

# A tool that did not run. Recording any of these as "0 findings" is the false clean this
# whole script exists to prevent.
_NOT_EXECUTED_SIGNS = (
    (r"running 0 tests", "a test binary selected nothing"),
    (r"0 tests? selected", "no test was selected"),
    (r"no test target", "no test target matched"),
    (r"executed=0", "run-contained.sh recorded the command as not executed"),
    (r"does not resolve inside the container", "--require-cmd was unsatisfied"),
    (r"treat this run as INVALID", "the wrapper already declared the run invalid"),
    # Stock opengrep registry packs cannot load under --network none. Across one 15-node
    # campaign this meant no stock ruleset ever executed, and several nodes came close to
    # recording "0 findings" for a scan that never applied a rule.
    (r"(registry|rule ?pack|ruleset|config)[\s\S]{0,120}"
     r"(network|unreachable|Could not resolve|failed to (fetch|download)|Temporary failure)",
     "a ruleset needed the network, which every contained run denies"),
    (r"OG_RC=[1-9]", "opengrep exited non-zero, so no rule was applied"),
    (r"Scan was aborted", "the scanner aborted"),
    (r"not a git repository", "a repo-aware scanner ran outside the repo"),
    (r"scanned 0 commits|commits:\s*0", "a history scan saw no commits"),
)

TEARDOWN_SEQUENCE = [
    "stop the node; do not retry",
    "report the abort as an INVALID run with this verdict",
    "run-teardown.py --run-root <root> --apply",
    "verify headroom with run-preflight.py",
    "resume the node",
]


def _match(text: str, table) -> list[str]:
    return [why for pat, why in table if re.search(pat, text)]


def classify(rc: int, log: str, mem_mb: int | None, host_mem_mb: int | None, attempt: int) -> dict:
    """Verdict plus retry decision. `log` is the combined stdout/stderr of the run."""
    disk = _match(log, _DISK_SIGNS)
    store = _match(log, _STORE_SIGNS)
    memory = _match(log, _MEMORY_SIGNS)
    if rc == 137 and not disk:
        memory.append("rc=137 is SIGKILL, which under a memory cgroup means the cap")
    not_executed = _match(log, _NOT_EXECUTED_SIGNS)

    out: dict = {
        "schema": "sabot-failure/1",
        "rc": rc,
        "attempt": attempt,
        "evidence": {},
        "retry_allowed": False,
        "retry_reason": "",
        "outstanding_teardown": False,
        "remediation": [],
    }

    if disk or store:
        out["verdict"] = "resource:disk"
        out["invalid_run"] = True
        out["evidence"]["disk"] = disk + store
        out["retry_reason"] = (
            "a disk fault is never auto-retried: retrying into a full disk is what "
            "corrupted the container store"
        )
        out["outstanding_teardown"] = True
        out["remediation"] = TEARDOWN_SEQUENCE
        out["exit_code"] = EXIT_RESOURCE
        return out

    if memory:
        out["verdict"] = "resource:memory"
        out["invalid_run"] = True
        out["evidence"]["memory"] = memory
        out["outstanding_teardown"] = True
        ceiling = int(host_mem_mb * HOST_MEM_FRACTION) if host_mem_mb else None
        want = mem_mb * MEM_ESCALATION_FACTOR if mem_mb else None
        if attempt >= 2:
            out["retry_reason"] = (
                f"one escalation is already spent (attempt {attempt}); stop and report the "
                "node as resource-bound"
            )
        elif want is None:
            out["retry_reason"] = "pass --mem-mb to compute an escalation"
        elif ceiling is not None and want > ceiling:
            out["retry_reason"] = (
                f"the escalation to {want} MiB exceeds the host ceiling {ceiling} MiB "
                f"({host_mem_mb} MiB * {HOST_MEM_FRACTION}); this target does not fit on "
                "this host and must fail at preflight, not at the linker"
            )
        else:
            out["retry_allowed"] = True
            out["retry_mem_mb"] = want
            out["retry_env"] = {
                "CARGO_PROFILE_TEST_DEBUG": "0",
                "CARGO_PROFILE_DEV_DEBUG": "0",
            }
            out["retry_reason"] = (
                f"ONE escalation {mem_mb} -> {want} MiB, recorded as an explicit budget "
                "deviation; a second failure stops the node"
            )
        out["exit_code"] = EXIT_RESOURCE
        return out

    if not_executed:
        out["verdict"] = "invalid:not-executed"
        out["invalid_run"] = True
        out["evidence"]["not_executed"] = not_executed
        out["retry_reason"] = (
            "the tool did not run; fix the invocation or record a coverage gap. Recording "
            "this as 0 findings is a false clean"
        )
        out["exit_code"] = EXIT_NOT_EXECUTED
        return out

    if rc == 0:
        out["verdict"] = "inconclusive"
        out["invalid_run"] = False
        out["retry_reason"] = (
            "rc=0 is not evidence anything ran; prove positive work with assert-executed.sh"
        )
        out["exit_code"] = 0
        return out

    out["verdict"] = "target-defect"
    out["invalid_run"] = False
    out["retry_reason"] = "no resource or not-executed signal; the failure is about the target"
    out["exit_code"] = 0
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="classify-failure.py")
    ap.add_argument("--rc", type=int, required=True)
    ap.add_argument("--log", help="combined stdout/stderr of the run; '-' reads stdin")
    ap.add_argument("--mem-mb", type=int, help="the --mem cap the failed run used")
    ap.add_argument("--host-mem-mb", type=int, help="memory the host/VM can actually supply")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.log == "-":
        text = sys.stdin.read()
    elif args.log:
        p = Path(args.log)
        if not p.is_file():
            print(f"classify-failure: no such log: {p}", file=sys.stderr)
            return EXIT_USAGE
        text = p.read_text(errors="replace")
    else:
        text = ""

    v = classify(args.rc, text, args.mem_mb, args.host_mem_mb, args.attempt)
    if args.json:
        print(json.dumps(v, indent=2, sort_keys=True))
    else:
        print(f"verdict={v['verdict']} invalid_run={v['invalid_run']} "
              f"retry_allowed={v['retry_allowed']}")
        for why in sum(v["evidence"].values(), []):
            print(f"  evidence: {why}")
        if v.get("retry_mem_mb"):
            print(f"  retry_mem_mb={v['retry_mem_mb']}")
        print(f"  {v['retry_reason']}")
        if v["outstanding_teardown"]:
            print("  outstanding teardown item: this run's ephemeral residue was not cleaned")
        for step in v["remediation"]:
            print(f"  step: {step}")
    return v["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
