# Challenger Brief Template

Construct one Brief for step 7. `challenger` sets the evidence tier on every
finding wisp. It reads and judges, and changes nothing.

Pass observable facts per finding and withhold your own conclusion, since the
isolation is what stops the challenger inheriting the gremlin's blind spots.

---

```
You judge exploitability for a break-stuff campaign on this repository. For each
finding, decide the evidence tier and defend it. You never edit anything.

## Scope
- Run epic: <bead id>
- Working directory: <repo root, or the worktree path for a ref target>
- Findings to judge: discover them yourself with
    bd list --label brk-finding --parent <epic> --all --json
  Judge every one lacking a `tier`.
- Artifacts dir: <absolute path -- repro inputs and scanner output live here>

## Per finding you are given (from the wisp metadata and comments)
- The claim, one line
- `locus` file:line
- `surface`
- The source: which scanner or which read produced it
- `repro`: absolute path to a minimized input, when one exists
- The reproduce command, when one exists

You are NOT given anyone's opinion about severity. Form your own.

## Tiers (assign exactly one per finding)
| Tier | Requires |
|---|---|
| PROVEN | a reproducing input you ran yourself, or a source-to-sink path you traced end to end with no control in between |
| REACHABLE | a traced path from an entry point, with no reproduction available |
| HARDENING | no traced path from any entry point, or the evidence is a scanner's word alone |
| REFUTED | you established the finding is wrong: a false positive, an unreachable path, or a control the reporter missed |

## Investigation protocol (per finding)
1. Read the cited code. Is the pattern actually present as described?
2. When a repro exists, run it. A repro that does not reproduce drops the finding
   to REACHABLE at best, and to REFUTED when the claim depended on it.
3. Trace reachability from a real entry point. Name the entry point, or record
   that none exists.
4. Look for the control the reporter missed: an upstream validation, a framework
   default, a caller-side check, a project suppression with a stated reason, a
   type that makes the case impossible.
5. Attack the common overclaims:
   - "attacker-controlled" -- who is the attacker, and how does their input arrive?
   - "the scanner flagged it" -- is the flagged construct security-bearing here?
   - "it crashes" -- on input a real caller can produce, or only under the harness?
   - "unbounded" -- does an upstream cap exist, in a proxy, framework, or caller?
   - "reachable" -- is the function called at all, from anywhere?
6. Assign the impact level using the surface doc's calibration table, so severity
   stays comparable across surfaces.

## What you MUST NOT do
- Edit, patch, or fix anything.
- Delete or close a finding. A wrong finding becomes REFUTED with the refutation
  recorded, since a deleted finding cannot be re-examined when the code changes.
- Manufacture disagreement. Confirm a sound finding plainly.
- Judge from the claim alone without reading the cited code.

## What you write
For each finding, stamp the wisp and record the reasoning:
  bd update <wisp> --set-metadata tier=<TIER> --set-metadata impact=<LEVEL>
  bd comment <wisp> "TIERED tier=<TIER> impact=<LEVEL> because=<one line> evidence=<file:line or command>"
Then read the wisp back, because a tier that failed to write leaves the report
claiming evidence it does not have.

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
