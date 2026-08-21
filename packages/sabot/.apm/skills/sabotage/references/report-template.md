# Report template

The step-8 output, and a rendering of the finding beads rather than a document
authored from the agents' replies. Every column below maps to a field in the finding
wisp schema in `beads-store.md`; a blank column means a missing field on a wisp, so
the fix is the stamp rather than the prose.

Every finding carries both axes and a bead ID, and a section that does not apply is
dropped rather than padded.

## Ordering, grouping, and counting

A run producing hundreds of findings needs an ordering rule, since the reader stops
partway down. Rank on the fields already on the wisp:

| Rank key | Order | Read from |
|---|---|---|
| 1. tier | PROVEN, REACHABLE, HARDENING, REFUTED | `tier` |
| 2. impact | CRITICAL, HIGH, MEDIUM, LOW | `impact` |
| 3. threat alignment | findings matching the epic's stamped `threat` first | `threat` on the epic against `cwe` on the wisp |
| 4. instance count | descending | `instance_count` on the group representative |
| 5. locus | lexical, so the order is stable across renders | `locus` |

One row per GROUP, never per instance. A group's row shows the representative's locus
and its `instance_count`, and its instances go to a nested list or an appendix.

MUST Order every findings table by the five keys above. An unordered table of 251 rows hides its own CRITICAL rows.
MUST Use the epic's stamped `threat` as rank key 3. One run stamped a threat model and then ordered by nothing, so the model influenced no output.
MUST Report three counts separately: groups, instances, and wisps. One run reported 251 findings where the group count was near 30, which overstates the defect count and understates each one.
MUST Render every table from the beads query, and cite the query in the report footer. A report typed from agent replies drifts from the graph, and the graph is what the next campaign resumes from.

---

```markdown
# Sabot Report -- <target>

**Target:** <whole repo | module `src/x` | hook `guard.py` | diff | commit `abc123` | PR #42>
**Scope mode:** <quick|full|audit-only|harness-only>  ·  **Base ref:** <none | `main`>
**Surfaces:** <list>  ·  **Run epic:** <bead id>  ·  **Date:** <YYYY-MM-DD>
**Budget used:** <n> harnesses, <wall_s>s each, <total>s total of <approved>s

## Summary

| Tier | CRITICAL | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| PROVEN | | | | |
| REACHABLE | | | | |
| HARDENING | | | | |
| REFUTED | | | | |

Headline: <one sentence, the single thing to fix first, or the strongest statement
the evidence supports when nothing was found>

## Coverage

State this before the findings, because a reader who trusts an incomplete audit is
worse off than one who knows its limits.

| Surface | Scanners run | Scanners skipped | Harnesses run / written | Gaps |
|---|---|---|---|---|
| shell | shellcheck, opengrep | checkov (not installed) | 4 / 4 | none |
| code | bandit, ruff | CodeQL (opt-in, declined) | 3 / 5 | 2 entry points unfuzzed: `parse_v2`, `decode_frame` |

Gap reasons, stated precisely:
- `SKIPPED (scoped)` -- global-class analysis on a bounded target
- `SKIPPED (not installed)` -- with the install command
- `SKIPPED (budget)` -- named the tool recon aimed ON that the clock displaced
- `NOT EXECUTED (requires network)` -- the tool or its ruleset fetches from a
  registry, and every container runs `--network none`. Say whether the step-8.6
  network stage was granted, declined, or never offered, since that decides whether
  the gap was closable at all (`references/network-stage.md`)
- `INVALID` -- the scanner or harness crashed, so nothing was tested
- `NOT EXECUTED` -- the tool or harness never ran; the reason distinguishes absent
  from unreachable from never-written
- `UNTESTED` -- it ran and produced no verdict, because its benign control failed or
  its assertion never fired
- `budget_exhausted` -- the harness hit its cap with coverage still climbing, and
  the remaining budget needed
- `N/A` -- no tool exists for this dimension on this stack

### NOT-EXECUTED register

One row per dimension the campaign did not exercise, with a reason on every row.
Every entry here is a limit on the report's central claim, so the register is
mandatory even when the run found plenty.

| Dimension | Reason | Consequence for the claim |
|---|---|---|
| interprocedural taint (CodeQL) | OFF on cost | every dataflow path in the report was traced by hand |
| stock ruleset for the code surface | `requires network`, and every container runs `--network none` | only locally-authored rules ever ran, so no standard pack was applied on any surface |
| a harness set on one surface | INVALID on a resource limit (SIGKILL/137, ENOSPC, image I/O error, lost log) | the surface is UNTESTED, in both directions |
| justfile recipes | the runner is absent from every image | UNTESTED |
| exhaustive interleavings | the model checker is absent from the lockfile | concurrency findings are sampled, not exhaustive |
| power-loss durability | untestable in-process | the durability half of the claim is unmeasured |
| git-history secret scan | the worktree `.git` is a pointer outside the mount, so the scanner saw 0 commits and exited 0 | INVALID, never clean |
| N of M command handlers | unreachable by any harness | the boundary is read-traced only |
| one crate | every executable vector fills the disk, which the authoring ban forbids | accepted gap, deliberate |

### Tool-integrity certification

Per surface, the evidence that each tool ran. A surface without this row is a gap.

| Surface | Compiler verified | Test binaries at nonzero counts | `running 0 tests` count | Scanner results parsed | Any result resting on a wrapper exit code |
|---|---|---|---|---|---|
| code | `/usr/local/cargo/bin/cargo` 1.97.1 | 13, named | 0 | JSON, 38 files | none |

### Structurally closed classes

Classes no finding could exist in, with the census that establishes it. "We found no
X" and "X is impossible here" are different claims, and only the second is worth
reading.

| Class | Closed by | Census | Role affected |
|---|---|---|---|
| memory safety | `unsafe_code = "forbid"` at `Cargo.toml:31` | 0 `unsafe` blocks over 44 crates | triager: 0 crash wisps over 15 node-runs, no-op |

### Premise corrections

Facts the campaign's own dispatch asserted and later measured false. Each one cost
agent time, and the count is a measure of how well the run was aimed.

| Premise as dispatched | What is true | Cost |
|---|---|---|
| a coverage gap at `seed-builder/src/main.rs:31` | a `//!` doc-comment line; nothing was ever there | 4 agents told to chase it |
| the install path is unreachable | no shipped entry point reaches it, and it IS production source called from `installer.rs:15` | both prior claims half wrong; 4 findings reclassified as pre-wiring defects |

