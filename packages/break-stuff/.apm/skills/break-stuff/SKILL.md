---
name: break-stuff
description: Attack code, scripts, hooks, or agents for vulns and robustness bugs, then fuzz and prove them. Use when asked to harden, red-team, or fuzz.
---

# Break Stuff

Attack a target across five surfaces, prove each finding with a traced path or a
reproducing input, and report on two axes: evidence and impact. Product code stays
untouched until step 10, which requires explicit approval; harnesses and regression
tests are written freely.

Run state lives in beads. Agents hand work to each other through wisps, so a
campaign survives a crash and resumes from the durable graph. LOAD
`references/beads-store.md` before creating anything.

This SKILL is a router. Load the referenced file for each step rather than
inlining its content.

## STOP: pin the scope before you touch the target

Answer the three questions below before detecting the stack, running a scanner, or
spawning a `gremlin`. None is skippable in an interactive run. LOAD
`references/interview.md` for how to probe for what the user left unsaid and what an
answer should make you distrust. It also gives the defaults a non-interactive run
records as gaps.

1. **Which target, and what do you fear most?** Ask in two steps when the user named
   none. Offer every time: `whole repo` · `language/area filter` · `directory/module` ·
   `file(s)` · `one script/hook` · `one agent or skill` · `uncommitted changes` ·
   `commit` · `commit range / branch compare` · `PR`. Kinds compose. Assuming whole
   repo is a scope error. Capture the user's stated fear too; it is stamped on the
   epic as `threat` and orders the report, without being handed to a scout as a
   hypothesis.
2. **Which surfaces?** Detect them from the target via `references/surfaces/index.md`,
   then present the detected set for the user to trim or extend, pre-selected ON.
   `robustness` is mandatory and cannot be removed. A surface file-detection missed
   (a frontend with no framework marker, live web DAST the user wants) can be added
   here; a detected surface the user does not want scanned can be dropped. This is
   one message with question 3, not a separate prompt.
3. **Which tools, what fuzz budget, and any blast-radius opt-in?** Run
   `<skill-dir>/scripts/install-tools.sh --probe`. In one message, propose the
   full thorough tool set per detected surface as a tiered table (default-on
   pre-selected ON, opt-in shown OFF with a reason) together with a fuzz budget
   table covering wall-clock per harness, parallel jobs, and memory cap. Live-spawn
   agentic fuzzing and dev-server DAST run real payloads through real grants, so they
   are OFF until the user names the target and opts in here. Then wait for the reply.
   "go" means: install every missing default-on tool, accept the proposed budget, run
   everything except the blast-radius opt-ins.

A **non-interactive** run (CI, or a sub-agent with no user to ask) is the only
exception: use the target it was given or the whole repo, the full detected surface set,
the budget defaults from `references/fuzzing.md`, and the installed tools, then
record every gap.

**Skill dir vs. target dir.** Tools run with cwd set to the *target* repo, while
this skill's shipped assets (`scripts/`, `references/corpora/`) live in the *skill*
dir. Note the directory holding this `SKILL.md` once as `$BREAK_SKILL_DIR` and
reference every shipped asset by an absolute path beneath it. A skill-relative
path silently matches nothing, and a run that matched nothing looks clean.

## Division of labour

The split that keeps findings honest: authors write, the executor executes, and
neither judges its own output.

| Agent | Writes | Executes | Judges |
|-------|--------|----------|--------|
| `scout` | recon artifacts, repo-specific rules | read-only queries | nothing |
| `fuzzer` | harnesses, corpora, attack scenarios | nothing | nothing |
| `gremlin` | nothing | scanners and harnesses, per surface | nothing |
| `triager` | crash records | minimizer only | crash class |
| `challenger` | nothing | read-only diagnostics | evidence tier |
| `hardener` | product patches | verification re-run | nothing |

## Workflow

Run in order. The full procedure lives in `references/workflow.md`; LOAD it first.

1. **Open the run.** Create the run epic and one surface node per detected surface
   per `references/beads-store.md`. Every later handoff attaches to this graph.
2. **Resolve the target and detect surfaces.** LOAD `references/targeting.md`:
   resolve to an explicit file list plus base ref, choose in-place or worktree
   checkout, confirm scope. Map the target onto surfaces through
   `references/surfaces/index.md`. A repo hits several surfaces at once, and a
   single hook usually hits both shell and robustness.
