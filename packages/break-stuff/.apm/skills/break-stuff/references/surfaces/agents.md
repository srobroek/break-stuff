# Surface: Agents, skills, and prompts

No deterministic scanner exists for this surface, which makes reading and payload
testing the only detection available. The security model is simple to state: any
content an agent reads can attempt to instruct it, and any tool the agent holds is
reachable by whoever controls that content.

## Detect

`SKILL.md`, `*.agent.md`, `.claude/agents/**`, `.codex/agents/**`, `.mcp.json`,
`settings.json` or `settings.local.json` carrying `hooks` or `permissions`,
`CLAUDE.md`, `AGENTS.md`, `.claude/rules/**`, `.apm/instructions/**`,
`.apm/context/**`, and any prompt template a program builds at runtime.

## Tools

| Tool | Tier | Class | Run recipe | Catches | Overlap |
|------|------|-------|-----------|---------|---------|
| `scripts/fuzz-cli.py` | default-on | local | corpus mode against a hook or MCP server, see `harnesses.md` | a hook or server that crashes, hangs, or misparses a payload | the only executable check on this surface |
| `references/agentic-fuzz.md` (promptfoo) | opt-in | local | `npx --yes promptfoo@latest redteam generate` then `eval` against a real-invocation target script | generated attacks that LAND: repo-prompt-injection, verifier-sabotage, sandbox escape, MCP abuse | needs a model to generate and grade; the target itself is a local script |
| `references/corpora/prompt-injection.md` | default-on | local | `fuzzer` builds scenarios from it; `gremlin` runs them against the target definition | instruction override, exfil paths, tool coercion | the payload source of truth |
| semgrep (recon-synthesized) | opt-in | local | `scout` writes rules for the code side during recon (see the agentic pattern list below), then `uvx semgrep --config <rule> --json <files>` | a prompt assembled by string concatenation, an unpinned MCP `@latest` server, a secret committed in an agent config | no registry pack covers these agentic patterns, so recon synthesizes them per repo |
| `jq` schema read | default-on | local | `jq '.permissions, .hooks, .mcpServers' <settings.json>` | over-broad allowlists, wildcard permissions, unpinned MCP servers | mechanical, so it needs no judgement |
| gitleaks | default-on | local | `gitleaks detect --no-git --report-format json` | credentials in an MCP config or agent definition | overlaps the repo's own `secrets-scan` package, which is preferred when present |
| agentic-radar | opt-in | local | `uvx agentic-radar` | a static map of an agentic system's tools and flows | upstream quiet since 2025-11 |
| semgrep (ToB pack) | opt-in | local | `uvx semgrep --config p/trailofbits --json <files>` | agent-adjacent code patterns the shipped ruleset misses | fetches the pack over the network |
| snyk-agent-scan | default-on | local | `uvx snyk-agent-scan <config-path>` | MCP tool poisoning, cross-origin escalation, rug-pull patterns | static, so no LLM gate; the only executable scanner for MCP configs |

MUST Read the agent or skill definition as a whole before testing a payload against it, since the tool grant determines what an injection can reach.
MUST Restrict live-spawn agentic fuzzing to a PR, commit, or range target, and ask which skill or agent to invoke. See `references/agentic-fuzz.md`; a whole-repo live-spawn would attack every definition present.
MUST Run every case against every named target once live-spawn is approved. The definition pass ranks the report rather than selecting the work, since a definition whose rules read correctly while the agent complies anyway is the finding this mode exists to catch.
NOT No scanner judges prompt-injection resistance, so a clean tool run on this surface is not coverage of the injection classes: the reading pass against the corpus is the detection.
NOT An LLM red-team tool (garak, promptfoo) measures whether a MODEL can be made to misbehave, which is a different target from whether this repo's definitions and grants are safe. Out of scope.
MUST Decline snyk-agent-scan's prompt to launch stdio servers unless the user explicitly approves, since starting a server executes third-party code.

## Agentic patterns for recon to synthesize (no registry pack covers these)

`scout` writes and validates a rule per applicable pattern during recon, rather than
the skill shipping a static file that rots:

| Pattern | Shape | Where it bites |
|---|---|---|
| Unpinned MCP server | `npx -y <pkg>@latest` / `uvx <pkg>` with no version in `.mcp.json` | remote code execution on next server start |
| Prompt built by concatenation | `f"...{untrusted}..."` / `"..." + var` assigned to a prompt or system-prompt field | delimiter injection closing the template |
| Secret in an agent or MCP config | a live-looking token in `.mcp.json` `env` or an agent body | committed credential |
| Fetched content into a prompt | a `requests`/`fetch` result interpolated into a prompt with no quarantine | untrusted content reaching the model |
| exec of model output | `exec`/`eval`/`subprocess` on a completion/response variable | running whatever the model was persuaded to emit |
| Memory write of unvalidated content | model or fetched text written to a durable memory store | one session plants a fact later sessions trust |

