"""classify-failure.py gives every caller one verdict on a failed contained run.

A resource fault is an INVALID run: not a finding, not a target defect. A campaign lost
nine unexecuted harnesses to reading a memory-cgroup SIGKILL as a missing system library.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".apm" / "skills" / "sabotage"
SCRIPT = SKILL / "scripts" / "classify-failure.py"

EXIT_USAGE = 2
EXIT_RESOURCE = 10
EXIT_NOT_EXECUTED = 11


def run(log: str | None, *args: str) -> tuple[int, dict]:
    """Run the classifier over `log` on stdin and return (rc, parsed json)."""
    p = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--json"],
        input=log if log is not None else "",
        capture_output=True,
        text=True,
    )
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else {})


LINKER_OOM = """\
   Compiling pv_ipc v0.1.0
error: linking with `cc` failed: signal: 9 (SIGKILL: kill)
collect2: fatal error: ld terminated with signal 9 [Killed]
"""

ENOSPC = """\
error: failed to write /artifacts/.build/deps/libpv.rlib
Caused by: No space left on device (os error 28)
"""

CORRUPT_STORE = """\
docker: Error response from daemon: failed to register layer:
  error reading from server: input/output error
"""


# --- memory: one bounded escalation ----------------------------------------


def test_linker_sigkill_is_a_memory_fault_not_a_missing_library():
    rc, v = run(LINKER_OOM, "--rc", "101", "--log", "-", "--mem-mb", "2048",
                "--host-mem-mb", "16384")
    assert rc == EXIT_RESOURCE
    assert v["verdict"] == "resource:memory"
    assert v["invalid_run"] is True
    assert v["retry_allowed"] is True
    # 2048 MiB SIGKILLed ld; the same package linked at 6144.
    assert v["retry_mem_mb"] == 6144
    assert v["retry_env"]["CARGO_PROFILE_TEST_DEBUG"] == "0"


def test_rc_137_alone_is_read_as_the_memory_cap():
    rc, v = run("the container went away\n", "--rc", "137", "--log", "-",
                "--mem-mb", "2048", "--host-mem-mb", "16384")
    assert rc == EXIT_RESOURCE
    assert v["verdict"] == "resource:memory"


def test_a_second_attempt_gets_no_further_escalation():
    # One escalation, recorded as a budget deviation. A campaign that keeps doubling
    # trades every other node's memory for one node's evidence.
    rc, v = run(LINKER_OOM, "--rc", "101", "--log", "-", "--mem-mb", "6144",
                "--host-mem-mb", "65536", "--attempt", "2")
    assert rc == EXIT_RESOURCE
    assert v["retry_allowed"] is False
    assert "already spent" in v["retry_reason"]


def test_an_escalation_past_what_the_host_has_is_refused():
    # Asking 6 GiB of a 4 GiB VM must fail at preflight, not at the linker.
    rc, v = run(LINKER_OOM, "--rc", "101", "--log", "-", "--mem-mb", "2048",
                "--host-mem-mb", "4096")
    assert rc == EXIT_RESOURCE
    assert v["retry_allowed"] is False
    assert "ceiling" in v["retry_reason"]


def test_memory_without_a_known_cap_cannot_compute_an_escalation():
    rc, v = run(LINKER_OOM, "--rc", "101", "--log", "-")
    assert rc == EXIT_RESOURCE
    assert v["retry_allowed"] is False
    assert "--mem-mb" in v["retry_reason"]


# --- disk and the container store: never auto-retried ----------------------


def test_enospc_is_never_auto_retried():
    # Retrying into a full disk is what corrupted the container store.
    rc, v = run(ENOSPC, "--rc", "101", "--log", "-", "--mem-mb", "2048",
                "--host-mem-mb", "65536")
    assert rc == EXIT_RESOURCE
    assert v["verdict"] == "resource:disk"
    assert v["retry_allowed"] is False
    assert v["remediation"][0].startswith("stop")


def test_a_corrupt_container_blob_is_a_resource_fault_not_a_finding():
    rc, v = run(CORRUPT_STORE, "--rc", "125", "--log", "-")
    assert rc == EXIT_RESOURCE
    assert v["verdict"] == "resource:disk"
    assert v["invalid_run"] is True


def test_disk_beats_memory_when_both_signs_appear():
    # A full disk kills the linker too; retrying it with more memory refills the disk.
    rc, v = run(LINKER_OOM + ENOSPC, "--rc", "137", "--log", "-", "--mem-mb", "2048",
                "--host-mem-mb", "65536")
    assert rc == EXIT_RESOURCE
    assert v["verdict"] == "resource:disk"
    assert v["retry_allowed"] is False


def test_every_resource_verdict_leaves_an_outstanding_teardown_item():
    # A run that dies on ENOSPC is exactly the run whose residue nobody cleans up.
    for log in (LINKER_OOM, ENOSPC, CORRUPT_STORE):
        _, v = run(log, "--rc", "101", "--log", "-")
        assert v["outstanding_teardown"] is True


# --- not executed: never "0 findings" --------------------------------------


def test_a_test_binary_that_selected_nothing_is_not_executed():
    rc, v = run("running 0 tests\ntest result: ok. 0 passed\n", "--rc", "0", "--log", "-")
    assert rc == EXIT_NOT_EXECUTED
    assert v["verdict"] == "invalid:not-executed"
    assert "false clean" in v["retry_reason"]


def test_a_history_scan_over_zero_commits_is_not_executed():
    # gitleaks git mode on a worktree whose .git is a pointer file: 0 commits, exit 0.
    rc, v = run("scanned 0 commits for leaks\n", "--rc", "0", "--log", "-")
    assert rc == EXIT_NOT_EXECUTED
    assert v["verdict"] == "invalid:not-executed"


def test_a_ruleset_that_needed_the_network_is_not_executed():
    # Stock registry packs cannot load under --network none, so no rule ever applied.
    log = "opengrep: could not fetch ruleset p/rust: Temporary failure in name resolution\n"
    rc, v = run(log, "--rc", "2", "--log", "-")
    assert rc == EXIT_NOT_EXECUTED
    assert v["verdict"] == "invalid:not-executed"


def test_a_nonzero_opengrep_status_is_not_executed():
    rc, v = run("OG_RC=2\n", "--rc", "0", "--log", "-")
    assert rc == EXIT_NOT_EXECUTED


def test_the_wrapper_recording_executed_zero_is_not_executed():
    rc, v = run("executed=0\nreason=--require-cmd unsatisfied\n", "--rc", "6", "--log", "-")
    assert rc == EXIT_NOT_EXECUTED


# --- target defects and the rc=0 trap --------------------------------------


def test_a_real_assertion_failure_is_a_target_defect():
    log = "test parse::rejects_overflow ... FAILED\nassertion failed: left == right\n"
    rc, v = run(log, "--rc", "101", "--log", "-")
    assert rc == 0
    assert v["verdict"] == "target-defect"
    assert v["invalid_run"] is False


def test_rc_zero_over_a_clean_looking_log_is_inconclusive_not_a_pass():
    # rc=0 is not evidence anything ran: a rewritten toolchain produced rc=0 with 0 tests.
    rc, v = run("done\n", "--rc", "0", "--log", "-")
    assert rc == 0
    assert v["verdict"] == "inconclusive"
    assert "not evidence" in v["retry_reason"]


# --- interface -------------------------------------------------------------


def test_a_missing_log_file_is_a_usage_error(tmp_path):
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--rc", "1", "--log", str(tmp_path / "nope.log")],
        capture_output=True, text=True,
    )
    assert p.returncode == EXIT_USAGE


def test_a_missing_rc_is_a_usage_error():
    p = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert p.returncode == EXIT_USAGE


def test_json_carries_the_verdict_evidence_and_exit_code():
    _, v = run(LINKER_OOM, "--rc", "101", "--log", "-", "--mem-mb", "2048",
               "--host-mem-mb", "16384")
    assert v["schema"] == "sabot-failure/1"
    for key in ("verdict", "invalid_run", "retry_allowed", "retry_reason",
                "outstanding_teardown", "remediation", "evidence", "exit_code"):
        assert key in v
    assert v["evidence"]["memory"]


def test_human_output_names_the_evidence_and_the_teardown_step():
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--rc", "101", "--log", "-"],
        input=ENOSPC, capture_output=True, text=True,
    )
    assert p.returncode == EXIT_RESOURCE
    assert "verdict=resource:disk" in p.stdout
    assert "outstanding teardown item" in p.stdout
    assert "run-teardown.py" in p.stdout