3. **Probe, propose tools and budget, then wait** (blocking, interactive runs).
   See `references/tooling.md` with `references/installer.md`.
   - **3.5. Read the project's own security config before running anything.**
     Baselines, suppressions, `# nosec` / `#[allow]` / `.semgrepignore`, and
     accepted-risk docs all govern. A rule the project disabled with a stated
     reason caps at HARDENING.
   - **3.6. Repo-global pre-pass.** Run every whole-tree scanner (deps, secrets),
     the union of cross-surface scanner invocations, the baseline test suite, and the
     repo self-read ONCE, and stamp the results on the epic. Surfaces cite them
     rather than recomputing per surface. See `references/workflow.md`.
4. **Recon.** Spawn one `scout` per surface, in parallel, to derive this repo's own
   threat model: what it claims about itself, where its trust boundaries sit, how it
   does things and which places deviate, plus validated semgrep or ast-grep rules
   for THIS codebase. Standard rulesets are used as they come, and what recon builds
   is the harness around them. LOAD `references/recon.md`; Brief from
   `references/scout-brief.md`.
5. **Author the attack plan.** Spawn `fuzzer` per surface to write harnesses,
   seed corpora, and attack scenarios for every reachable entry point, mirroring
   the repo's own convention for where fuzz targets live. Scripts, hooks, and CLIs
   get the shipped `scripts/fuzz-cli.py`; agents and skills get
   `references/corpora/prompt-injection.md`. Each finished harness becomes a
   harness wisp. Each harness asserts an invariant recon discovered. Brief from
   `references/fuzzer-brief.md`, patterns in `references/harnesses.md`.
6. **Attack.** Spawn one `gremlin` per surface node, in parallel. Each runs its
   surface's scanners plus the rules recon synthesized, claims the harness wisps
   for its surface, executes them
   inside the approved budget against local code, and reads for what scanners miss:
   trust boundaries, authz logic, guard bypasses, prompt-injection paths, unbounded
   work. Brief from `references/gremlin-brief.md`. Anything absent gets skipped,
   warned about, and recorded with an install hint; a scanner crash is an INVALID
   run, since reporting it as "0 findings" hides the gap.
7. **Triage crashes.** Every crash `gremlin` files becomes a crash wisp. `triager`
   claims each batch, dedups by stack, minimizes to a smallest reproducing input,
   and separates memory-safety from robustness.
8. **Prove or refute.** `challenger` claims the finding wisps and sets each
   evidence tier, Briefed from `references/challenger-brief.md`. A refuted finding
   is recorded as REFUTED alongside the refutation.
9. **Report.** Emit via `references/report-template.md`, citing bead IDs so
   remediation is trackable after the session ends.
10. **Patch, only on explicit approval.** Spawn `hardener` per approved finding,
    then re-run steps 6 and 7 to verify.

## Hard rules

MUST Fuzz and attack only local code in this repo or worktree. A network host, public endpoint, or third-party service is out of scope regardless of who asks.
MUST Attack this codebase rather than a model. An LLM red-team tool measures a model's alignment, which is a different target, so it stays out of scope even on the agents surface.
MUST Cap every campaign with the wall-clock, job, and memory limits set in step 3, and stop when they are reached.
MUST Run every execution phase (fuzzing, DAST, build-script execution) in a container per `references/isolation.md`, never on the host, and refuse the execution phases when no container runtime is present rather than falling back to the host.
MUST Never author an input whose effect is irreversible even inside the container. Fuzz the code path that receives `rm -rf` while leaving the command itself unexecuted. See `references/isolation.md`.
MUST Keep every finding. A challenger-refuted finding is reported as REFUTED with its reason, and a finding with no traced path is reported as HARDENING.
MUST Carry both axes plus a `file:line` on every finding: the evidence tier (PROVEN|REACHABLE|HARDENING|REFUTED) and the impact (CRITICAL|HIGH|MEDIUM|LOW).
MUST Keep the write and execute roles apart. `fuzzer` never runs a harness it wrote, and `gremlin` never edits one it runs, because an agent that grades its own output hides its own bugs.
MUST Leave product code untouched in steps 1 to 9. Steps 5 to 7 may only write harness files, corpora, and tests; `hardener` patches in step 10 on explicit approval, behind a verification re-run.
MUST Leave every written artifact uncommitted and list it in the report, since committing is the user's call.
MUST Treat robustness findings as first-class: a crash on malformed input with no attacker path is a real finding, tiered by impact.
MUST Detect with real tools from `references/tooling.md` and `references/fuzz-tools.md`. A regex grep is no substitute for a scanner, a hand-written corpus is no substitute for a generator, and a missing tool becomes a reported coverage gap.
MUST Aim the standard rulesets with recon rather than running them unaimed. Stock packs are the borrowed detectors, and the harness around them is derived per repo, so a campaign whose findings all came from stock packs did no recon and the report says so.
MUST Graduate every rule behind a confirmed finding into the repo's own lint config, since the regression test guards that one instance and only the rule guards the next.
MUST Route every handoff through a bead or wisp per `references/beads-store.md`. A finding that exists only in an agent's reply dies with the session.
DEFAULT Resolve language and area filters by detected-surface glob rather than directory path.
DEFAULT Write a regression test for every PROVEN finding, beside the repo's existing tests.
NOT A proof-of-concept that damages state is banned: destructive filesystem writes; fork bombs; exhausting the developer's machine past the approved cap.
NOT Raw scanner output is HARDENING until a path or repro is traced, so do not report it as a finding on its own.

