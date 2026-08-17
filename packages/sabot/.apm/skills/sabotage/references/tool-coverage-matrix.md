# Tool coverage matrix

This matrix lists every tool sabot advertises, the image that ships it, its OFFLINE
requirement under `--network none` (the campaign's mandatory isolation), and its
end-to-end test status. The "offline req" column is MEASURED, not assumed: run the
tool twice (`--network none` against `--network bridge`) and compare, per the probe
method in `isolation.md`. A tool that exits 0 offline while doing less than it does
online is DEGRADED-SILENT, the false-clean this matrix exists to eliminate.

## Offline-requirement classes

- **self-contained**: offline output equals online; the tool ships all it needs and runs as-is.
- **baked-ok**: needs remote data, baked into the image, works offline.
- **degraded-silent**: exits 0 offline but did less (loaded 0 rules/advisories). MUST fix (bake, or forbid the online-only invocation).
- **fails-loud**: errors offline, safe because the campaign sees the failure.
- **needs-build-dep**: offline operation needs crates/packages/compilers not present.
- **UNMEASURED**: not yet probed.

## Status legend

baked (in an image manifest + verified) · fragment-pending (bake work queued) ·
image-unbuilt (fragment exists, image not built) · fixture-verified (a test repo
proved detection end-to-end).

## base image (cross-surface, infra, secrets, container, generators)

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| opengrep | degraded-silent (forbid `--config auto`; local rules only) | baked | rust-parser (local rule) |
| ripgrep | self-contained | baked | n/a |
| shellcheck | self-contained | baked | shell fixture (pending) |
| shfmt | self-contained | baked | shell fixture (pending) |
| ast-grep | self-contained | baked | rust-parser rule |
| gitleaks | self-contained (rules embedded) | baked | secrets fixture (pending) |
| zizmor | self-contained (offline==online) | baked | **infra-ci VERIFIED** |
| actionlint | self-contained | baked | infra-ci |
| pinact | fails-loud (SHA resolve needs net) | baked | infra-ci |
| trivy | fails-loud → bake trivy-db | baked (DB non-empty, asserted) | infra/deps fixture |
| osv-scanner | fails-loud → bake OSV DB | baked (4 ecosystems, asserted) | deps fixture |
| Checkov | UNMEASURED (pip) | fragment-pending | iac fixture |
| hadolint | UNMEASURED (binary) | fragment-pending | dockerfile fixture |
| kube-linter | UNMEASURED (binary) | fragment-pending | k8s fixture |
| tflint | UNMEASURED (binary; plugins need net) | fragment-pending | terraform fixture |
| Grype | UNMEASURED → likely bake DB | fragment-pending | deps fixture |
| TruffleHog | UNMEASURED (verify mode needs net) | fragment-pending | secrets fixture |
| Kingfisher | UNMEASURED (live-validate needs net) | fragment-pending | secrets fixture |
| GuardDog | UNMEASURED (pip) | fragment-pending | deps fixture |
| OSSF-Scorecard | needs-net (GH API), likely irreducible gap | fragment-pending | doc as gap? |
| poutine | UNMEASURED (binary) | fragment-pending | infra-ci |
| Nuclei | UNMEASURED → bake templates | fragment-pending | web fixture |
| Bearer | UNMEASURED (binary) | fragment-pending | code fixture |
| radamsa | self-contained (mutator) | fragment-pending | n/a |
| zzuf | self-contained (mutator) | fragment-pending | n/a |
| C-Reduce | self-contained (reducer) | fragment-pending | n/a |

## rust fragment

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| clippy | needs dep graph (ok in ext) | baked | rust-parser |
| cargo-fuzz | needs-build-dep (libfuzzer-sys+arbitrary+g++), baked; needs `+nightly` | baked | **rust-parser VERIFIED** (built and crashed the target offline) |
| cargo-audit | degraded-silent → bake advisory-db | baked | **deps-rust VERIFIED** (1216 advisories, RUSTSEC-2020-0071 offline) |
| cargo-geiger | needs dep graph (ok in ext) | baked | rust-parser |
| cargo-careful | UNMEASURED (+nightly) | fragment-pending | rust-parser |
| cargo-deny | degraded-silent → bake advisory-db | fragment-pending | deps fixture |
| cargo-semver-checks | UNMEASURED (needs baseline) | fragment-pending | rust-parser |
| cargo-vet | UNMEASURED | fragment-pending | deps fixture |
| Miri | needs-build-dep (+nightly component) | fragment-pending | rust-parser |
| proptest | crate, no binary (dev-dep) | fragment-pending | rust-parser |
| CASR | UNMEASURED (crash triage) | fragment-pending | rust-parser crash |
| AFL++ | needs-build-dep (apt + cargo-afl) | fragment-pending | rust-parser |
| honggfuzz | needs-build-dep (apt + cargo) | fragment-pending | rust-parser |
| weggli | self-contained (C/C++ pattern) | fragment-pending | n/a |

## go fragment

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| `go test -fuzz` | self-contained (fuzzer is in the toolchain; no runtime crate to bake) | baked | **go-parser VERIFIED** (found seeded panic offline, crash corpus copied out) |
| gosec | self-contained (rules compiled in) | baked | **go-parser VERIFIED** (G404 offline) |
| golangci-lint | self-contained (linters compiled in) | baked | **go-parser VERIFIED** (ineffassign offline) |
| go vet | self-contained (ships with the toolchain) | baked | go-parser (no vet-class defect seeded; ran clean) |

The go surface needs `GOPROXY=off` and a `TMPDIR` below the scratch root; both are
recorded as MUSTs in `isolation.md`.

## python fragment

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| Bandit | self-contained (rules embedded) | baked | **python-parser VERIFIED** (B307 offline) |
| Ruff | self-contained (needs `RUFF_CACHE_DIR` off the read-only target) | baked | **python-parser VERIFIED** (offline) |
| Semgrep | degraded-silent (same as opengrep) | baked | python-parser |
| atheris | needs-build-dep (clang + `libclang-rt-<major>-dev` + `CXX`), baked | baked | **python-parser VERIFIED** (found seeded IndexError offline) |
| Hypothesis | self-contained (library; assert by import) | baked | python-parser |
| HypoFuzz | UNMEASURED (pip) | image-unbuilt | python-parser |
| schemathesis | UNMEASURED (needs a spec) | image-unbuilt | api fixture |
| Grammarinator | UNMEASURED (pip) | image-unbuilt | n/a |
| dharma | UNMEASURED (pip) | image-unbuilt | n/a |
| shrinkray | self-contained (reducer) | image-unbuilt | n/a |

## node fragment

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| Jazzer.js | self-contained (prebuilt addon; needs glibc >= 2.38, so trixie) | baked | node-parser |
| fast-check | self-contained (library; reachable via `NODE_PATH`) | baked | node-parser |
| retire.js | degraded-silent → bake defs + `--jsrepo` | baked | node-parser |
| eslint-plugin-no-unsanitized | UNMEASURED (needs eslint) | fragment-pending | node-parser |

## heavy engines (own layer; large)

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| CodeQL | needs-build-dep + query packs (~500MB) | fragment-pending | code fixture |
| Joern | JVM + install (CPG build) | fragment-pending | code fixture |
| OWASP-ZAP | JVM/daemon, DAST (needs a running server) | fragment-pending | web fixture |

## Irreducible gaps (cannot work offline; document, do not pretend)

- **OSSF-Scorecard**: scores a repo via the GitHub API; no offline mode. Record as a coverage gap in any report that would run it.
- Any tool whose ONLY value is a live network probe (ZAP active scan against a remote, Kingfisher/TruffleHog live-credential validation): offline runs the static half only; the report must say which half ran.