## Recon

What the campaign learned about this repo before attacking it. A report without
this section is a stock-pack sweep rather than an audit.

| Artifact | Count | Where |
|---|---|---|
| Trust boundaries mapped | 14 | `<artifacts>/recon-trust-map.md` |
| Invariants derived | 9 | `<artifacts>/recon-invariants.md` |
| Idiom deviations found | 3 of 47 handlers skip the shared validator | `<artifacts>/recon-census.md` |
| Repo-specific rules written | 5 | `<artifacts>/rules/` |

Finding provenance, which shows whether recon did the work:

| Source | Findings | Share |
|---|---|---|
| Repo-specific rules from recon | 6 | 40% |
| Harnesses asserting a recon invariant | 4 | 27% |
| Standard packs, placed on a path by the trust map | 3 | 20% |
| Standard packs, unplaced (HARDENING) | 2 | 13% |

## Systemic patterns

The step-8.5 output, placed above the individual findings because a shape repeating
across nodes is a stronger statement than any of its instances. Drop the section only
when the synthesis pass found no `root_cause` spanning two nodes.

| # | Bead | Impact | Pattern | Instances | Nodes | What it says about the codebase |
|---|---|---|---|---|---|---|
| P1 | sab-40 | HIGH | a safety mechanism is built and never wired to a caller, and its self-check reports success | 8 | code, shell, infra | the review process accepts a mechanism's existence as evidence it runs |

## PROVEN findings

Ordered by impact. Each row has a reproduction.

| # | Bead | Impact | Surface | Locus | Finding | Reproduce |
|---|---|---|---|---|---|---|
| 1 | sab-12 | CRITICAL | shell | `guard.py:88` | `env` prefix bypasses the rm-rf block | `fuzz-cli.py --target ... --vectors v.json` |

## REACHABLE findings

A path was traced from an entry point, with no reproduction available.

| # | Bead | Impact | Surface | Locus | Path from entry point |
|---|---|---|---|---|---|
| 4 | sab-15 | HIGH | code | `api.rs:41` | `handle_post` -> `parse_body` -> unchecked `alloc` |

## Chains

Two or more findings that combine to an impact none reaches alone, tiered at the
endpoint impact. The constituent findings keep their own rows above; a chain is an
additional finding, not a replacement. Drop this section when no chain was found.

| # | Bead | Endpoint impact | Constituents | Chain (hop -> hop) |
|---|---|---|---|---|
| 7 | sab-22 | CRITICAL | sab-15 (HIGH) + sab-18 (MEDIUM) | arbitrary write `sab-18` -> config read at `load.rs:30` -> code exec `sab-15` |

## HARDENING

No traced path, or scanner evidence alone. Real, and lower priority than the
above.

| # | Bead | Impact | Surface | Locus | Finding | Why untiered higher |
|---|---|---|---|---|---|---|

## REFUTED

Kept deliberately, so the next campaign does not re-litigate them.

| # | Bead | Original claim | Refutation | Evidence |
|---|---|---|---|---|

## Robustness findings

Break-stuff reports stability defects alongside security ones. These carry no
attacker path and are still real.