## Scope modes

- **quick**: steps 1 to 6 with a smoke campaign over existing harnesses, skipping new harness authoring and the challenger.
- **full** (default): every step.
- **audit-only**: steps 1 to 9 that describe findings without fixing them. Regression tests that reproduce a PROVEN finding are still written, since a test describes the bug; only the product-code change is withheld.
- **harness-only**: steps 1 to 5: author harnesses and corpora, execute nothing.

## References

| File | When to load |
|------|--------------|
| `references/workflow.md` | Always, before step 1 |
| `references/interview.md` | Steps 0, 2, 3: pin target, threat, surfaces, tools, budget, consent |
| `references/beads-store.md` | Step 1: run graph, wisps, handoff, resume |
| `references/escalation.md` | Steps 4, 6, 8: build the attack-vector baseline and chain findings |
| `references/targeting.md` | Step 2: any non-whole-repo target |
| `references/surfaces/index.md` | Step 2: route target to surface docs |
| `references/recon.md` | Step 4: derive the trust map, invariants, and repo-specific rules |
| `references/scout-brief.md` | Step 4: build each `scout` Brief |
| `references/surfaces/<surface>.md` | Steps 5 to 7: per-surface attacks and tools |
| `references/tooling.md` | Steps 3 to 6: scanner catalog, invocation, overlap, class |
| `references/installer.md` | Step 3: install-flow contract and bundles |
| `references/fuzzer-brief.md` | Step 5: build each `fuzzer` Brief |
| `references/harnesses.md` | Step 5: harness patterns per target kind |
| `references/gremlin-brief.md` | Step 6: build each `gremlin` Brief |
| `references/fuzz-tools.md` | Steps 5 to 7: generator, mutator, minimizer, and coverage catalog |
| `references/isolation.md` | Steps 5 to 7: container contract; authoring ban; host tripwire |
| `references/fuzzing.md` | Step 6: budgets, runners, crash capture |
| `references/corpora/prompt-injection.md` | Steps 5 to 6: agent-surface payloads |
| `references/agentic-fuzz.md` | Steps 5 to 6: generated attacks against a hook, skill, or agent |
| `references/challenger-brief.md` | Step 8: build the `challenger` Brief |
| `references/report-template.md` | Step 9: two-axis report format |

## Agents

| Agent | Role | Spawned |
|-------|------|---------|
| `scout` | Read-only recon: trust map, invariants, idiom census, repo-specific rules | Step 4, one per surface, parallel |
| `fuzzer` | Authors harnesses, corpora, and vectors from recon's invariants; runs nothing | Step 5, one per surface, parallel |
| `gremlin` | Executes scanners, synthesized rules, and harnesses per surface, and reads for what they miss | Step 6, one per surface node, parallel |
| `triager` | Dedups, minimizes, and classifies crashes | Step 7, once per crash batch |
| `challenger` | Read-only exploitability critic; sets the evidence tier | Step 8, once over the finding wisps |
| `hardener` | Applies approved patches and re-verifies | Step 10, only after explicit approval |
