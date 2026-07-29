# Workflow

The full step-by-step procedure. LOAD this before step 1. The SKILL.md list is the
index; this file is the operating detail.

## Step 0: mode and preconditions

Determine interactive or non-interactive first, since it decides whether the
blocking gates apply:

| Condition | Mode |
|---|---|
| A user is present to answer | interactive: both gates block |
| CI, a cron run, or a sub-agent invocation | non-interactive: skip the gates, use defaults, record every gap |

Check `bd` availability per `beads-store.md`. No `bd` stops the run.

Determine the scope mode: `quick`, `full` (default), `audit-only`, or
`harness-only`.

## Step 1: open the run

1. Resolve the artifacts dir. A caller-supplied path (a spawn prompt naming an
   artifacts dir) wins; otherwise default to `<primary>/.break-stuff/run-<id>/artifacts`.
   Create it, and stamp the resolved path so every agent writes to the same place.
2. Create the run epic with `run_id`, `target`, `base_sha`, and `artifacts`
   metadata. The `budget` key is stamped after step 3.
3. Hold the surface nodes until step 2 has detected which surfaces exist.

MUST Let a caller-supplied artifacts dir override the default, since a sub-run spawned with an explicit path must write where the caller expects rather than forking a second location.
MUST Stamp the resolved artifacts dir on the epic before spawning any agent, so every Brief carries one path and agents do not scatter output across two dirs.

## Step 2: resolve the target and detect surfaces

1. When the user named no target, STOP and ask per the SKILL.md two-step. Do not
   assume whole repo.
2. LOAD `targeting.md`. Resolve to an explicit file list plus a base ref, and
   decide in-place or worktree checkout.
3. Detect surfaces by mapping the resolved file list against
   `surfaces/index.md`. Include `robustness` on every run.
4. Create one surface node per detected surface, with a `scope` glob array.
5. Enumerate entry points per surface, since these become the fuzzer's work list:
   parse functions, CLI commands, hook scripts, request handlers, config readers,
   agent definitions. Record each with a `file:line`.

MUST Record the entry points before step 4. A fuzzer given no entry points invents its own scope and writes harnesses for code nobody calls.

## Step 3: probe, propose, wait

1. Run `install-tools.sh --probe`.
2. Build the proposal per `installer.md`: every viable tool for each detected
   surface, default-on pre-selected ON, opt-in shown OFF with its reason.
3. Build the budget table per `fuzzing.md`, stating the harness count and the
   worst-case wall-clock so the user approves a duration.
4. Stop and wait. "go" installs every missing default-on tool, accepts the
   budget, and proceeds.
5. Stamp the approved budget onto the run epic, so a resumed campaign reuses it.

### Step 3.5: read the project's own security config

Before running any scanner, find and read every config that governs it:

| Look for | Effect on findings |
|---|---|
| `.semgrepignore`, `.banditrc`, `#[allow(...)]`, `# nosec`, `//nolint` | a rule the project disabled with a stated reason caps at HARDENING |
| A scanner baseline file | anything in the baseline is pre-existing, so a diff run reports only what is new |
| `SECURITY.md`, an accepted-risk doc, an ADR | a documented accepted risk is cited rather than re-reported |
| `.gitleaksignore`, a secrets allowlist | an allowlisted value is not a finding |

MUST Honor the project's config. Reporting a deliberately disabled rule as a new finding destroys the report's credibility, and the user stops reading it.
MUST Record a suppression that carries no reason as its own HARDENING finding, since an unexplained suppression is a gap rather than a decision.

## Step 4: recon

LOAD `recon.md` and follow it. Produce the trust map, invariant list, idiom census,
and synthesized rules, then record each on the run epic and carry them into every
Brief.

MUST Recon before authoring, since a fuzzer with no invariants writes never-panics harnesses and nothing else.
MUST Aim the standard packs here rather than running them unaimed, because an unaimed pack floods the report and the reader stops separating signal from volume.

## Step 5: author the attack plan

Spawn one `fuzzer` per surface, in parallel, Briefed from `fuzzer-brief.md`. Each
writes harnesses, corpora, vectors, and repo-specific rules from recon's
invariants, files a wisp per artifact, and runs nothing.

`harness-only` mode stops here and reports what was written.

## Step 6: attack

