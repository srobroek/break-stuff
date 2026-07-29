# Break stuff

Unleash havoc on your repos by letting your agents use tools at their disposal to try and find holes in your code, application, prompts, and more. Uses both deterministic and non-deterministic tooling for maximum chaos. 

## Quick Start

Offensive and robustness auditing for code, scripts, hooks, and agents.

jackhammer is a **marketplace** that ships one package: the **`break-stuff`**
skill and its agents. It applies blunt force to your own codebase until the cracks
show, then proves each crack with a reproducing input or a traced path.

## What it does

Point it at a repo, a diff, a hook, or an agent definition. It runs **recon
first** — working out what the code assumes about itself, where its trust
boundaries sit, and where it deviates from its own patterns — then attacks those
assumptions across seven surfaces:

| Surface | What it attacks |
|---|---|
| Code | injection, taint-to-sink, unsafe blocks, overflow, deserialization, ReDoS |
| Shell & hooks | command-position bypass, quoting, fail-open inversion, guard evasion |
| Agents & prompts | prompt injection, tool over-grant, exfil paths, unpinned MCP servers |
| Infra & supply chain | IaC misconfig, CI injection, secrets, malicious dependencies |
| Web & frontend | DOM-sink XSS, CSP gaps, client-side secrets, live DAST against the dev server |
| Build & toolchain | build-time execution, install scripts, the xz-tarball vector |
| Robustness | malformed-input crashes, boundary values, resource limits, silent wrong answers |

Standard scanners and fuzzers (semgrep, bandit, clippy, cargo-fuzz, nuclei, …) are
borrowed as they come; recon builds the harness that aims them and writes rules for
what no pack covers. Findings carry two axes — **evidence tier** (proven /
reachable / hardening / refuted) and **impact** — and are demoted rather than
dropped. It is advisory: it writes harnesses, rules, and regression tests, and
patches product code only on explicit approval.

## Why "break-stuff"?

The package is named for what you type to invoke it — "break this hook",
"red-team this agent", "fuzz this parser". The repo is `jackhammer` (the tool); the
skill is `break-stuff` (the verb). You trigger it by asking to harden, red-team,
fuzz, or break something.

## Install


Note
**Claude Code**

```
claude plugin marketplace add srobroek/break-stuff
claude plugin install break-stuff@break-stuff

```

**Codex**

Note: Codex has not been fully tested yet, run at your own risk. 
```
codex plugin marketplace add srobroek/break-stuff
codex plugin add break-stuff@break-stuff
```

**APM** (Codex, and other APM runtimes)

```
apm marketplace add srobroek/break-stuff --name break-stuff
apm install break-stuff@break-stuff --target claude
apm install break-stuff@break-stuff --target codex
```

Pin a release by appending `@<tag>` to the marketplace-add, e.g.
`srobroek/jackhammer@break-stuff--v0.1.0`.

## Requirements

- **beads** (`bd`) — the task-graph substrate the campaign records its run into.
  A campaign that cannot open a beads run refuses to start; there is no fallback
  store.
- **A container runtime** — docker, finch, or colima. Every execution phase (fuzz
  campaigns, live DAST, build-script runs) executes inside a locked-down,
  disposable container, never on the host. With no runtime present, the static and
  reading passes still run and the execution phases are reported as a coverage gap
  rather than run unconfined.

## How to use it

Invoke the skill and name a target:

```
break-stuff — red-team the PreToolUse guards in packages/hooks-bash-safety
break-stuff — fuzz the FITS header parser in this crate
break-stuff — audit this PR for security and robustness issues
```

It runs a five-agent campaign:

1. **scout** — recon per surface: trust map, invariants, idiom census, repo-specific rules
2. **fuzzer** — writes harnesses, seed corpora, and attack vectors (runs nothing)
3. **gremlin** — executes scanners and harnesses inside a container, reads for what they miss
4. **triager** — dedups crashes, minimizes to a smallest reproducing input, classifies
5. **challenger** — sets the evidence tier on every finding, independently

A sixth agent, **hardener**, applies an approved fix and re-verifies, only after you
say so.

### Scope modes

- **full** (default) — every step
- **quick** — recon plus a smoke campaign, no new harnesses or challenger
- **audit-only** — describe findings, never patch (regression tests are still written)
- **harness-only** — author harnesses and corpora, execute nothing

### Safety

- Attacks only local code you own — no network target, no public endpoint, no live DoS
- Execution is container-isolated: target mounted read-only, network denied, resource-capped, non-root
- A campaign never generates an input whose effect is irreversible; it fuzzes the code path that *receives* `rm -rf`, it never runs it
- Product code is patched only on explicit approval, behind a verification re-run

## What ships

| Path | What |
|---|---|
| `packages/break-stuff/.apm/skills/break-stuff/` | the skill router + reference docs |
| `.../scripts/fuzz-cli.py` | a JSON-stdin/CLI adversarial harness for any hook or guard |
| `.../scripts/run-contained.sh` | the container wrapper every execution phase runs through |
| `.../references/containers/` | per-surface Dockerfiles (rust, python, node), extensible |
| `packages/break-stuff/.apm/agents/` | scout, fuzzer, gremlin, triager, challenger, hardener |



License: Apache-2.0
