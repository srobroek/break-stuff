# Surface: Code memory and logic

Application code, judged by whether attacker-influenced input reaches a dangerous
operation. The organizing question is always the taint path: which entry points
accept untrusted data, and what does that data reach.

## Detect

Any `*.rs` `*.go` `*.py` `*.ts` `*.js` `*.c` `*.cpp` `*.java` `*.rb` `*.php` in
the resolved file list. Prioritize files reachable from an entry point: HTTP
handlers, CLI argument parsing, deserializers, file readers, message consumers,
and FFI boundaries.

## Tools

| Tool | Tier | Class | Run recipe | Catches | Overlap |
|------|------|-------|-----------|---------|---------|
| semgrep | default-on | local | `mise x ubi:opengrep/opengrep -- opengrep --config p/python --config p/command-injection --json <files>` (per-language pack for the detected stack) | injection, unsafe deserialization, hardcoded secrets, weak crypto, path traversal | registry packs; intra-file dataflow. `--config auto` fetches over the network, so it needs the user's agreement |
| bandit | default-on | local | `bandit -f json -r <paths>` | Python: `shell=True`, `pickle`, `yaml.load`, `assert` for control flow, weak hashes | semgrep covers some, bandit is Python-specific and cheaper |
| gosec | default-on | local | `gosec -fmt=json ./...` | Go: unhandled errors on security calls, SQL string building, weak rand, TLS config | golangci-lint bundles it; skip when that ran with gosec enabled |
| cargo-audit | default-on | global | `cargo audit --json` | Rust: RUSTSEC advisories in the dependency tree | overlaps osv-scanner from `infra.md`; keep for Rust-specific advisories |
| cargo-geiger | opt-in | global | `cargo geiger --output-format Json` | Rust: `unsafe` usage census across dependencies | off by default, since it is slow and reports rather than judges |
| clippy | default-on | local | `cargo clippy --message-format=json -- -W clippy::arithmetic_side_effects -W clippy::indexing_slicing -W clippy::unwrap_used` | Rust: panic paths, integer overflow, slicing panics | honors project config first; add these lints only when the repo pins none |
| CodeQL | opt-in | global | `codeql database create` then `codeql database analyze --format=sarif-latest` | genuine interprocedural taint tracking | the only real interprocedural engine here, off by default because a database build costs minutes |
| ruff | default-on | local | `ruff check --extend-select S,B,ASYNC --output-format json .` | Python: the bandit `S` ruleset plus bugbear, at ruff speed | overlaps bandit; run both, since ruff misses some bandit checks |
| eslint security plugins | opt-in | local | `npx eslint --format json .` with `eslint-plugin-security` | JS/TS: dynamic `require`, `eval`, unsafe regex | project-local install, so it is opt-in |

MUST Run `opengrep --config auto` only with the user's agreement, since it fetches rules over the network. The shipped ruleset works offline.
MUST Name the registry pack that fits the detected language rather than `--config auto`, since auto fetches an unpredictable rule set over the network and its result is not reproducible.

## Attack checklist

| # | Attack | Where it hides | Confirm by |
|---|--------|----------------|-----------|
| 1 | Injection at a sink | SQL built by concatenation, shell calls, template rendering, LDAP, XPath | trace from an entry point to the sink with no escaping between them |
| 2 | Unsafe deserialization | `pickle`, `yaml.load`, Java readObject, `serde` with untrusted `deny_unknown_fields` off | confirm the format allows type or code control |
| 3 | Path traversal | file reads joining user input, archive extraction, upload handling | supply `../`, an absolute path, a symlink, or a zip entry escaping the target dir |
| 4 | ReDoS | a regex with nested quantifiers applied to user input | measure wall-clock growth against input length; superlinear growth confirms it |
| 5 | Unbounded allocation | reading a body or file into memory without a cap, a length field trusted from input | send a large declared length and watch resident memory |
| 6 | Integer overflow reaching an index or size | arithmetic on a length or count, cast narrowing, Rust release-mode wrapping | supply boundary values and check for a panic or a wrong allocation size |
| 7 | Panic or unwrap on input | `unwrap`, `expect`, `[]` indexing, `unreachable!` on parsed data | feed malformed input to the parser and observe the panic |
| 8 | TOCTOU | check-then-use on files, permissions, or balances | inspect whether the two operations share a lock or an atomic primitive |
| 9 | Authorization logic gap | a permission check missing on one handler among many, or performed after the effect | enumerate every handler and compare which enforce the check |
| 10 | Unsafe block invariant violation | Rust `unsafe`, C pointer arithmetic, FFI boundaries | check the documented invariant against every caller, including ones passing malformed input |
| 11 | Weak crypto or bad randomness | `math/rand` for tokens, MD5 or SHA1 for authentication, a static IV or key | check whether the value is security-bearing |
| 12 | Secret in code or log | credentials in source, tokens written to logs or error messages | grep the log statements along the error path for the secret variable |
| 13 | Race in shared state | a counter, cache, or map mutated without synchronization | run the concurrency harness from `harnesses.md` under a race detector |
| 14 | SSRF and open redirect | a URL taken from input and fetched, a redirect target from a parameter | check whether the host is validated against an allowlist |

## Harness patterns

Native fuzzing per language, with the runner and entry point stated in
`fuzzing.md`:

| Language | Runner | Entry point shape |
|---|---|---|
| Rust | `cargo fuzz` (libFuzzer) or `arbitrary` with `proptest` | `fuzz_target!(\|data: &[u8]\|)` around the parser |
| Go | `go test -fuzz` | `func FuzzX(f *testing.F)` seeded from testdata |
| Python | `atheris`, or `hypothesis` for property tests | the module's public parse or handle function |
| JS/TS | `jazzer.js`, or `fast-check` for property tests | the exported handler |
| C/C++ | libFuzzer or AFL++ with ASan and UBSan | `LLVMFuzzerTestOneInput` |

MUST Build with the sanitizers the language offers, since a memory bug without ASan is silent corruption rather than a crash.
DEFAULT Seed every corpus from the repo's own test fixtures before generating inputs, because a real message shape reaches deeper code than random bytes.

## Impact calibration

| Level | Meaning on this surface |
|---|---|
| CRITICAL | remote input reaches code execution, authentication bypass, or arbitrary file write |
| HIGH | remote input reaches SQL, a file read outside scope, memory corruption, or a crash in a service process |
| MEDIUM | a panic or unbounded allocation reachable from a local entry point, a race with a plausible window, or weak crypto on a security-bearing value |
| LOW | a theoretical overflow behind validation, a panic in a test-only path, or a hardcoded value with no secret content |

## False-positive traps

| Looks like a finding | Clears when |
|---|---|
| SQL built by concatenation | every interpolated value is a compile-time constant or comes from an enum |
| `unwrap` on a parse | the parsed value is a literal in the same function, so the panic is unreachable |
| Weak hash flagged by a scanner | the hash is a cache key or checksum rather than an authentication primitive |
| `math/rand` flagged | the value is a jitter or shuffle rather than a token or key |
| Path join with a variable | the variable was resolved and prefix-checked against a canonical root earlier in the same function |
| Integer overflow in Rust | the crate builds with `overflow-checks = true` in the release profile, making the case a panic already reported elsewhere |
| Unbounded read | an upstream framework or proxy enforces a body cap, which the report must cite as the mitigating control |
