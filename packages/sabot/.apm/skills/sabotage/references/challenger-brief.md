# Challenger Brief Template

Construct one Brief for step 7. `challenger` sets the evidence tier on every
finding wisp. It reads and judges, and changes nothing.

Pass observable facts per finding and withhold your own conclusion, since the
isolation is what stops the challenger inheriting the gremlin's blind spots.

---

```
You judge exploitability for a sabot campaign on this repository. For each
finding, decide the evidence tier and defend it. You never edit anything.

## Scope
- Run epic: <bead id>
- Working directory: <repo root, or the worktree path for a ref target>
- Findings to judge: discover them yourself with
    bd list --label sab-finding --metadata-field run_id=<id> --all --json
  Judge every one lacking a `tier`.
- Artifacts dir: <absolute path -- repro inputs and scanner output live here>

## Per finding you are given (from the wisp metadata and comments)
- The claim, one line
- `locus` file:line
- `surface`
- `source`: what produced it (`synthesized-rule` · `stock-pack` · `harness` · `read`)
- `path`: the reachability chain the gremlin recorded, `entry -> ... -> sink` with a
  file:line per hop. Verify this rather than re-tracing from scratch; re-derive only
  when it is absent.
- `repro`: absolute path to a minimized input, when one exists
- The reproduce command, when one exists

You are NOT given anyone's opinion about severity. Form your own.

## Chaining
After every finding carries a tier, read `references/escalation.md` and look for
chains: where one finding's primitive reaches what another needs. File each chain as
a NEW finding wisp citing the constituent ids, tiered at its endpoint impact; the
constituents stay unchanged (the no-delete rule holds). Trace every hop against the
recorded `path` metadata before filing; an unverified hop makes it a HARDENING note.

## Preconditions on tiering above HARDENING
Check each before you assign a tier. A finding failing any of them is capped at
HARDENING with the failed precondition named as the reason.

| Precondition | How to check | Why |
|---|---|---|
| the harness that produced it had a PASSING benign control | `control_path` on the harness wisp, plus the control's result in the gremlin's coverage wisp | a hostile failure beside a failing control confirms and refutes nothing, so the locus is UNTESTED |
| the assertion fired | the runner output names the assertion | two assertions in one test stop at the first panic, leaving the second unfired while the test appears to have run |
| the evidence is not profile-dependent | the harness asserts a VALUE, not a panic | a `debug_assert!` and an unchecked overflow both measure the build profile when release sets no `overflow-checks` |
| a suppression covering the locus states a reason | the step-3.5 suppression list | a reasoned suppression caps at HARDENING; an unreasoned one caps nothing, so tier on the evidence |
| the tool that produced it actually ran | the gremlin's tool-integrity certification | an UNVERIFIED or absent certification makes every tool-sourced finding on that surface HARDENING |
| the run that produced it hit no resource limit | the coverage wisp for SIGKILL/137, an OOM message, ENOSPC, an image I/O error, or a lost log | the same rule as control-must-pass: an INVALID run measures nothing in either direction, so it neither supports a tier nor clears a locus |

MUST Refuse to tier any finding from a run that hit a resource limit, and refuse equally to read that run's absence of findings as clean. Both directions rest on the same evidence, and there is none.

## Dedup by citation, never by deletion
When two surfaces filed the same locus, keep the first and record the second as an
independent confirmation on it (`bd comment` plus `relates-to`), then close the
duplicate with reason `duplicate` and a pointer. Independent confirmation raises
confidence in the surviving finding, and it is lost when the duplicate is deleted or
when both rows stand as separate findings.

Dedup mechanically on `dedup_key` (`<surface>:<locus>:<class>`) rather than by eye.
Overlapping surface globs put the same locus in two nodes' scope, so the same defect
arrives twice with two wisp ids and two titles:

    bd list --label sab-finding --metadata-field run_id=<id> --all --json > /tmp/f.json
    jq -r '.[].metadata.dedup_key' /tmp/f.json | sort | uniq -d

Every key printed by that command is a duplicate set to collapse before you tier.

An EMPTY result from it is a broken query until you have checked that the keys exist:

    jq -r '[.[] | select(.metadata.dedup_key)] | length' /tmp/f.json

Zero there means the gremlins filed without the key, so `uniq -d` had nothing to compare
and the surface reads as duplicate-free. Fall back to `locus` plus defect class, stamp
`dedup_key` on every finding you judge so the next pass has it, and report the missing
key as a gap. Measured: one campaign filed 383 findings with no `dedup_key` on any of
them, over seven genuine cross-surface duplicate loci that the prescribed command could
not see.

MUST Re-verify a dedup claim you inherited. One run carried an unverified dedup between two surfaces because the wisp list was unreadable at the time, and the tiering pass owns that check.

## Group by root cause, and tier the group once
Distinct loci sharing one defect are one issue with many instances. Normalize
`root_cause` across them to a single phrase, pick the instance with the strongest
evidence as the representative, and tier the group at that instance's tier:

    bd update <representative> --metadata '{"group_role":"representative","instance_count":<n>}'
    bd update <each other> --metadata '{"group_role":"instance","group_of":"<representative>"}'

MUST Normalize `root_cause` to one phrase per group before you tier. In one run, 224 loci collapsed onto a single `unwrap` at one boundary, done by hand at report time, so the finding count read as 251 issues.
MUST Tier the representative and inherit the tier onto the instances, then state the instance count on the representative. Tiering 224 instances separately spends the pass on one defect and buries the rest.
NOT Never collapse instances that differ in tier or in fix. A shared symptom with two fixes is two groups.

## Tiers and investigation protocol
Follow the Tiers table, the per-finding investigation protocol (including the
`path`-verify step and the overclaim attacks), and the MUST-NOT list in your agent
definition. This Brief supplies the per-run facts; the standing method lives in the
agent def, so it is stated once and cannot drift from it.

## What you write
For each finding, stamp the wisp with a single merging `--metadata` blob (never
`--set-metadata`, which `beads-store.md` bans because it clobbers sibling keys) and
record the reasoning:
  bd update <wisp> --metadata '{"tier":"<TIER>","impact":"<LEVEL>","by":"challenger"}'
  bd comment <wisp> "TIERED tier=<TIER> impact=<LEVEL> by=challenger because=<one line> evidence=<file:line or command>"
Then read the wisp back, because a tier that failed to write leaves the report
claiming evidence it does not have. Stamp `by=challenger` so the report marks the
finding independently challenged; a self-tier (`by=self`) is the inline-only path in
`workflow.md` step 8.

## Return
The Challenger Output format from your agent definition: a verdict line with tier
counts, a per-finding table, and the refutation rationale for anything you moved
down.
```

---

## Filling guidance

- **Withhold your own verdict.** Hand over facts alone, since a Brief that says
  "this looks critical" gets that answer back.
- **Point at the graph, not a list.** The challenger reads its work list from
  beads, so a resumed campaign finds exactly the untiered findings.
- **Let one challenger see every surface.** Cross-surface context is what catches
  the shell finding whose severity only shows in the code surface.
- **Refute rather than delete.** A REFUTED finding with a recorded reason is how
  the next campaign avoids re-litigating the same false positive.
