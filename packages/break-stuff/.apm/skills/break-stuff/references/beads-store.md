# Beads store: run graph, wisps, handoff, resume

A campaign's state lives in the project's beads database (the `bd` CLI). One
database is shared by every worktree, so agents read and write live state with
plain `bd` commands. Large payloads (harness source, crash inputs, scanner JSON)
are files under `<primary>/.break-stuff/run-<id>/artifacts/`; bead comments cite
them by absolute path.

Beads is mandatory. A finding that exists only in an agent's reply dies with the
session, and a campaign that cannot resume is a campaign that must restart.

## Prerequisite (checked once, at run start)

```
command -v bd >/dev/null || { echo "break-stuff requires the beads CLI (bd)"; exit 1; }
bd info >/dev/null 2>&1 || bd init --stealth --prefix brk
```

No `bd` on PATH stops the run: tell the user to install beads. There is no
fallback store. A present `bd` with no database gets `bd init --stealth --prefix
brk`, which is git-invisible (writes `.git/info/exclude`, leaves `git status`
clean).

## Objects

Every campaign bead carries the same `run_id` metadata as the epic. Rollup
queries filter on it, since a rollup by parent or label alone breaks on bd 1.1.2:
`--parent <epic>` returns only direct children (surface nodes), so a finding two
levels down never appears, and a child inherits its parent's labels, so a
label-only query over the shared database over-selects and bleeds across
concurrent campaigns. The `run_id` field scopes every rollup to one run.

| Object | Beads representation |
|---|---|
| Run | one **epic** bead; metadata `run_id`, `target`, `base_sha`, `budget` (JSON), `artifacts` (abs dir) |
| Surface node | **task** bead, `--parent <epic>`, label `brk-surface`, metadata `run_id`, `surface`, `scope` (JSON array of globs) |
| Harness wisp | **task** bead, `--parent <surface>`, labels `brk-harness` + `non-work`, metadata `run_id`, `entry_point`, `runner`, `harness_path`, `input_shape` |
| Crash wisp | **task** bead, `--parent <surface>`, labels `brk-crash` + `non-work`, metadata `run_id`, `input_path`, `stack_hash` |
| Finding wisp | **task** bead, `--parent <surface>`, label `brk-finding`, metadata `run_id`, `tier`, `by`, `source`, `impact`, `locus`, `surface`, `path` |
| Coverage record | **task** bead, `--parent <surface>`, label `brk-coverage` + `non-work`, metadata `run_id`, `scanners_run`, `scanners_skipped`, `harnesses_run`, `harnesses_total`, one per surface node |
| Decision | **decision** bead under the epic, for an accepted-risk or scope ruling that outlives one finding |

```
# Capture the id with --json | jq -r .id. Do NOT use --silent to capture an id:
# on bd 1.1.2 --silent prints a multi-line status block, so EPIC becomes
# "  Status: open" and every child create fails "parent issue not found",
# a silently broken run graph. --json emits a parseable object; jq pulls the id.
EPIC=$(bd create "break-stuff run-<id>" --type epic --json \
  --metadata '{"run_id":"run-<id>","target":"<resolved target>","base_sha":"<sha>","budget":{"wall_s":60,"jobs":4,"mem_mb":2048},"artifacts":"<abs>/.break-stuff/run-<id>/artifacts"}' \
  | jq -r '.id')
# Every child carries run_id=run-<id> too, since rollups filter on it (see below).
S1=$(bd create "surface: shell" --parent "$EPIC" --labels brk-surface --json \
  --metadata '{"run_id":"run-<id>","surface":"shell","scope":["packages/*/scripts/**","**/*.sh"]}' \
  | jq -r '.id')
bd dep cycles                 # must stay clean
```

MUST Capture a bead id with `bd create ... --json | jq -r '.id'`, never with `--silent`. On bd 1.1.2 `--silent` prints a status block rather than a bare id, so the capture is garbage and the run graph is silently broken from the first child.
MUST Stamp `run_id` on every campaign bead, matching the epic's. Rollups filter on it (see Reading the run), and a bead created without it is invisible to every rollup, so its harness never runs or its finding never reports.
MUST Label harness, crash, and coverage wisps `non-work` as well as their own label, then discover them by their own label rather than by `bd ready`. On bd 1.1.2 `bd ready` still returns a `non-work` wisp, so a discovery query keys on the specific label (`brk-harness`) plus the surface parent, not on the ready queue.
MUST Use `--metadata` for stamps, since it merges with existing keys and never clobbers `surface` or `scope`.
MUST Write `--label` (singular) on every `bd list`. On bd 1.1.2 `bd list --labels` is a hard error, so a discovery command written with the plural silently fails and the agent finds nothing. Only `bd create` takes `--labels`.

## Handoff chain

