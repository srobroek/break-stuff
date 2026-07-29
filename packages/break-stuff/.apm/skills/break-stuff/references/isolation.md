# Isolation and guardrails

Execution runs in a container, never on the host. A Worktrunk lease is a
filesystem boundary only: same kernel, same network, same credentials. A campaign
that fuzzes a parser, runs a `build.rs`, or drives a dev server is running code
whose behaviour is the unknown under test, so it runs where a destructive effect
has nowhere to land.

Three layers, strongest first. The container is the wall; the authoring ban keeps
the fuzzer from arming a payload; the host tripwire is the honest backstop that
lives outside the sandbox and cannot be fooled from inside it.

## What runs where

| Phase | Host or container | Why |
|---|---|---|
| Reading, static scanners (semgrep, clippy, shellcheck, ruff), recon | host | reads bytes, executes nothing untrusted |
| Rule validation, `--vectors-help`, `cargo metadata` | host | no target code runs |
| Fuzz campaigns, harness execution, `fuzz-cli.py` against a real target | **container** | the target's behaviour on hostile input is the unknown |
| `build.rs`, proc-macro expansion, install scripts | **container** | build-time code runs before any test could catch it |
| Dev-server DAST | **container** | the server is started and driven with payloads |

MUST Run every execution phase in a container. A phase that executes target code on the host has no guarantee the target cannot reach the host's files, network, or credentials.
MUST Keep reading and static scanning on the host; a container there is cost with no safety gain.

## Container contract

```
docker run --rm \
  --network none \                 # no outbound anything; loopback DAST maps a port instead
  --memory 2g --memory-swap 2g \   # the budget's mem cap, kernel-enforced
  --pids-limit 512 \               # fork-bomb ceiling
  --cpus 2 \
  --read-only \                    # image fs is read-only
  --tmpfs /scratch:size=512m \     # the only writable place inside
  --cap-drop ALL --security-opt no-new-privileges \
  --user 1000:1000 \               # never root
  -v <target>:/target:ro \         # target mounted READ-ONLY
  -v <artifacts>:/artifacts \      # the one writable host mount, for findings
  <image> <campaign command>
```

MUST Mount the target read-only. The campaign reads and attacks it; it never needs to write the target, and a read-only mount makes an accidental mutation impossible.
MUST Pass `--network none` for a fuzz or build run. A harness that needs loopback (dev-server DAST) gets a published port mapping instead, never full network.
MUST Enforce the run's memory, pid, and cpu budget as container flags, since a flag the kernel enforces holds where a `NOT` rule in prose does not.
MUST Run as a non-root user with `--cap-drop ALL` and `--security-opt no-new-privileges`, so a container escape has nothing to escalate to.
MUST Write findings only to the `/artifacts` bind mount, the single writable path that survives the container.

## Assert the tools survived the build

Containerization guarantees a coverage-guided fuzzer is PRESENT (baked into the
image); it does not guarantee the build produced it. A stale or half-built image
that silently lacks `cargo fuzz` or `atheris` produces the exact false-clean the
package exists to catch. So before the fuzz phase trusts a clean result, assert the
surface's critical tool runs inside the image:

```
scripts/run-contained.sh --assert-tools break-stuff/<surface>:1 <tool[,tool...]>
```

Assert EVERY tool the surface's campaign will invoke, not only the fuzzer — a
missing scanner is the same silent-clean as a missing fuzzer. Pass the full
comma-list the surface doc's Tools table names:

| Surface image | Assert (all campaign tools for the surface) |
|---|---|
| `break-stuff/rust:1` | `cargo-fuzz,cargo-audit,clippy` |
| `break-stuff/python:1` | `atheris,hypothesis,bandit,ruff,semgrep` |
| `break-stuff/node:1` | `jazzer,fast-check,retire` |
| `break-stuff/base:1` | `semgrep,shellcheck,ripgrep` |