MUST Have `scout` synthesize these as validated rules during recon, and treat a repo with none of them present as covered rather than a gap.

## Attack checklist

| # | Attack | Where it hides | Confirm by |
|---|--------|----------------|-----------|
| 1 | Untrusted content reaching context | `WebFetch`, `fetch_url`, MCP resources, file reads of vendored or downloaded content, PR bodies, issue text | trace whether the fetched text lands in a prompt without a quarantine boundary |
| 2 | Tool over-grant | an agent's `tools:` list, `permissions.allow` in settings | compare the granted set against the agent's stated task; a read-only reviewer holding `Write` or `Bash` is over-granted |
| 3 | Instruction override | a skill or agent body that says to follow instructions found in data | check whether the definition tells the agent to treat file content as authority |
| 4 | Exfil path | an agent holding both a read tool and a network or write tool | name the specific pair; a reader with `WebFetch` can send what it reads |
| 5 | Abstract or unresolvable tool names | `tools: terminal`, `tools: file-manager` in a definition | confirm the harness resolves the name; an unresolved name yields zero tools and drives fabrication |
| 6 | Unpinned MCP server | `.mcp.json` with `npx -y <pkg>@latest` or a floating tag | check for a pinned version or SHA; an unpinned server is remote code execution on next start |
| 7 | Hook trust boundary | a hook that reads `tool_input` and executes part of it | trace whether any field reaches a shell or an `eval` |
| 8 | Missing self-filter in a hook | a hook matching on a broad event and acting on the wrong tool | send an unrelated tool payload and check whether it acts |
| 9 | Permission escalation through a subagent | a parent with narrow tools spawning a child with `*` | compare parent and child grants; the child's grant is the effective one |
| 10 | Secret in a definition or config | a token in `.mcp.json` `env`, an API key in an agent body | confirm the value is a live credential rather than a placeholder |
| 11 | Prompt assembled by concatenation | code building a prompt with `f"..."` from a database or request field | check for delimiter injection: can the value close the quoting the template assumes |
| 12 | Output-contract escape | an agent whose report is parsed by the caller | supply content that forges the caller's expected verdict line |
| 13 | Memory or state poisoning | a skill that writes to a durable memory the next session trusts | check whether written content is validated before a later session acts on it |
| 14 | Auto-approve breadth | a hook or setting that approves tool calls without inspecting them | enumerate what the approval covers and whether a destructive call fits |

## Harness patterns

Two harnesses cover this surface:

**Definition review.** `fuzzer` builds a scenario table from
`references/corpora/prompt-injection.md`, one row per payload class crossed with
each entry point where untrusted content enters. `gremlin` evaluates each against
the definition and records whether the definition contains a rule that would stop
it. This is a reading exercise with a fixed checklist rather than an execution.

**Hook and server execution.** Every hook and MCP server is a program taking
structured input, so it goes through `scripts/fuzz-cli.py` in JSON-stdin mode with
the same invariants as `shell.md`.

MUST Test a payload against the definition rather than against a live agent, because spawning an agent to see whether the injection works costs tokens and yields a non-deterministic answer.
NOT Never place a live injection payload in a file the running session then reads, since that attacks the auditor rather than the target.

## Impact calibration

| Level | Meaning on this surface |
|---|---|
| CRITICAL | untrusted content can reach a tool that writes, executes, or transmits, with no boundary in between |
| HIGH | an agent holds a read plus a send tool with no rule against forwarding what it reads, or an MCP server is unpinned |
| MEDIUM | over-granted tools with no traced injection path, a hook that acts on unrelated payloads, or an abstract tool name |
| LOW | a definition missing a defensive rule for a path no untrusted content currently reaches |

## False-positive traps

| Looks like a finding | Clears when |
|---|---|
| An agent holding `Bash` | its task requires running the project's tests, and its definition forbids network and write operations |
| `WebFetch` in an agent's grant | the definition routes fetched content through a summarizer that never re-enters a tool call |
| A wildcard permission | it appears in `settings.local.json` for a personal sandbox rather than in a committed config |
| A token-looking string in a config | it matches a known placeholder form, or the scanner's own allowlist covers it |
| A skill telling the agent to follow a referenced file | the file is a repo-controlled reference rather than fetched or user-supplied content |
| An unpinned MCP server | the server is a local path or a first-party binary the user builds, so no remote fetch happens |