| # | Bead | Impact | Locus | Breaks on | Consequence |
|---|---|---|---|---|---|
| 9 | sab-20 | HIGH | `config.py:22` | empty config file | traceback at startup instead of a clear error |

## Artifacts written

Every file is uncommitted. Committing is yours to decide.

| Path | Kind | Runs via |
|---|---|---|
| `tests/fuzz/fuzz_parse.py` | harness | `python -m atheris tests/fuzz/fuzz_parse.py` |
| `tests/fuzz/vectors-guard.json` | attack vectors | `fuzz-cli.py --target ... --vectors ...` |
| `.sabot/run-3/artifacts/crash-code-1.bin` | crash input | the reproduce command in sab-15 |

## Rules to keep

Rules recon wrote that are worth running after this campaign. Uncommitted, as
above.

| Rule | Invariant it guards | Findings | Graduate to | Status |
|---|---|---|---|---|
| `repo-raw-execute-outside-wrapper` | every query goes through `db.q()` | 2 PROVEN | `.semgrep/sabot-derived.yml` | ready |
| `repo-hook-must-decide` | every guard emits an explicit decision | 0 | `.semgrep/sabot-derived.yml` | opt-in; guards the invariant against future breakage |

## Remediation order

Ordered by impact over effort, with the bead to work from.

| Order | Bead | Fix | Effort | Verifies by |
|---|---|---|---|---|
| 1 | sab-12 | anchor the guard on the tokenized command rather than the raw string | small | the existing vectors file, which must go to 0 findings |

## Accepted risks honored

Suppressions and documented decisions the campaign respected rather than
re-reported.

| Source | Rule | Where |
|---|---|---|

Suppression accounting, since the unreasoned count is itself a finding:

| Measure | Count | Effect |
|---|---|---|
| total suppressions | 331 | the size of the deliberately-unscanned surface |
| with a stated reason | 249 | each caps a related finding at HARDENING |
| with no stated reason | 82 | capped nothing; reported as one HARDENING finding |
| documented accepted risks | 7 | cited rather than re-reported |
```

---

## Rules for filling it

MUST Write the report with every gap still open. This document exists to state them: an unrun harness, an uncovered surface, an untiered finding, and an INVALID run each get a row here, and step 10 fixes them on explicit approval. A report withheld until its run came back clean would only ever describe a clean run.
MUST Put coverage before findings. A report that leads with findings and buries its gaps reads as complete when it is not.
MUST Fill the NOT-EXECUTED register with a reason on every row, even on a run that found plenty. A dimension the campaign never exercised is a limit on its central claim, and a limit stated only as a count reads as coverage.
MUST Separate NOT EXECUTED from UNTESTED from INVALID from clean. A locus whose benign control failed has no verdict; a locus whose harness was never written was never tested; a locus whose scanner crashed was not scanned. All three read as clean when collapsed into one number.
MUST Include the tool-integrity certification per surface, and mark a surface UNVERIFIED where the gremlin did not supply one. A wrapper returning 0 while running nothing was measured three separate ways in one run, so an exit code supports no coverage claim.
MUST Report a structurally closed class with its census rather than omitting it, and say which role it left with nothing to do.
MUST Include the premise-corrections table whenever an agent corrected a dispatched premise. Premise error is a property of the run's own aim, and it stays invisible without a place to record it.
MUST Put the systemic-patterns section above the findings whenever step 8.5 filed a pattern wisp, and state its instance count and node span. A pattern rendered as N separate rows deep in a long table reads as N unrelated bugs.
MUST Cite a bead ID on every finding, since that is what survives the session and what a fix can be tracked against.
MUST Keep the REFUTED section even when it is the only content. A campaign that found nothing real still tells the reader what was checked.
MUST Set the budget actually used against the budget approved, so the reader can judge whether more time would find more.
MUST Report a robustness finding at its own impact level. Discounting it for lacking an attacker understates a real defect.
MUST List every rule worth keeping with its graduation path. Rules outlive the report; a rule left in the artifacts dir stops running when the campaign ends.
MUST Include the finding-provenance table. A campaign whose findings came only from standard packs did no recon. The report says so plainly rather than presenting a stock sweep as an audit.
NOT Never reprint code, diffs, or file contents. Evidence is a `file:line` and a command.
NOT Never present a scanner count as a finding count. Many flagged lines from one rule with no traced path collapse to one HARDENING row.

## When nothing was found

Say so plainly, and make the claim precise about what was actually exercised:

> No PROVEN or REACHABLE findings. 12 harnesses ran to their caps with coverage
> plateaued across 4 surfaces; 3 entry points went unfuzzed (listed under
> Coverage), and CodeQL was declined, so interprocedural taint was not checked.

MUST Bound the claim by what ran. "Nothing found" without the coverage table is an assertion the campaign cannot support.