Exit 0 means every named tool answered `--version` inside the image; non-zero names
the missing ones. Assert the complete set once, up front, so a campaign never
discovers a missing scanner mid-run and reports its dimension as clean.

MUST Assert EVERY tool the surface's campaign will invoke inside the image up front, not only the coverage-guided fuzzer. A campaign that runs a scanner or fuzzer without confirming it is present reports a clean result it did not earn, and a missing scanner is as silent as a missing fuzzer.
MUST Refuse the fuzz phase and report the surface as uncovered when the assertion fails, rather than falling through to hand-written vectors and calling it fuzzed. Rebuild the image from `references/containers/` and retry, or record the gap in the report headline.

## Degrade loudly, never silently

A container runtime may be absent (`docker`, `podman`, `finch`, `nerdctl`). Since
execution is container-mandatory, the run cannot proceed to an execution phase
without one.

MUST Probe for a runtime at step 3 and, when none is present, refuse the execution phases and say so in the report: static scanning and recon ran, fuzzing and DAST and build-execution did not, and the coverage gap is the whole execution surface.
MUST Never fall back to host execution when no container is available. A host-only fuzz run is the exact unbounded risk the container exists to prevent, and a silent fallback presents it as a completed campaign.
NOT Never weaken the container contract (add network, drop the mem cap, run root) to make a harness pass. A harness that only runs unconfined is a harness that does not run.

## The authoring ban

The container contains a blast; this stops the fuzzer from arming one. Even inside
isolation, an input whose *purpose* is an irreversible effect is never generated.

MUST Fuzz the code path that RECEIVES a destructive input, never author a harness that EXECUTES the destructive branch. A parser that mishandles `rm -rf /` is the target; running `rm -rf /` is not the test.
NOT Never generate an input class whose effect is irreversible even in the container: a real `rm`/`mkfs`/`dd` to a device, a `DROP`/`TRUNCATE` against a live database, a fork bomb, a disk-filling loop. The finding is that the target accepts the input, not that the effect happened.
MUST Seed a destructive-looking payload as data the target parses, not as a command the harness runs. `{"command":"rm -rf /"}` fed to a guard is a vector; `os.system("rm -rf /")` in a harness is an attack on the machine.

## The host tripwire

The backstop that lives outside the sandbox. A monitor inside the container can be
subverted by what it monitors; a host-side hook watching the filesystem cannot.

Wire a `PostToolUse` (or `FileChanged`, where the harness supports it) hook, scoped
to the campaign, that halts on any observable the container should have prevented:

| Tripwire | Halt because |
|---|---|
| A write anywhere outside `<artifacts>` and the container | the container boundary leaked, or an execution phase ran on the host |
| A canary file (seeded outside the artifacts dir) changed or read | a payload reached beyond its sandbox |
| An outbound connection beyond loopback from a campaign process | `--network none` was bypassed or a phase ran unconfined |
| Disk or inode growth past the budget, a pid/fd runaway | a resource attack the container caps should have bounded |

MUST Seed canaries OUTSIDE the container mounts before an execution phase, and read them after, since a canary the campaign can reach is a canary that proves reach.
MUST Halt the campaign, preserve the artifacts, and report on any tripwire rather than continuing. A campaign that trips a guardrail and keeps running has already lost the property the guardrail asserts.
MUST Treat a tripwire hit as a finding about the ISOLATION, reported alongside the target findings, since the campaign reaching the host is worse news than anything it found in the target.
NOT Never disable the tripwire to let a campaign finish. The tripwire firing is the campaign telling you it escaped.

## Report line

Every campaign states its isolation posture, so a reader knows what the findings
were produced under:

```
Isolation: docker, --network none, mem 2g, pids 512, target ro, non-root.
           host tripwire active (artifacts-dir + 3 canaries). No trip.
```

MUST State the isolation posture in the report. A finding produced under an unknown or degraded posture is a finding whose blast radius the reader cannot judge.
