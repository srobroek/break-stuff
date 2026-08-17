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
| shellcheck | self-contained | baked | **shell VERIFIED** (SC2086/SC2045/SC2035/SC2164 offline, exit 1) |
| shfmt | self-contained | baked | **shell VERIFIED** (`-d` reports an indentation diff offline, exit 1) |
| ast-grep | self-contained | baked | rust-parser rule |
| gitleaks | self-contained (rules embedded); `gitleaks dir` scans a non-git tree | baked | **secrets VERIFIED** (3 offline: private-key, generic-api-key, github-pat) |
| zizmor | self-contained (offline==online) | baked | **infra-ci VERIFIED** |
| actionlint | self-contained | baked | infra-ci |
| pinact | fails-loud (SHA resolve needs net) | baked | infra-ci |
| trivy | fails-loud → bake trivy-db | baked (DB non-empty, asserted) | infra/deps fixture |
| osv-scanner | fails-loud → bake OSV DB | baked (4 ecosystems, asserted) | deps fixture |
| Checkov | self-contained once installed (policies ship in the wheel; the pip install is the network op) | baked (`sabot/scanners:1`, pipx venv) | **iac VERIFIED** (11 failed / 7 passed offline as uid 1000, exit 1, incl. the open-port-22 SG check) |
| hadolint | self-contained (rules compiled in) | baked | **infra-extras VERIFIED** (DL3006/DL3008/DL3009/DL3015 offline) |
| kube-linter | self-contained (checks compiled in) | baked | **infra-extras VERIFIED** (5 checks fired offline) |
| tflint | baked-ok CORE ONLY (`--init` provider plugins need net; report must say core-only) | baked | **infra-extras VERIFIED** (2 core issues offline) |
| Grype | baked DB DECLINED: DB measures 2.0GB (v0.117.0) and base is inherited by every surface; trivy + osv-scanner already cover the same ecosystems | declined | n/a; the coverage is already there via trivy and osv-scanner |
| TruffleHog | baked-ok DETECTION ONLY; needs `--no-update` (self-updater aborts the scan on a read-only fs) + `--no-verification` | baked | **secrets VERIFIED** (2 offline, AWS + Github, both `Verified: false`) |
| Kingfisher | baked-ok DETECTION ONLY; `--no-validate` is mandatory offline, and the update check fails harmlessly (`update_check_status: failed`) | baked (`sabot/scanners:1`) | **secrets MEASURED** (1061 rules applied offline; 1 finding, `kingfisher.aws.2`, `Not Attempted`). Found FEWER than gitleaks on the same fixture: it missed the RSA private key and the `ghp_` PAT |
| GuardDog | self-contained for `scan` on a local path (heuristics ship in the wheel); `verify` queries the registry. **EXITS 0 ON A HIGH-RISK VERDICT** | baked (`sabot/scanners:1`, pipx venv) | **deps-py VERIFIED** (8.0/10 High risk offline, 2 risk categories / 7 issues on a seeded install-time exfil `setup.py`) |
| OSSF-Scorecard | needs-net (GH API), likely irreducible gap | fragment-pending | doc as gap? |
| poutine | self-contained (rules compiled in); subcommand is `analyze_local` | baked | **infra-ci VERIFIED** (injection rule fired offline) |
| Nuclei | baked-ok, and MUST pass BOTH `-templates` and `-ud` at the baked path (see below); `-duc` to stop the updater | baked (`sabot/scanners:1`, 13575 templates, all validating) | **web VERIFIED** (14 findings offline under `--read-only` as uid 1000 against a container-local `http.server`: robots-txt, tech-detect, 10 missing-header matchers) |
| Bearer | fails-loud without baked rules (`0 rules found ... could not be downloaded`); MUST pass `--external-rule-dir` | baked (`sabot/scanners:1`, bearer-rules pinned by SHA) | **code-py VERIFIED** (234 rules evaluated offline; `python_lang_os_command_injection` line 10 + `python_lang_weak_hash_md5` line 6) |
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
| Jazzer.js | self-contained (prebuilt addon; needs glibc >= 2.38, so trixie); MUST be installed LOCALLY, not `-g` (see below) | baked | **node-parser VERIFIED** (crash + artifact on the seeded no-colon TypeError) |
| fast-check | self-contained (library; reachable via `NODE_PATH`) | baked | **node-parser VERIFIED** (shrunk a counterexample for SEEDED-BUG-2 in 1 test, 4.9.0) |
| retire.js | degraded-silent → bake defs + `--jsrepo` | baked | node-parser |
| eslint-plugin-no-unsanitized | UNMEASURED (needs eslint) | fragment-pending | node-parser |

Jazzer.js must NOT be installed with `npm i -g`. Measured, `npm i -g @jazzer.js/core`
nests the `@jazzer.js` peers (bug-detectors, fuzzer, hooking, instrumentor) under
`core/node_modules/`, while core resolves them as SIBLINGS, so every run died before its
first input while `jazzer --version` still answered:

```
Error: ENOENT: no such file or directory, scandir
'/usr/local/lib/node_modules/@jazzer.js/bug-detectors/dist/internal'
```

A local install into a prefix dir (`/opt/jazzer`, symlinked onto PATH) produces the flat
layout core expects. The build now runs a real fuzz target and requires an `Uncaught
Exception` in the output, because this is the second time this tool has been installed,
asserted, and unrunnable: the first was the arm64 `dlopen` failure behind a passing
`jazzer --version` (bs-156).