Spawn one `gremlin` per surface node, in parallel, Briefed from
`gremlin-brief.md`. Each one:

1. Runs its surface's scanners, the packs recon aimed, and the rules recon synthesized.
2. Claims and executes the harness wisps for its surface, inside the budget.
3. Reads the code against recon's trust map, then the surface attack checklist.
4. Clears candidates against the surface false-positive traps.
5. Files crash wisps and finding wisps.

MUST Treat a scanner crash as INVALID and fix the invocation, since "0 findings" from a tool that never ran is the most damaging possible report line.
MUST Verify each harness reached its target using the runner's coverage output, because a harness wired to nothing looks exactly like a clean result.

### Step 6.5: live-spawn agentic fuzzing (opt-in)

Only when the user opts in, only on a PR, commit, or range target, and only against
skills or agents the user names. Every generated case runs against every named
target, inside a Worktrunk lease with canaries seeded outside it. See
`references/agentic-fuzz.md` for the gates, containment, and tiering.

MUST Refuse live-spawn on a whole-repo target and say why, since it would attack every definition present.
MUST Read the canaries and collect the artifacts before discarding the lease.

## Step 7: triage crashes

`triager` claims each crash batch, dedups by stack, minimizes every input, and
classifies memory-safety against robustness. Each minimized crash becomes a
finding wisp, and its crash wisp closes.

## Step 8: prove or refute

`challenger` claims every untiered finding wisp and stamps a tier plus an impact,
Briefed from `challenger-brief.md`. Nothing is deleted.

`quick` mode skips this step, and its report states that every finding is untiered.

**Solo / non-interactive runs.** A single agent that ran the finding step cannot
also be the independent `challenger` without breaking "neither judges its own
output". Two honest options, and the report must say which was taken:
- **Spawn `challenger` anyway** when the run can spawn an agent (the default, even
  non-interactively): it is a fresh context that did not produce the findings, so
  the independence holds.
- **Tier inline, marked provisional** only when spawning is impossible (a leaf
  agent with no spawn budget). Every tier is then stamped `by=self` and the report
  headlines that no independent pass ran, so a reader never mistakes a self-tier
  for a challenged one.

MUST Prefer spawning `challenger` even in a non-interactive run, since independence comes from a fresh context rather than from a human being present.
MUST Mark an inline tier `by=self` and headline the missing independent pass when spawning was impossible, because a self-judged finding presented as challenged is the dishonesty the two-agent split exists to prevent.

## Step 9: report

Emit per `report-template.md`, reading the finding set from beads rather than from
the agents' replies. Cite bead IDs, list every written artifact by path, and state
every coverage gap.

MUST Manage the run by reading the graph, not by holding agent returns. Every agent returns a thin pointer (counts, bead ids, artifact paths) and writes its findings to wisps and artifacts, so the orchestrator's context stays flat across any number of surfaces and never compacts. Read the fat payloads from the wisps the returns point at, only when the report needs them.

## Step 10: patch

Only on explicit approval. Spawn `hardener` per approved finding, then re-run the
relevant scanners from step 6 and the relevant harnesses from step 7 to verify.

`audit-only` refuses this step even when approval is offered: it means "do not FIX
the findings", not "write nothing". A regression test that reproduces a PROVEN
finding is a description of the bug, not a fix, so it is written even in audit-only
(the fix that makes it pass is what audit-only withholds). See the write policy below.

## Failure handling

| Failure | Response |
|---|---|
| A scanner is absent | skip, warn, record an install hint, report the dimension as a gap |
| A scanner crashes | INVALID: fix the invocation and rerun, and never report it as clean |
| A harness fails to build | INVALID: report it as an untested entry point |
| A harness hits its cap with coverage climbing | `budget_exhausted`: report the gap with the remaining budget |
| An agent dies mid-campaign | resume from beads per `beads-store.md`, since its wisps survive |
| The budget runs out with harnesses unrun | stop, and list every unrun harness as a gap |
| A crash does not reproduce | a harness bug rather than a target bug, recorded as INVALID |

MUST State every gap in the report. A campaign that hides what it could not check reads as a clean bill of health.

## Debug mode

OFF by default. Turn it ON only when the user asks to debug the break-stuff run
itself, which adds the raw scanner invocations, exit codes, and per-harness exec
counts to the report.
