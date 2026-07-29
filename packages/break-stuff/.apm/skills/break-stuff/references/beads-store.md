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

| Object | Beads representation |
|---|---|
| Run | one **epic** bead; metadata `run_id`, `target`, `base_sha`, `budget` (JSON), `artifacts` (abs dir) |
| Surface node | **task** bead, `--parent <epic>`, label `brk-surface`, metadata `surface`, `scope` (JSON array of globs) |
| Harness wisp | **task** bead, `--parent <surface>`, labels `brk-harness` + `non-work`, metadata `entry_point`, `runner`, `harness_path` |
| Crash wisp | **task** bead, `--parent <surface>`, labels `brk-crash` + `non-work`, metadata `input_path`, `stack_hash` |
| Finding wisp | **task** bead, `--parent <surface>`, label `brk-finding`, metadata `tier`, `impact`, `locus`, `surface` |
| Decision | **decision** bead under the epic, for an accepted-risk or scope ruling that outlives one finding |

```
EPIC=$(bd create "break-stuff run-<id>" --type epic --silent \
  --metadata '{"run_id":"run-<id>","target":"<resolved target>","base_sha":"<sha>","budget":{"wall_s":60,"jobs":4,"mem_mb":2048},"artifacts":"<abs>/.break-stuff/run-<id>/artifacts"}')
S1=$(bd create "surface: shell" --parent "$EPIC" --labels brk-surface --silent \
  --metadata '{"surface":"shell","scope":["packages/*/scripts/**","**/*.sh"]}')
bd dep cycles                 # must stay clean
```

MUST Label harness and crash wisps `non-work` as well as their own label. Generic ready and claim selectors exclude `non-work`, which keeps a coordination wisp out of any other agent's work queue.
MUST Use `--metadata` for stamps, since it merges with existing keys and never clobbers `surface` or `scope`.

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
bd list --parent <surface> --labels brk-harness --status open --json
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
bd create "finding: <one-line claim>" --parent <surface> --labels brk-finding --silent \
  --metadata '{"tier":"PROVEN","impact":"HIGH","locus":"src/auth/token.rs:88","surface":"code","cwe":"CWE-190","repro":"<abs path to minimized input>"}'
```

| Field | Values |
|---|---|
| `tier` | `PROVEN` (repro or traced exploit path) · `REACHABLE` (path traced, no repro) · `HARDENING` (no path, or tool-only) · `REFUTED` (challenger disproved it) |
| `impact` | `CRITICAL` · `HIGH` · `MEDIUM` · `LOW`, calibrated per surface doc |
| `locus` | `file:line`, always |
| `repro` | absolute path to the minimized input, when one exists |

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

| Question | Command |
|---|---|
| campaign status | `bd list --label brk-surface --parent <epic> --all --json` |
| all findings by tier | `bd list --label brk-finding --parent <epic> --all --json` then group by `metadata.tier` |
| one finding's story | `bd show <bead> --json` with `bd comments <bead>` |
| unexecuted harnesses | `bd list --label brk-harness --parent <epic> --status open --json` |
| coverage gaps | findings and surfaces carrying `state:budget_exhausted` or `state:invalid` |
| resume after crash | in-flight = `bd list --parent <epic> --status in_progress --json`; agent handle = bead `assignee` |
| close-out gate | `bd dep cycles` clean AND no `brk-harness` wisp left `open` AND every `brk-finding` carries a `tier` |

## Resume

A campaign resumes without re-running finished work:

1. Read the epic's `budget` metadata rather than re-asking the user, since the
   approved budget is durable.
2. List harness wisps still `open` and hand them to a fresh `gremlin`.
3. List crash wisps still `open` and hand them to a fresh `triager`.
4. List finding wisps with no `tier` and hand them to `challenger`.
5. Report from the graph.

MUST Verify a claim before stealing it. A wisp `in_progress` with a live assignee belongs to a running agent; treat it as dead only when the assignee's session is gone.
NOT Re-running an already-executed harness wastes the budget and produces duplicate crash wisps, so check `state:executed` before dispatch.
