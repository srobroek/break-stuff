# Report template

The step-8 output. Read the finding set from beads rather than from the agents'
replies, so the report matches the durable graph.

Every finding carries both axes and a bead ID, and a section that does not apply is
dropped rather than padded.

---

```markdown
# Break Stuff Report -- <target>

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
- `INVALID` -- the scanner or harness crashed, so nothing was tested
- `budget_exhausted` -- the harness hit its cap with coverage still climbing, and
  the remaining budget needed
- `N/A` -- no tool exists for this dimension on this stack

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

## PROVEN findings

Ordered by impact. Each row has a reproduction.

| # | Bead | Impact | Surface | Locus | Finding | Reproduce |
|---|---|---|---|---|---|---|
| 1 | brk-12 | CRITICAL | shell | `guard.py:88` | `env` prefix bypasses the rm-rf block | `fuzz-cli.py --target ... --vectors v.json` |

## REACHABLE findings

A path was traced from an entry point, with no reproduction available.

| # | Bead | Impact | Surface | Locus | Path from entry point |
|---|---|---|---|---|---|
| 4 | brk-15 | HIGH | code | `api.rs:41` | `handle_post` -> `parse_body` -> unchecked `alloc` |

## Chains

Two or more findings that combine to an impact none reaches alone, tiered at the
endpoint impact. The constituent findings keep their own rows above; a chain is an
additional finding, not a replacement. Drop this section when no chain was found.

| # | Bead | Endpoint impact | Constituents | Chain (hop -> hop) |
|---|---|---|---|---|
| 7 | brk-22 | CRITICAL | brk-15 (HIGH) + brk-18 (MEDIUM) | arbitrary write `brk-18` -> config read at `load.rs:30` -> code exec `brk-15` |

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
| 9 | brk-20 | HIGH | `config.py:22` | empty config file | traceback at startup instead of a clear error |

## Artifacts written

Every file is uncommitted. Committing is yours to decide.

| Path | Kind | Runs via |
|---|---|---|
| `tests/fuzz/fuzz_parse.py` | harness | `python -m atheris tests/fuzz/fuzz_parse.py` |
| `tests/fuzz/vectors-guard.json` | attack vectors | `fuzz-cli.py --target ... --vectors ...` |
| `.break-stuff/run-3/artifacts/crash-code-1.bin` | crash input | the reproduce command in brk-15 |

## Rules to keep

Rules recon wrote that are worth running after this campaign. Uncommitted, as
above.

| Rule | Invariant it guards | Findings | Graduate to | Status |
|---|---|---|---|---|
| `repo-raw-execute-outside-wrapper` | every query goes through `db.q()` | 2 PROVEN | `.semgrep/break-stuff-derived.yml` | ready |
| `repo-hook-must-decide` | every guard emits an explicit decision | 0 | `.semgrep/break-stuff-derived.yml` | opt-in; guards the invariant against future breakage |

## Remediation order

Ordered by impact over effort, with the bead to work from.

| Order | Bead | Fix | Effort | Verifies by |
|---|---|---|---|---|
| 1 | brk-12 | anchor the guard on the tokenized command rather than the raw string | small | the existing vectors file, which must go to 0 findings |

## Accepted risks honored

Suppressions and documented decisions the campaign respected rather than
re-reported.

| Source | Rule | Where |
|---|---|---|
```

---

## Rules for filling it

MUST Put coverage before findings. A report that leads with findings and buries its gaps reads as complete when it is not.
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