Each arrow is a durable write, so the receiving agent reads its input from the
graph rather than from a parent's prose.

| Step | Writer | Creates | Claimed by |
|---|---|---|---|
| 4 | `fuzzer` | harness wisp per entry point | `gremlin` for that surface |
| 5 | `gremlin` | crash wisp per distinct crash, finding wisp per non-crash finding | `triager` (crashes), `challenger` (findings) |
| 6 | `triager` | finding wisp per minimized crash, closes the crash wisp | `challenger` |
| 7 | `challenger` | tier stamp on each finding wisp | main thread at report time |
| 9 | `hardener` | patch record on the finding wisp | main thread for verification |

A `gremlin` discovers its work with:

```
bd list --parent <surface> --label brk-harness --status open --json
bd update <harness-wisp> --claim        # atomic, first-wins, sets assignee
```

## State mapping

`bd set-state` owns the `state:` label dimension: each transition deletes the
prior `state:<value>` label, adds the new one, and emits an event bead as the
transition record.

| Enum state | Bead status | `state:` label | Set by |
|---|---|---|---|
| `pending` | `open` | `state:pending` | creator at `bd create` |
| `claimed` | `in_progress` | `state:claimed` | claim-holder after `bd update --claim` |
| `executed` | `in_progress` | `state:executed` | `gremlin` after a harness runs to its cap |
| `minimized` | `in_progress` | `state:minimized` | `triager` after the input shrinks |
| `tiered` | `in_progress` | `state:tiered` | `challenger` after the verdict |
| `patched` | `in_progress` | `state:patched` | `hardener` after the verification re-run |
| `reported` | `closed` | `state:reported` | main thread at report emit |
| `budget_exhausted` | `open` | `state:budget_exhausted` | `gremlin` when a harness hits its cap with coverage still growing |
| `invalid` | `blocked` | `state:invalid` | `gremlin` when a scanner or harness crashed rather than finding something |

```
bd set-state <bead> state=<name> --reason "<why>"
bd update <bead> --status <status>          # only where status changes
```

MUST Distinguish `budget_exhausted` from `reported`. The first says coverage was still growing when the clock ran out, which is a coverage gap the report has to state.
MUST Distinguish `invalid` from a clean result. A scanner that crashed found nothing because it never ran.

## Finding wisp shape

Every finding carries both axes plus its locus, written as metadata so the report
generator reads structure rather than prose:

```
FINDING=$(bd create "finding: <one-line claim>" --parent <surface> --labels brk-finding --json \
  --metadata '{"run_id":"run-<id>","tier":"PROVEN","by":"challenger","source":"synthesized-rule","impact":"HIGH","locus":"src/auth/token.rs:88","surface":"code","cwe":"CWE-190","repro":"<abs path to minimized input>","path":"handle_post -> parse_body -> alloc @ api.rs:41"}' \
  | jq -r '.id')
```

| Field | Values |
|---|---|
| `tier` | `PROVEN` (repro or traced exploit path) · `REACHABLE` (path traced, no repro) · `HARDENING` (no path, or tool-only) · `REFUTED` (challenger disproved it) |
| `by` | who set the tier: `challenger` (an independent pass) or `self` (the finder tiered its own finding inline). The report headlines a `self` tier as unchallenged. |
| `source` | what produced the finding: `synthesized-rule` · `stock-pack` · `harness` · `read`. The report's provenance table groups on it, so a stock-only sweep is visible rather than presented as an audit. |
| `impact` | `CRITICAL` · `HIGH` · `MEDIUM` · `LOW`, calibrated per surface doc |
| `locus` | `file:line`, always |
| `path` | the reachability chain the gremlin recorded, `entry -> ... -> sink` with a `file:line` per hop, so the challenger verifies the recorded path rather than re-tracing it |
| `repro` | absolute path to the minimized input, when one exists |

MUST Stamp `by=self` when the agent that found a finding also tiered it, and `by=challenger` when an independent pass did. The report cannot tell a self-tier from a challenged one otherwise, so a self-judged finding reads as independently confirmed.
MUST Record `source` on every finding, since a report whose findings are all `source=stock-pack` did no recon, and the provenance table can only say so when the field is on the wisp rather than in prose.

MUST Never delete a finding wisp. A refuted finding is stamped `tier=REFUTED` with the refutation in a comment, then closed with reason `refuted`, because a deleted finding cannot be re-examined when the code changes.
MUST Re-read a finding wisp after stamping a tier. A tier that failed to write leaves the report claiming evidence it does not have.

## Events and audit

Every material verb (`authored executed crashed minimized tiered refuted patched
gap`) is recorded by the acting agent, with identity via `BEADS_ACTOR`, as two
writes:

```
bd audit record --actor <actor> --kind tool_call --tool-name brk.<verb> \
  --issue-id <bead> --exit-code 0
bd comment <bead> "<VERB> <surface> field=… output_ref=<abs artifact path>"
```

