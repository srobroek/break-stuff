# Tool catalog: cross-cutting index

Per-surface tool tables are authoritative in each `surfaces/<surface>.md`, with
their Tier, Class, and Run recipe columns. This file holds what cuts across
surfaces: the universal run rules, plus the overlap map and analysis classes that
scope each tool.

The tools live in the surface image, not on the host; see `references/isolation.md`
(Provisioning) for how the image is built and dev-deps baked.

## Universal run rules

Every recipe in a surface doc assumes these, so they are not repeated there:

1. **Every recipe runs in the container.** A surface doc's recipe is the tool
   invocation; `run-contained.sh` wraps it, so the tool runs against the target
   mounted read-only at `/target`, never on the host. This holds for text scanners
   (`opengrep`, `shellcheck`, `ast-grep`) as well as compiling ones (`clippy`,
   `gosec`) and fuzzers: a compiling scanner builds the crate and so runs the
   target's own build code, which must be confined. The host runs only the agent and
   `bd`/`git`/the runtime.
2. **cwd is `/scratch`, the target is read at `/target`.** The container's writable
   cwd is `/scratch`; pass the resolved file set as paths under `/target` (e.g.
   `opengrep --config p/python /target/src`), and let builds write to `/scratch`
   (`CARGO_TARGET_DIR` etc. are set for you).
2. **Shipped assets are absolute.** Reference `corpora/` and any recon-synthesized
   rule by absolute path, since cwd is the target and a skill-relative path silently
   matches nothing.
3. **Project config wins.** When the repo configures a scanner, run it so that
   config governs. The recipe's flags are the no-project-config form.
4. **Exit codes are a contract.** For most scanners, non-zero means findings
   rather than failure. Distinguish 0 (clean), N (findings, so parse the output),
   and a usage or crash error (INVALID, so fix the invocation and rerun). A
   sub-second run from a tool that must compile is also INVALID.
5. **Flag exactly as written.** Go tools use single-dash `-format`, others use
   `--`. Copy the recipe verbatim rather than normalizing it.
6. **Suppress default noise the project never opted into.** When a scanner's
   defaults are stricter than the repo's own rules and no project config exists,
   the recipe states its own suppression.

MUST Never substitute a regex grep for a scanner. A missing tool is a reported coverage gap, and a guess dressed as a finding is worse than a gap.

## Analysis class

Each tool carries one class, which decides how it scopes to a bounded target:

| Class | Meaning | Bounded-target behaviour |
|---|---|---|
| local | the finding lives inside one file | pass the target file list |
| relational | the finding is a link between the target and other code | scan target plus context, report links touching the target |
| global | a project-wide invariant, such as dependency CVEs or dead code | skip and record "SKIPPED (scoped)" |
| baseline | the analysis is a comparison against a ref | native to a ref target, so run it against the base and headline the delta |

Class matters only for bounded targets. A whole-repo run executes everything.

## Overlap map

A tool that already covers a dimension makes the point tool redundant, so drop the
point tool rather than reporting the same finding twice:

| Dimension | Owner | Point tool becomes |
|---|---|---|
| Python security lints | ruff `S` ruleset | bandit still adds checks ruff lacks, so keep both |
| Go security | golangci-lint with gosec enabled | standalone gosec is redundant |
| Rust panics and overflow | clippy | nothing else needed |
| IaC misconfig | trivy | checkov still adds policy classes, so keep both |
| Dependency CVEs | the repo's `dep-audit` package | osv-scanner and grype are redundant when it ran |
| Secrets | the repo's `secrets-scan` package | gitleaks and trufflehog are redundant when it ran |
| Shell inside CI | actionlint, which embeds shellcheck | a separate shellcheck pass over `run:` blocks is redundant |
| Shell inside Dockerfile | hadolint, which embeds shellcheck | same |
| CI security | zizmor | nothing else does workflow dataflow |
| Interprocedural taint | CodeQL | semgrep is intra-file only, so they do not overlap |

MUST Prefer the repo's own `dep-audit` and `secrets-scan` packages when present, running these scanners only for what those leave uncovered.

## Coverage honesty rules

A skipped tool and a covered dimension are different report lines:

| Situation | Report as |
|---|---|
| A meta-tool that ran already covers the dimension | covered, not a gap |
| Global-class tool on a bounded target | SKIPPED (scoped), which takes precedence over "not installed" |
| Tool absent and the dimension uncovered | SKIPPED (not installed), with the install hint |
| The stack has no tool for this dimension at all | N/A |
| Tool ran and crashed | INVALID, and never clean |

