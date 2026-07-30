# Fuzzing: budgets, runners, crash capture

Execution rules for `gremlin`. Everything here runs against local code in this
repo or worktree, with no network target and no live load probe.

## Budget

The budget is approved by the user at step 3 and stored in the run epic's
`budget` metadata, so a resumed campaign reuses it rather than re-asking.

| Knob | Default | Meaning |
|---|---|---|
| `wall_s` | 60 | seconds per harness |
| `jobs` | 4 | concurrent fuzz processes |
| `mem_mb` | 2048 | address-space cap per process |
| `total_s` | 1800 | campaign-wide ceiling |

Propose these as a table alongside the tool table, with the count of harnesses and
the resulting worst-case wall-clock, so the user approves a duration rather than a
number they have to multiply themselves.

MUST Enforce the cap in the runner rather than by watching the clock. Use each fuzzer's own time flag, and wrap anything lacking one in `timeout`.
MUST Cap memory with `ulimit -v` or the runner's own flag, because an unbounded-allocation finding otherwise takes the developer's machine down with it.
MUST Stop at `total_s` even with harnesses unrun, then record each unrun harness as a coverage gap.
MUST Stamp `state:budget_exhausted` when a harness hits its cap while coverage is still growing, since that distinguishes "found nothing" from "ran out of time".
NOT Never raise the budget mid-campaign without asking. A budget the user approved is the authorization for the run.

## Runners

| Language | Command | Time flag | Crash artifact |
|---|---|---|---|
| Rust | `cargo fuzz run <target> -- -max_total_time=<wall_s> -rss_limit_mb=<mem_mb>` | `-max_total_time` | `fuzz/artifacts/<target>/crash-*` |
| Rust (property) | `cargo test --release <name>` with `PROPTEST_CASES=<n>` | case count | `proptest-regressions/*.txt` |
| Go | `go test -fuzz=<Fuzz> -fuzztime=<wall_s>s -parallel=<jobs>` | `-fuzztime` | `testdata/fuzz/<Fuzz>/*` |
| Python | `python -m atheris <harness>.py -max_total_time=<wall_s>` | `-max_total_time` | stderr repro plus written input |
| Python (property) | `pytest --hypothesis-show-statistics` | derive from `deadline` and `max_examples` | `.hypothesis/examples/` |
| JS/TS | `npx jazzer <harness> -- -max_total_time=<wall_s>` | `-max_total_time` | crash file in cwd |
| JS/TS (property) | `npx vitest run` with fast-check | `numRuns` | counterexample in the failure output |
| C/C++ | `<harness> -max_total_time=<wall_s> -rss_limit_mb=<mem_mb>` | `-max_total_time` | `crash-*` in cwd |
| C/C++ (AFL++) | `afl-fuzz -i <in> -o <out> -V <wall_s> -m <mem_mb> -- <bin> @@` | `-V` | `<out>/default/crashes/*` |
| Any CLI or hook | `scripts/fuzz-cli.py --target <t> --timeout <s> --mem-mb <m> --vectors <f>` | `--timeout` per invocation | `--artifacts-dir` |

MUST Build with sanitizers where the language offers them: `RUSTFLAGS="-Zsanitizer=address"` under `cargo fuzz`, `-fsanitize=address,undefined` for C and C++, and `-race` for Go concurrency harnesses. A memory bug without a sanitizer is silent corruption rather than a crash.
MUST Persist the corpus between runs, since a corpus thrown away makes every campaign start from zero.
DEFAULT Seed from the repo's own test fixtures and testdata before generating inputs, because a real message shape reaches deeper code than random bytes.

## Coverage honesty

A campaign that finds nothing has to distinguish four cases, since they demand
different remediation and only one of them is good news:

| Observation | Report as |
|---|---|
| Harness ran to its cap, coverage plateaued, no crash | genuine clean result for that entry point |
| Harness ran to its cap, coverage still climbing | `budget_exhausted`, a coverage gap with a stated remaining budget |
| Harness failed to build or link | `invalid`, since nothing was tested |
| Harness ran but the entry point rejected every input early | `invalid`, because a harness whose inputs all fail validation tests the validator alone |

MUST Read the fuzzer's own coverage or exec-per-second output rather than inferring from the absence of crashes. A harness wired to nothing reports zero crashes exactly like a target with no bugs.
MUST Check that a harness reached the code it targets, using the runner's coverage counters or a deliberate assertion the harness should trip on a known-bad input.

## Tool selection

Runners above are the execution layer. The generator, mutator, minimizer, and
coverage tool come from `fuzz-tools.md`, picked by the input shape recon recorded.

## Crash capture

Every crash becomes a crash wisp with its input persisted, then goes to
`triager`:

1. Copy the crashing input to `<artifacts>/crash-<surface>-<n>.<ext>`.
2. Record the runner's stack or panic message, plus the exact command that
   reproduces it.
3. Create the crash wisp with `input_path` and `stack_hash` metadata per
   `beads-store.md`.
4. Continue the campaign. A crash stops its own harness, not the run.

MUST Verify a crash reproduces from the persisted input before filing it, because a crash that only happens under the fuzzer's own state is a harness bug.
MUST Record the exact reproduce command in the wisp, since a crash nobody can rerun cannot be fixed or verified.

## Safety

Execution runs in a container, not on the host, and not merely in a worktree. The
container contract, the authoring ban on irreversible inputs, and the host tripwire
are in `references/isolation.md`; the rules below assume that isolation is in place.

MUST Run against local code only, inside the container of `references/isolation.md`. A fuzz target that opens a network connection beyond loopback is out of scope and gets rewritten or dropped.
MUST Run in a worktree when a harness writes files, keeping the campaign out of the user's working tree.
MUST Cap concurrency at the approved `jobs`, and lower it when the machine is the developer's own workstation.
NOT Fork bombs, disk-filling loops, and any PoC that deletes or overwrites a path outside the artifacts dir are all banned.
NOT Never point a harness at a shared database, a staging environment, or any service the user does not run locally.
