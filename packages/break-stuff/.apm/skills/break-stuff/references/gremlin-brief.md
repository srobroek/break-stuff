# Gremlin Brief Template

Construct one Brief per surface node for step 5. `gremlin` executes scanners and
the harnesses `fuzzer` wrote, then reads for what neither can see. It edits
nothing.

Spawn the gremlins in parallel, one message with several Agent calls, one per
surface node.

---

```
You attack the **<SURFACE>** surface of this repository. You execute scanners and
the harnesses already written for this surface, and you read the code for what
they miss. You do not edit any file.

## Scope
- Surface: <code | shell | agents | infra | robustness>
- Files: <explicit resolved paths for this surface>
- Working directory: <repo root, or the worktree path for a ref target>
- Exclude: <generated, vendored, fixtures>
- Base ref (if any): <for diff/PR/range targets>
- Scoped-run note: <for a bounded target, skip global-class tools and say so>
- Surface node bead: <bead id -- your claim target and the parent for every wisp>
- Artifacts dir: <absolute path -- scanner JSON, crash inputs, and logs go here>

## Trust map recon produced
<the boundaries for this surface with a file:line each, and what the code assumes
holds after each one. Your reading pass targets these rather than sweeping the
whole file list.>

## Rules recon synthesized for THIS repo (run these)
<absolute paths to the validated rule files, with the invariant each encodes. Run
them alongside the standard packs; they carry knowledge no pack has.>

## Standard packs to run, and the ones deliberately off
<the packs recon aimed at this surface, with the exact invocation. Also the packs
left off and why, so their absence is a recorded decision rather than an oversight.>

## Tools confirmed installed for this surface
<name plus the exact run recipe from references/surfaces/<SURFACE>.md, one per
line. A tool not listed here is NOT available: record it as a coverage gap rather
than attempting it.>

## Project security config found in step 3.5 (honor it)
<baselines, suppressions, # nosec / #[allow] / .semgrepignore entries, accepted-risk
docs. A rule the project disabled with a stated reason caps at HARDENING.>

## Harnesses to execute
<list the harness wisps for this surface. Discover them yourself with:
  bd list --parent <surface-bead> --labels brk-harness --status open --json
Claim each with `bd update <wisp> --claim` before running it.>

## Isolation (mandatory for execution)
Run every harness, scanner-that-executes, and dev-server inside the container of
`references/isolation.md`: `--network none`, the budget as kernel-enforced mem/pid
caps, target mounted read-only, findings to the `/artifacts` mount, non-root. If no
container runtime is present, do NOT run the execution phases on the host: report
them as an isolation coverage gap and run only the static/reading passes.

## Assert the fuzzer before the fuzz phase
Before running any coverage-guided fuzz harness, assert its tool is in the image:
`run-contained.sh --assert-tools break-stuff/<surface>:1 <fuzzer>`. Exit non-zero
means the tool is missing: REFUSE the fuzz phase and report the surface as an
uncovered gap in the report headline, do NOT fall through to hand-written vectors
and call it fuzzed. See `references/isolation.md`.

## Budget (hard cap, approved by the user)
- Per-harness wall-clock: <wall_s>s   Jobs: <jobs>   Memory: <mem_mb>MB
- Stop at the cap. When a harness hits it with coverage still climbing, stamp
  state:budget_exhausted rather than reporting a clean result.

## Your reference
Read `references/surfaces/<SURFACE>.md` FIRST: it is your tool recipe list, attack
checklist, impact calibration, and false-positive trap list. Read
`references/fuzzing.md` for runner flags and crash capture. Do not improvise the
catalogue.

## Method
1. Run every listed scanner and every synthesized rule file with its exact recipe.
   A crash or usage error is an INVALID run to fix and rerun, never a clean result.
2. Claim and execute each harness wisp inside the budget. Verify the harness
   reached its target using the runner's coverage counters; a harness wired to
   nothing reports zero crashes exactly like a robust target.
3. Read the code against the Brief's trust map first, then the surface's attack
   checklist, for what tools cannot see: authorization logic, guard bypasses,
   injection paths, unbounded work. The trust map aims this pass, so a boundary
   recon flagged gets read before anything else.
4. Clear every candidate against the surface's false-positive trap list before
   filing it.
5. File a crash wisp per distinct crash and a finding wisp per non-crash finding,
   per `references/beads-store.md`. Persist every crashing input and record the
   exact reproduce command.

## What you MUST NOT do
- Edit, patch, or fix anything, including a harness that looks wrong. Report a
  broken harness as INVALID and move on.
- Raise the budget, or continue past the cap.
- Touch a network target, a shared service, or anything outside this repo.
- File a finding without a file:line, or a crash without a persisted input.
- Report a stock pack match as a finding above HARDENING unless the trust map places it on a path.

## Rules
MUST Tier a stock pack match at HARDENING unless the Brief's trust map places it on a reachable path, since a generic match carries no knowledge of this repo.
MUST Re-verify each synthesized rule against its known-positive fixture before trusting a zero-match result, and report the rule as INVALID when the fixture does not match, because a rule that matches nothing is indistinguishable from a repo with no findings.
MUST Report which findings came from synthesized rules against stock packs, because a campaign carried entirely by stock packs did no real recon and the report must say so.

## Return
The Gremlin Output format from your agent definition: a coverage block naming
every tool run, skipped, or invalid; the wisp ids you filed; and a findings table.
Do not tier the findings; the challenger does that.
```

---

## Filling guidance

- **Hand the recipes, do not let it improvise them.** A tool invoked with guessed
  flags either floods the report with default noise or silently matches nothing.
- **Name the harnesses by wisp, not by path.** The graph is the source of truth, so
  a resumed campaign re-reads it rather than trusting a stale list.
- **State the budget in the Brief.** A gremlin that never learned the cap runs
  until something kills it.
- **Pass the project's own config.** Reporting a rule the project deliberately
  disabled as a new finding destroys the report's credibility.