MUST State the skip reason precisely, since "not installed" and "out of scope" demand different remediation from the reader.

## Detection sources

Detection comes from three places, in ascending order of how much this repo it
knows. No generic rules are shipped in the package: a hand-maintained generic rule
duplicates a registry pack and rots silently (a mixed-language rule that passes
`--validate` can still fail at scan time and run against zero files).

| Source | What | Coverage |
|---|---|---|
| Registry packs | `p/python`, `p/bash`, `p/command-injection`, bandit, gosec, clippy, shellcheck | generic dangerous patterns, maintained upstream |
| Recon-synthesized | rules `scout` writes and validates during recon, from this repo's own invariants and the agentic-pattern list in `surfaces/agents.md` | this repo's contracts, and agentic patterns no registry pack covers |
| Shipped corpora | `corpora/prompt-injection.md`, `scripts/fuzz-cli.py` | payload classes and the decision-contract harness |

MUST Select a registry pack that fits the detected language rather than `opengrep --config auto`, since auto fetches an unpredictable set over the network and its result is not reproducible.
MUST Run a recon-synthesized rule against a known-positive from this repo before trusting a zero-match result, since a rule that matches nothing reads exactly like a clean repo.
## Out of scope: LLM red-teaming

`garak` and `promptfoo` are excluded by design. Both measure whether a *model* can be
made to misbehave, and garak's own README says it does "somewhat similar things to
nmap or Metasploit, but for LLMs". The target here is this codebase, so a model's
alignment score answers a question nobody asked and costs inference to get.

The agents surface stays covered statically: the reading pass against
`corpora/prompt-injection.md`, the tool-grant analysis, `snyk-agent-scan` for MCP
configs, and the shipped `prompt-build.yml` rules for prompts assembled in code.

## Where tools come from

A surface recipe is the bare invocation of a tool that is already in the image
(`opengrep --config ...`, `cargo clippy`, `gosec`). `run-contained.sh` runs it against
the target at `/target`; nothing is fetched at run time, since the campaign runs under
`--network none`. Provisioning happens once, at image build, from
`references/containers/Dockerfile.<surface>` plus the dev-dep bake
(`isolation.md`, Provisioning).

The install forms below are how a Dockerfile PUTS a tool in the image, not how the
campaign calls it. They are here so a new surface image, or an extend layer, installs
the right way:

| Install form (in the Dockerfile) | Used for |
|---|---|
| `apt-get install` | the base OS scanners: ripgrep, shellcheck, jq |
| `pipx install` / `pip install` | Python-packaged scanners and generators: opengrep, zizmor, schemathesis, bandit |
| `npm i -g` / project `npm ci` | JS tools: ast-grep, jazzer.js, fast-check, eslint (project-local via the baked deps) |
| `go install <path>@<version>` | Go tools: gosec |
| `cargo install --locked <tool>` | cargo subcommands: cargo-fuzz, cargo-audit (clippy ships with the toolchain) |
| the base language image | the compiler/toolchain itself: `FROM rust:1-slim`, `FROM python:3-slim`, `FROM node:20-slim` |

MUST Pin every tool the Dockerfile installs to an explicit version (`cargo install --locked <tool> --version x`, `go install ...@vX`, `pip install tool==x`), so the image is reproducible and a scan result does not shift when an upstream releases.
MUST Make the pins of OUR security tooling bot-upgradable, so a scanner or fuzzer we bake does not silently rot. This is the tooling in the committed `Dockerfile.<surface>` (opengrep, cargo-fuzz, gosec, ...), not the target's own dev-deps, which are the target repo's concern. `FROM` tags are read by Dependabot and Renovate natively; a version pinned inside a `RUN` line is NOT (Dependabot ignores it, Renovate needs a `# renovate:` comment), so annotate each `RUN`-line pin with a `# renovate: datasource=... depName=...` line and ship `containers/renovate.json` with the custom manager. On-demand extend layers are transient and inherit their freshness from the committed base, so they pin inline without a bot.
MUST Report a tool absent from the image as a coverage gap (via `--assert-tools`), never substitute a different tool silently.
NOT Never fetch a tool at run time. The campaign is `--network none`; a tool not in the image is a gap the report states, not something the gremlin installs.
