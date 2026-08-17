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
| hadolint | self-contained (rules compiled in) | baked | **infra-extras VERIFIED** (DL3006/DL3008/DL3009/DL3015 offline) |
| kube-linter | self-contained (checks compiled in) | baked | **infra-extras VERIFIED** (5 checks fired offline) |
| tflint | baked-ok CORE ONLY (`--init` provider plugins need net; report must say core-only) | baked | **infra-extras VERIFIED** (2 core issues offline) |
| Grype | baked DB DECLINED: DB measures 2.0GB (v0.117.0) and base is inherited by every surface; trivy + osv-scanner already cover the same ecosystems | declined | n/a; the coverage is already there via trivy and osv-scanner |
| TruffleHog | baked-ok DETECTION ONLY; needs `--no-update` (self-updater aborts the scan on a read-only fs) + `--no-verification` | baked | **VERIFIED** (1 unverified AWS secret offline, verified_secrets 0) |
| Kingfisher | UNMEASURED (live-validate needs net) | fragment-pending | secrets fixture |
| GuardDog | UNMEASURED (pip) | fragment-pending | deps fixture |
| OSSF-Scorecard | needs-net (GH API), likely irreducible gap | fragment-pending | doc as gap? |
| poutine | self-contained (rules compiled in); subcommand is `analyze_local` | baked | **infra-ci VERIFIED** (injection rule fired offline) |
| Nuclei | UNMEASURED → bake templates | fragment-pending | web fixture |
| Bearer | UNMEASURED (binary) | fragment-pending | code fixture |
| radamsa | self-contained (mutator); builds from source, needs `libc6-dev` | baked | **python-parser VERIFIED** (33 crashes in 200 mutations offline) |
| zzuf | self-contained (mutator) | baked | build asserts output differs from input |
| C-Reduce | self-contained (reducer); test script MUST use a RELATIVE path | baked | **VERIFIED** (182 -> 16 bytes offline) |

## rust fragment

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| clippy | needs dep graph (ok in ext) | baked | rust-parser |
| cargo-fuzz | needs-build-dep (libfuzzer-sys+arbitrary+g++), baked; needs `+nightly` | baked | **rust-parser VERIFIED** (built and crashed the target offline) |
| cargo-audit | degraded-silent → bake advisory-db | baked | **deps-rust VERIFIED** (1216 advisories, RUSTSEC-2020-0071 offline) |
| cargo-geiger | needs dep graph (ok in ext) | baked | rust-parser |
| AFL++ | needs-build-dep (apt + cargo-afl) | fragment-pending | rust-parser |
| honggfuzz | needs-build-dep (apt + cargo) | fragment-pending | rust-parser |

## rust-extras fragment

An OPTIONAL escalation image (`sabot/rust-extras:1`), not part of every campaign: a
rust run starts on `sabot/rust:1` and escalates here when a finding needs a license
view, a UB interpreter, or a semver-break check. Absent is a note in the preflight, not
a failure.

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| cargo-deny | degraded-silent → baked advisory-db, and `db-path` must be a WRITABLE PARENT holding the db under `advisory-db-<hash>` with its `.git` intact; `--offline` goes before the subcommand | baked (wrapper copies the db into that shape on tmpfs) | **deps-rust VERIFIED** offline (RUSTSEC-2020-0071; `bans ok, licenses FAILED`) |
| cargo-careful | needs-build-dep: sysroot MUST be baked, and to a uid-1000-readable path (the default `~/.cache` put it in `/root`) | baked (`/deps/cache/cargo-careful`) | **rust-parser VERIFIED** (2 tests pass offline off the baked sysroot). **NOT a substitute for Miri**: on `ub-rust` it reported the seeded out-of-bounds read as passing. It hardens std's debug assertions; it does not interpret UB |
| Miri | needs-build-dep: builds its OWN sysroot from rust-src at first use, which needs crates.io. `miri --version` answers while that sysroot is absent | baked (`/deps/cache/miri`) | **rust-parser VERIFIED** offline after the bake; failed `no matching package named hashbrown` before it. **ub-rust VERIFIED**: `cargo test` reports 1 passed on a read past the end of an allocation, Miri reports `Undefined Behavior: ... at or beyond the end of the allocation of size 3 bytes` |
| cargo-semver-checks | needs a baseline; `--baseline-rev` needs `.git` (stripped by `--copy-src`) and the default resolves through crates.io. `--baseline-root` is the offline form | baked | **rust-parser VERIFIED** (196 checks, 58 skip, via `--baseline-root /target`) |
| cargo-vet | fails-loud offline: needs a `supply-chain/` store, and imports its audits over the network | baked | **deps-rust MEASURED**: `must run 'cargo vet init'`: honest, not a false clean |
| weggli | self-contained (C/C++ pattern; patterns come from the campaign) | baked | 0.2.4 answers; no C/C++ in the rust fixtures |
| proptest | crate, no binary (a dev-dep, baked per-target by build-ext-image.sh) | declined | n/a; installing it globally installs nothing usable |
| CASR | needs gdb, and duplicates what libFuzzer already prints for a rust panic | declined | n/a |

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