Full harness source, scanner JSON, and crash inputs go to
`<artifacts>/<surface>-<verb>-<n>.<ext>`; the comment carries the absolute path
rather than the content.

## Reading the run

Surface nodes are direct children of the epic, so `--parent <epic>` reaches them.
Harnesses, findings, crashes, and coverage records are grandchildren (children of a
surface node), so `--parent <epic>` never returns them on bd 1.1.2; roll them up by
their own label scoped to the run with `--metadata-field run_id=<id>`.

| Question | Command |
|---|---|
| campaign status | `bd list --label brk-surface --parent <epic> --all --json` |
| all findings by tier | `bd list --label brk-finding --metadata-field run_id=<id> --all --json` then group by `metadata.tier` |
| one finding's story | `bd show <bead> --json` with `bd comments <bead>` |
| unexecuted harnesses | `bd list --label brk-harness --metadata-field run_id=<id> --status open --json` |
| coverage record per surface | `bd list --label brk-coverage --metadata-field run_id=<id> --all --json` |
| coverage gaps | harnesses and findings carrying `state:budget_exhausted` or `state:invalid`: `bd list --metadata-field run_id=<id> --all --json` filtered on the `state:` label |
| resume after crash | in-flight = `bd list --metadata-field run_id=<id> --status in_progress --all --json`; agent handle = bead `assignee` |
| close-out gate | `bd dep cycles` clean AND every detected surface node has a `brk-coverage` record AND no `brk-harness` wisp left `open` or `blocked` AND every `brk-finding` carries a `tier` |

MUST Roll up grandchildren with `--metadata-field run_id=<id>`, never `--parent <epic>`. On bd 1.1.2 `--parent` returns direct children only, so an epic-parent query for findings or harnesses returns an empty set and the close-out gate passes over unrun, untiered work.
MUST Gate close-out on a `brk-coverage` record existing for every detected surface. A gremlin that died before writing coverage leaves a surface untested, and without this check the report simply omits it and reads as clean.
MUST Count a `blocked` (INVALID) harness as unfinished at the gate, not only an `open` one, since an INVALID harness is an untested entry point that would otherwise pass a gate keyed on `open` alone.

## Raw export: the graph IS the persistence

The run graph is the campaign's single store, so no agent writes a parallel
findings file. One command emits the whole run as parseable JSON for a machine
reader, a diff against a later run, or an archive:

```
bd list --metadata-field run_id=<id> --all --json > <artifacts>/run-<id>.json
```

That object holds every surface node, harness, crash, finding, and coverage record
with its metadata, which is what lets the report generator read structure rather
than prose and what carries work between agents: each of `scout`, `fuzzer`,
`gremlin`, `triager`, and `challenger` reads its inputs from the wisps a prior agent
filed (see Handoff chain) rather than from a parent's reply. Correlation is by
`run_id` and by parent, so a finding traces to its surface, its harness, and its
crash input without a join table.

Only the oversized payloads stay outside the graph, cited by absolute path in a bead
comment: the recon document, scanner JSON, harness source, and crash-input binaries.
A bead holds the structure and the pointer; the file holds the bytes. This keeps
every `bd list` query small while the blobs remain one `cat` away.

MUST Emit the raw `run-<id>.json` alongside the report, since it is the parseable form of everything the markdown summarizes and the only export a later campaign can diff against.
NOT Never write a finding, tier, or coverage fact to a side file the graph does not also hold. A fact that lives only in a file breaks correlation and dies outside the run, which is the failure the graph exists to prevent.

## Resume

A campaign resumes without re-running finished work. Every list below scopes to the
run with `--metadata-field run_id=<id>`:

1. Read the epic's `budget` metadata rather than re-asking the user, since the
   approved budget is durable.
2. Hand a fresh `gremlin` every harness wisp that is `open`, or `blocked` with
   `state:invalid` (a crashed scanner or unbuilt harness the previous run never
   completed), or `open` with `state:budget_exhausted` (ran out of clock with
   coverage climbing). Skip any carrying `state:executed`.
3. List crash wisps still `open` and hand them to a fresh `triager`.
4. List finding wisps with no `tier` and hand them to `challenger`.
5. Report from the graph.

MUST Include `state:invalid` and `state:budget_exhausted` harnesses in the resume set. An INVALID harness is `blocked` rather than `open`, so a resume that lists only `open` harnesses silently drops the exact entry points the previous run failed to test.
MUST Verify a claim before stealing it. A wisp `in_progress` with a live assignee belongs to a running agent; treat it as dead only when the assignee's session is gone.
NOT Re-running an already-executed harness wastes the budget and produces duplicate crash wisps, so check `state:executed` before dispatch.
