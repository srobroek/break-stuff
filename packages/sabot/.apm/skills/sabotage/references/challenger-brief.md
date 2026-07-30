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