Jazzer.js also needs a WRITABLE `TMPDIR`. `run-contained.sh` supplies one
(`TMPDIR=/scratch/tmp`), so the shipped path is fine, but a hand-rolled `docker run`
without it is not: measured under `--read-only`, the fuzzer still exits 77 on a real crash
while printing only three INFO lines, so the crash, the stack, and the artifact all vanish.
That is a found bug reported as noise, which is worse than a false clean.

## heavy engines (own layer; large)

| Tool | Offline req | Bake status | Fixture / test |
|---|---|---|---|
| CodeQL | needs-build-dep + query packs (~500MB); **NO linux-arm64 build exists** | BLOCKED on arm64, see below | code fixture (x86_64 only) |
| Joern | self-contained once unpacked (CPG build fetches nothing) | **baked** (`sabot/heavy:1`, arm64 zip, sha512-verified) | **VERIFIED** (56813-byte CPG offline as uid 1000; query located the `exec` sink at line 3) |
| OWASP-ZAP | baked-ok PASSIVE ONLY; MUST pass `-dir <writable>` (ignores `$HOME`, and exits 0 while refusing to start) | **baked** (`sabot/heavy:1`, Core zip, 21 bundled add-ons) | **VERIFIED** (6 alerts offline under `--read-only` against a container-local `http.server`) |

CodeQL cannot be baked on this host. Release v2.26.3 of `github/codeql-cli-binaries`
publishes `codeql-linux64.zip` (x86_64), `codeql-osx64.zip`, `codeql-win64.zip`, and the
all-x86-64 `codeql.zip`. There is no linux-arm64 asset, and upstream declined to commit to
one (`codeql-cli-binaries#157`, closed: "I can't make any promises on if or when";
`#97` still open). Emulating x86_64 for a whole-program analysis engine trades a bake for
an unusable runtime, so the arm64 surface treats CodeQL as absent rather than degraded. A
campaign that needs it must run on an x86_64 host, and a report that would have run it must
name the gap.

Joern and ZAP are JVM tools and therefore arch-portable, but base ships no JVM today, so
the heavy layer has to add one before either can be measured.

## The scanners surface: nuclei, bearer, checkov, guarddog, kingfisher

An OPTIONAL escalation image (`sabot/scanners:1`), not part of every campaign. Base is
inherited by all four language surfaces and none of them needs a Terraform policy set, so
these five live in their own layer, like `sabot/rust-extras:1`. Absent is a preflight note.

Nuclei needs BOTH `-templates` and `-ud` pointed at the baked tree. It resolves a
template's `helpers/` payload files against its DEFAULT template directory rather than the
tree given to `-templates`, so with `-templates` alone roughly 5000 templates failed to
compile:

```
[ERR] ... could not load payload file: cause="access to helper file
/opt/sabot-db/nuclei-templates/helpers/wordlists/wp-users.txt denied"
```

`-ud` repoints that default. Every one of those failures is per-template, so nuclei still
runs, still exits, and still reports whatever the surviving templates found.

One upstream template is quarantined at the current pin. `http/cves/2026/CVE-2026-3395.yaml`
fails to unmarshal (`line 52: cannot unmarshal !!str POST /a... into []string`), it is
broken at upstream HEAD as well, and `-et` does not suppress it because `-validate` loads
a template before excluding it. The layer deletes that one file, which keeps the build
gate at zero errors instead of grepping for a success string in output that also carries
errors.

GuardDog EXITS 0 on a high-risk verdict. Measured on a seeded install-time exfiltration
`setup.py`, it reported `High risk (8.0/10)`, 2 risk categories, 7 issues, and exit 0. Any
wrapper gating on the exit code records that package as clean. Parse `risk_score` and
`issues` from `--output-format json` instead.

Kingfisher found LESS than gitleaks on the same fixture: 1 finding against gitleaks' 3,
missing both the RSA private key and the `ghp_` PAT, with 1061 rules applied. It is
additive coverage, not a replacement, and a report that runs only kingfisher on a secrets
sweep understates what is there.

## Irreducible gaps (cannot work offline; document, do not pretend)

- **OSSF-Scorecard**: scores a repo via the GitHub API; no offline mode. Record as a coverage gap in any report that would run it.
- Any tool whose ONLY value is a live network probe (ZAP active scan against a remote, Kingfisher/TruffleHog live-credential validation): offline runs the static half only; the report must say which half ran.

## Seeding a secrets fixture

A secret detector's fixture MUST carry high-entropy synthetic values. Measured on the
`secrets` fixture, the textbook placeholders produce a near-empty result that reads as a
broken detector:

| Seeded value | gitleaks |
|---|---|
| `AKIAIOSFODNN7EXAMPLE` + the matching `wJalrXUt…` secret | no finding (AWS's own doc keys are allowlisted) |
| `ghp_` + 36 repeated `a` | no finding (fails the entropy check) |
| An RSA private-key header | `private-key` |
| `AKIA` + 16 random uppercase, 40 random alphanumerics, `ghp_` + 36 random | `generic-api-key`, `github-pat`, `private-key` |

Generate the values rather than copying them, and keep the fixture OUTSIDE the repo: a
credential-shaped literal in a tracked file trips the commit-time secret scanner, which is
the same class of tool the fixture exists to exercise.
