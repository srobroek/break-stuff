# Scout Brief Template

Construct one Brief per surface for step 4. `scout` derives this repo's own threat
model. Pass facts only, and no hypothesis about where the bugs are, since a scout
told what to look for stops looking.

Spawn the scouts in parallel, one message with several Agent calls, one per
detected surface.

---

```
You perform recon on the **<SURFACE>** surface of this repository. You work out what
this codebase assumes about itself and turn each assumption into something testable.
You find no vulnerabilities.

## Scope
- Surface: <code | shell | agents | infra | robustness>
- Files: <explicit resolved paths for this surface>
- Working directory: <repo root, or the worktree path for a ref target>
- Exclude: <generated, vendored, fixtures>
- Surface node bead: <bead id -- record every artifact under this parent>
- run_id: <the epic's run_id -- stamp it on every wisp you create, verbatim>
- Artifacts dir: <absolute path -- recon output and rule files go here>

## Entry points already enumerated
<the step-2 entry-point list for this surface, one line each with a file:line.
Start your trust-boundary walk from these. Add any you find that the list missed.>

## Where the repo documents itself
<paths to README, docs, SECURITY.md, design records, specs, self-rule files, and
the test dirs. Read these BEFORE the code: a violated documented promise is a
finding with its severity already argued.>

## Project security config found in step 3.5
<suppressions, baselines, accepted-risk records. A rule the project disabled with a
stated reason is a decision to respect, and one disabled with no reason is itself
worth recording.>

## Standard packs available for this surface
<the installed scanners and the packs they offer. Your job is to AIM these: say
which to run against which paths and why, and which to leave off and why. Do not
run them for findings.>

## Your reference
Read `references/recon.md` FIRST and follow its procedure. Read
`references/surfaces/<SURFACE>.md` for what this surface makes possible, treating
its checklist as a floor rather than your output.

## What to produce
1. Falsifiable restatement of every guarantee the repo documents.
2. A trust map: each boundary with a file:line, its data source, and what the code
   assumes holds after it.
3. An invariant list: what the code assumes and never checks, each phrased so it
   can be falsified, each with a file:line.
4. An idiom census: how this repo does a thing, the conforming count, the deviating
   count, and the deviation loci.
5. Repo-specific semgrep or ast-grep rules for the invariants and deviations no
   standard pack covers. Validate each, then prove it matches a known-positive and
   skips a known-negative drawn from this repo. Write each at the repo's own
   lint-config convention when it has one, so a confirmed rule can graduate into CI.
6. A pack-aiming decision: packs to run with exact invocations, and packs left off
   with reasons.
7. An agentic-code scan: signature-detect whether the application itself is agentic
   (an import of `langgraph`/`langchain`/`crewai`/`llama_index`/`semantic-kernel`, an
   LLM SDK or a Bedrock-agent/AgentCore call; a prompt assembled from a variable and
   sent to a completion; `exec`/`eval`/`subprocess` on a model response; fetched
   content flowing into a prompt). When present, the agents surface applies to this
   app code even with no `.claude`/`.mcp.json` in the repo, and you synthesize rules
   for the patterns in `surfaces/agents.md`. This is content-based recon, not a path
   glob.

## What you MUST NOT do
- Edit product code, tests, or an existing rule file.
- Run a scanner for findings, or run a fuzz campaign. Confirming your own rule
  matches its fixture is the limit.
- Report a vulnerability. You produce the map others attack from.
- Hand forward an invariant with no file:line behind it.

## Return
The Scout Output format from your agent definition. Every artifact carries a
file:line, every census carries both counts, and every rule carries its fixture
results.
```

---

## Filling guidance

- **Withhold your hypothesis.** Naming a suspected bug narrows the census, and the
  census is where the finding lives.
- **Point at the repo's self-documentation explicitly.** A scout that skips the
  docs re-derives guarantees the project already stated, and misses the ones it
  states and breaks.
- **Pass the pack list, and let the scout aim it.** Aiming needs the threat model
  the scout is building, so it cannot be decided in advance.
- **One scout per surface.** Split a surface exceeding roughly 5k LOC by subtree,
  and give each a narrowed file list, since a census over too much code degrades to
  a guess.
- **Recon before authoring, always.** A `fuzzer` handed no invariants writes
  never-panics harnesses and nothing else, which finds crashes and misses every
  logic bug.
