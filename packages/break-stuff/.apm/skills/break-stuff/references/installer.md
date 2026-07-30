# Installer flow

How break-stuff handles tool availability. The tools run in the surface image, not
on the host (`references/isolation.md`, What runs where), so step 3 does not install
scanners on the host at all: it builds or extends the image and bakes the target's
dev-deps into it (`isolation.md`, Provisioning). A tool missing from the image
becomes a reported coverage gap, surfaced by `--assert-tools`.

## Host preflight, then image provisioning

The only host requirement is the container runtime plus `bd` and `git`;
`scripts/install-tools.sh --probe` is a preflight that confirms these and reports
which surface images exist. It installs nothing on the host: a host-side scanner
would run the target's code outside the container, so every tool lives in the image.

1. **Preflight (host):** `install-tools.sh --probe` confirms a runtime
   (`docker`/`finch`), `bd`, and `git`, and lists which `break-stuff/<surface>:1`
   images are built. No runtime means the execution phases cannot run
   (`isolation.md`, Degrade loudly).
2. **Provision (image):** build any missing surface image from
   `references/containers/`, and extend it with the target's dev-deps per
   `isolation.md` Provisioning, keyed on the manifest+lock so the layer caches.
3. **Assert (image):** `run-contained.sh --assert-tools <image> <tools>` confirms
   every campaign tool answers inside the image before the run trusts a clean result.

MUST Provision tools into the image, never onto the host. A scanner on the host runs the target's build code unconfined, the exact risk the container removes.
MUST Treat a missing runtime as a hard stop for the execution phases. Report a missing image tool as a coverage gap in the report; never let it pass as a silent skip.

## Legacy: host ephemeral routes (pre-container model)

The routes below predate the all-in-container model and are retained only for a
degraded host-only run where no container runtime exists at all. In that case the
run is already refusing every execution phase, so these cover the text-only scanners.
`install-tools.sh --routes` prints the per-tool invocation: `uvx` for Python-packaged
tools, `npx` for JS ones, `go run` for Go, a cargo subcommand for Rust, `mise x`.

## Step-3 sequence

1. **Probe.** `install-tools.sh --probe` prints, per bundle, which tools are
   resident, which are present but unrunnable (a version-manager shim with no
   version selected), and which are absent. Pair it with `--routes` so a tool that
   is absent but ephemerally runnable is not proposed as an install.
2. **Propose the full set and let the user trim.** Every viable tool for the
   detected surfaces is pre-selected default-on; the user deselects rather than
   opting in. Do not dump raw probe output, and do not offer depth tiers. Shape
   the decision like this:

   ```
   Detected surfaces: shell, agents, infra, robustness
   Installed:            shellcheck ok  actionlint ok
   Missing (default-on): semgrep MISS  zizmor MISS  trivy MISS  pinact MISS
   Opt-in (off unless asked): checkov -- overlaps trivy for the rules this repo
     hits; adds value only for custom policy
   ```

   Pull the overlap facts from `tooling.md`.
3. **Propose the budget in the same message.** The tool table and the budget table
   are one decision, since approving tools without a duration leaves the campaign
   unbounded. State the harness count and the worst-case wall-clock.
4. **Install every default-on tool the user leaves selected.**
   `install-tools.sh --install <bundle>...` or `--all`, with `--dry-run` first when
   the user wants to see the commands.
5. **Proceed regardless.** A declined install becomes a coverage gap in the report
   rather than a blocked run.

MUST Treat a SHIM result as missing. A binary on PATH that fails a trivial invocation cannot run a scan, and assuming it works produces a silent zero-findings result.

## Bundles

| Bundle | Tools | When |
|---|---|---|
| `core` | semgrep, gitleaks | always, the cross-surface floor |
| `shell` | shellcheck, shfmt | shell scripts or hooks in scope |
| `python` | bandit, ruff, atheris, hypothesis | Python in scope |
| `rust` | cargo-audit, cargo-fuzz, clippy via rustup | Rust in scope |
| `go` | gosec, golangci-lint | Go in scope |
| `js-ts` | eslint with the security plugin, jazzer.js, fast-check | JS or TS in scope (project-local) |
| `native` | AFL++, llvm with the sanitizers | C or C++ in scope |
| `infra` | trivy, checkov, hadolint, tflint, kube-linter | Terraform, Docker, or k8s in scope |
| `ci` | zizmor, actionlint, pinact | workflows in scope |
| `deps` | osv-scanner, grype | dependency scanning, when `dep-audit` is absent |
| `mutate` | radamsa, zzuf, honggfuzz | byte-level mutation; resident, since the upstreams ship no binaries |
| `triage` | casr, shrinkray, creduce | crash dedup, classification, and minimization |
| `schema` | genson, hypothesis-jsonschema, jsf, schemathesis | structure-aware generation from a schema or spec |
| `grammar` | grammarinator, dharma | grammar-aware generation for a DSL |
| `deep` | CodeQL, cargo-geiger | opt-in, for interprocedural taint or an unsafe census |

## Project-local tools

`eslint`, `jazzer.js`, and `fast-check` belong in the repo's own
`devDependencies`, pinned with the project. The script reports them and prints the
install line to run inside the repo rather than installing them globally. Run them
through `npx` so the project's config and plugin versions apply.

## Fuzzer toolchain notes

| Tool | Requirement |
|---|---|
| `cargo-fuzz` | a nightly toolchain for `-Zsanitizer=address`, so report the requirement rather than switching the user's default toolchain |
| `atheris` | a matching CPython build, and it fails on some 3.13-plus builds, so probe by running it rather than by checking the version |
| `go test -fuzz` | Go 1.18 or later, built in, so nothing to install |
| AFL++ | best through the distro package or brew, and it needs an instrumented build of the target |
| `hypothesis` | belongs in the project's own dev dependencies when the repo already uses pytest |

MUST Probe a fuzzer by running it; a fuzzer that cannot build its instrumented target is unavailable in practice.
NOT Never switch the user's default toolchain to satisfy a fuzzer. Report the requirement and let them decide.

## Environment isolation

MUST Prefer a repo-local install when mise is present, writing `./mise.toml` in the target rather than mutating the user's global config.
MUST Leave a tool already on PATH untouched, since reinstalling a working tool risks breaking a pinned version the project depends on.
