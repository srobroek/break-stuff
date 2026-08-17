# Surface: Build and toolchain execution

Code that runs at build, install, or commit time, before any test does. This is
the xz-backdoor vector: a payload never invoked by the shipped program, only by
the act of building or installing it. `shell.md` owns hooks and `infra.md` owns
unpinned CI actions; this surface owns the execution the toolchain itself performs.

## Detect

`build.rs`, a `[build-dependencies]` table or proc-macro crate in `Cargo.toml`,
`package.json` with a `preinstall`/`install`/`postinstall`/`prepare` script,
`setup.py`/`setup.cfg` with custom command classes, `Makefile`/`justfile`/`Taskfile`
recipes, `.pre-commit-config.yaml` repos pinned to a branch, `binstall`/`cargo`
config running a fetch, git hooks under version control, and any codegen step a
build invokes.

## Tools

| Tool | Tier | Class | Run recipe | Catches | Overlap |
|------|------|-------|-----------|---------|---------|
| read | default-on | local | read every file in the Detect list | what the build actually executes, and where its inputs come from | no scanner enumerates build-time execution; reading is the detection |
| semgrep | opt-in | local | `opengrep --config /opt/sabot-db/semgrep-rules/rust --config /opt/sabot-db/semgrep-rules/python --json build.rs setup.py` | a build script shelling out on a value it fetched or read | baked rule dir, code side only |
| `cargo metadata` | default-on | local | `cargo metadata --format-version 1` | every build-dependency and proc-macro crate that runs at compile time | enumerates the compile-time code surface |
| npm dry-run | default-on | local | `npm install --ignore-scripts --dry-run` then diff against a normal install | which packages want to run install scripts | shows the install-time execution set |
| pinact | default-on | local | `pinact run --check` | a pre-commit repo or action pinned to a mutable ref | shared with `infra.md` |
| osv-scanner | default-on | global | `XDG_CACHE_HOME=/opt/sabot-db/osv osv-scanner scan source --offline-vulnerabilities --format json -r .` | a known-malicious build-dependency | shared with `infra.md`; prefer the `dep-audit` package |

MUST Read `build.rs`, proc-macro crates, and every install script, since a scanner enumerates none of them and the whole surface is code that runs before a test could catch it.
NOT Never run a build or install to observe it without the isolation below. Observing build-time execution by performing it is running the payload.

## Attack checklist

| # | Attack | Where it hides | Confirm by |
|---|--------|----------------|-----------|
| 1 | Build script fetches and executes | `build.rs` / `postinstall` doing a network fetch then running the result | trace whether the fetched content reaches an exec or a file the build later runs |
| 2 | Proc macro with a side effect | a proc-macro crate that writes a file or opens a socket at expansion time | read the macro body; expansion runs on every compile |
| 3 | Install script exfil | `preinstall`/`postinstall` reading env or `~/.ssh` and sending it | check for env reads and network calls in the script |
| 4 | Codegen from an untrusted input | a build reading a checked-in blob or a downloaded schema and emitting code | check whether the input is trusted and pinned |
| 5 | Branch-pinned pre-commit or action | `.pre-commit-config.yaml` `rev:` a branch, an action `@main` | a moved ref runs new code on the next commit or CI run |
| 6 | Build-dependency confusion | a `[build-dependencies]` name one edit from a real crate, or an unexpected transitive | compare against the manifest's intent, same as `infra.md` typosquat |
| 7 | Git hook in the tree | a committed `.githooks/` or a `core.hooksPath` pointing into the repo | a clone that runs `git config core.hooksPath` executes it |
| 8 | Test-time execution as a build stage | a `build.rs` that runs the "tests" it generates, or a test harness invoked at build | check whether building alone runs arbitrary code |
| 9 | Environment-dependent build | a build that behaves differently under a CI env var (the xz shape: payload only in a release tarball, not the git tree) | diff the git tree against the published artifact |

## Harness patterns

Mostly a reading surface, since building to observe is running the payload. Two
executable checks, both isolated:

- **Script census.** `fuzzer` lists every install/build script and what each
  invokes; `gremlin` runs `npm install --ignore-scripts` versus a scripted install
  in a throwaway container or worktree and diffs what changed.
- **Building in a sandbox.** When a `build.rs` or proc macro must be run to judge it, do
  it in a Worktrunk lease with no network and canaries seeded outside the lease, per
  `agentic-fuzz.md`'s containment. A canary touched, or a network call attempted, is
  the finding.

MUST Run any build-time execution in a lease with no outbound network and canaries seeded outside it, since the payload runs the moment the build does.
MUST Diff the git tree against the published or release artifact when one exists, because the xz vector hides the payload in the tarball rather than the repo.

## Impact calibration

| Level | Meaning on this surface |
|---|---|
| CRITICAL | build or install runs attacker-controlled code, or a payload present in the artifact but absent from the source tree |
| HIGH | a build script fetches and executes unpinned remote content, or a proc macro exfiltrates at expansion |
| MEDIUM | a branch-pinned pre-commit repo or action, a build-dependency typosquat with no confirmed payload |
| LOW | a build script reading a local trusted file with no network and no exec |

## False-positive traps

| Looks like a finding | Clears when |
|---|---|
| `build.rs` present | it only sets `cargo:rustc-cfg` flags or links a system library, with no fetch or exec |
| `postinstall` script | it runs a local, in-package build step with no network and no env read |
| A proc macro | it is a well-known crate (serde-derive, tokio-macros) whose expansion is pure codegen |
| A build fetching a file | the URL is pinned to a digest and the content is verified before use |
| A git hook in the tree | it is documented and installed only by an explicit opt-in, not `core.hooksPath` on clone |
