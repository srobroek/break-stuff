# Fuzzer Brief Template

Construct one Brief per surface for step 4. `fuzzer` writes harnesses, corpora, and
attack scenarios, and executes nothing. Pass facts only: the surface with its entry
points and conventions, and the wisp to file against.

Spawn the fuzzers in parallel, one message with several Agent calls, one per
surface in the step-4 plan.

---

```
You author attack material for the **<SURFACE>** surface of this repository. You
write harnesses and corpora. You run nothing.

## Scope
- Surface: <code | shell | agents | infra | robustness>
- Files: <explicit resolved paths for this surface, not "the whole repo">
- Working directory: <repo root, or the worktree path for a ref target>
- Exclude: <generated, vendored, fixtures>
- Surface node bead: <bead id -- file every harness wisp under this parent>
- Artifacts dir: <absolute path -- write harness files and corpora here or at the
  repo-convention path, and record which>

## Invariants recon derived (assert these)
<the falsifiable claims from step 4: what the code assumes and never checks, each
with a file:line. These are what your harnesses assert. An invariant here beats a
generic never-panics harness, because it catches logic bugs a crash never reveals.>

## Trust boundaries recon mapped
<where data crosses from less trusted to more trusted, with a file:line each, plus
what the code assumes holds after each boundary. Aim harnesses at the assumption.>

## Idiom deviations recon found
<the places this repo departs from its own pattern, with the census count. Each one
is a candidate for a repo-specific rule or a targeted harness.>

## Entry points to cover
<the reachable entry points found in step 2: parse functions, CLI commands, hook
scripts, HTTP handlers, config readers, agent definitions. One line each with a
file:line. This is your work list.>

## Attack-vector baseline recon ranked (write these first)
<the boundary-anchored vectors from `escalation.md`, ranked by the blast radius of
the assumption each breaks. Each names a boundary file:line and the vector class its
shape invites. Author the highest-ranked first, since the budget is finite and the
top boundary is where a proven finding pays for the run.>

## Repo conventions (mirror these)
- Fuzz target location: <fuzz/fuzz_targets/ | *_test.go | tests/fuzz/ | none found>
- Test runner: <cargo test | go test | pytest | vitest>
- Existing fixtures to seed from: <paths>
- Property-test library already in the project: <proptest | hypothesis | fast-check | none>

## Your references
Read `references/harnesses.md` FIRST for invariant selection and placement rules.
Read `references/surfaces/<SURFACE>.md` for the attack checklist this surface
demands. For the agents surface, read `references/corpora/prompt-injection.md`.
Do not improvise a catalogue.

## Budget context (you do not run anything; this shapes what you write)
- Per-harness wall-clock: <wall_s>s
- A harness that cannot reach its target inside that window is the wrong harness:
  narrow the entry point instead of widening the input space.

## Authoring ban (safety)
Never author an input whose effect is irreversible, even though `gremlin` runs it in
a container: fuzz the code path that RECEIVES `rm -rf`/`mkfs`/`DROP TABLE`, never a
harness that EXECUTES it. A destructive-looking payload is data the target parses
(`{"command":"rm -rf /"}` fed to a guard), not a command the harness runs. See
`references/isolation.md`.

## What to produce
1. One harness per reachable entry point, at the repo-convention path, with the
   invariant stated in a comment at the top.
2. A seed corpus per harness, drawn from the repo's own fixtures first.
3. For CLIs, hooks, and MCP servers: a vectors JSON file for
   `scripts/fuzz-cli.py` instead of a bespoke harness, covering every wrapper and
   quoting form in the surface checklist plus one benign vector per guarded
   pattern.
4. One harness wisp per harness, per `references/beads-store.md`, carrying
   `entry_point`, `runner`, and `harness_path` metadata.

## Return
The Fuzzer Output format from your agent definition: a coverage block, a harness
table, and the wisp ids you created. Do not execute a harness, and do not report
findings; finding them is the gremlin's job.
```

---

## Filling guidance

- **One surface per fuzzer is the floor.** Split a surface exceeding roughly 5k
  LOC across several fuzzers by subtree or crate, each with a narrowed file list.
- **Pass the entry points, not a hypothesis.** `fuzzer` decides which invariant
  fits each entry point; handing it your guess about where the bug lives narrows
  the search wrongly.
- **State the convention explicitly.** A fuzzer that guesses the fuzz-target
  location writes files the project's test command never finds.
- **Never ask a fuzzer to run its own harness.** The write and execute split is
  what keeps a silently-broken harness from reporting a clean result.
