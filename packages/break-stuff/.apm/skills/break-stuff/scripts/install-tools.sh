#!/usr/bin/env bash
set -euo pipefail

# install-tools.sh
#
# Probe for and (on request) install the scanners and fuzzers the break-stuff
# skill drives. Tools are ALWAYS optional: break-stuff degrades gracefully and
# reports the gap when one is absent. This script installs nothing without an
# explicit --install / --all, and never uses sudo. When no package manager fits a
# tool, it prints the manual install step instead of failing.
#
# Modes:
#   install-tools.sh --probe                 report installed/missing per bundle (default)
#   install-tools.sh --list                  list bundles and their tools
#   install-tools.sh --install <bundle>...   install the named bundle(s)
#   install-tools.sh --all                   install every bundle
#   install-tools.sh --dry-run --install ... show the commands without running them
#
# Bundles:
#   core     opengrep gitleaks ast-grep                    (cross-surface floor)
#   shell    shellcheck shfmt                    (shell scripts, hooks, guards)
#   python   bandit atheris hypothesis            (Python code + fuzzing)
#   rust     cargo-audit cargo-fuzz clippy       (Rust code + fuzzing)
#   go       gosec                 (Go; go test -fuzz is built in)
#   js-ts    eslint jazzer.js fast-check          (project-local)
#   native   afl++ llvm                          (C/C++ with sanitizers)
#   infra    trivy checkov hadolint tflint kube-linter
#   ci       zizmor actionlint pinact            (workflow injection + pinning)
#   deps     osv-scanner                         (CVEs; prefer the dep-audit package)
#   supply   guarddog poutine kingfisher trufflehog
#                                                (MALICIOUS packages, CI/CD supply chain,
#                                                 validated secrets -- not just known CVEs)
#   mutate   radamsa zzuf honggfuzz              (seed-driven + coverage-guided mutators;
#                                                 source-only upstreams, so brew or a
#                                                 source build -- no mise/uvx route)
#   triage   casr shrinkray creduce             (crash dedup, classification, minimization)
#   schema   genson hypothesis-jsonschema jsf schemathesis  (structure-aware JSON/API generation)
#   grammar  grammarinator dharma                (grammar-aware generation for DSLs)
#   web      eslint-no-unsanitized retire.js nuclei zap  (frontend XSS/DOM + live dev-server DAST)
#   build    (read-driven; npm --ignore-scripts, cargo metadata)  (build/install-time execution)
#   agentcfg snyk-agent-scan agentic-radar       (STATIC audit of MCP/agent CONFIG: tool
#                                                 poisoning, over-grant, unpinned servers.
#                                                 NOT LLM red-teaming: garak and promptfoo
#                                                 attack a MODEL, a different target.)
#   deep     codeql cargo-geiger                 (OPT-IN: interprocedural taint)
#
# RUN ROUTE, not just install. Most tools here never need a persistent install:
# they are invocable on demand via `uvx`, `npx`, `cargo run`, `go run`, or a mise
# backend. `--routes` prints the ephemeral invocation per tool, which is what the
# skill's run recipes use. `--install` is for the few tools that must be resident
# (a compiled mutator, an instrumented-build toolchain) or when the user prefers a
# pinned local copy.
#
# Per-tool default-on vs opt-in tiers live in the surface docs (the source of
# truth). Records: name|probe-bin|key|hint[|pkg][|mise-spec][|run-route]
#
# Portability floor: bash 3.2.57 + BSD userland. No mapfile, no associative
# arrays, no GNU-only flags.

BUNDLES="core shell python rust go js-ts native infra ci deps supply mutate triage schema grammar agentcfg web build deep"

tools_for() {
  # Record: name|probe-bin|installer-key|hint|pkg|mise-spec|run-route
  # run-route is the EPHEMERAL invocation (uvx/npx/go run/cargo subcommand). Empty
  # means the tool must be resident (compiled, or needs an instrumented build).
  case "$1" in
    core)
      echo "gitleaks|gitleaks|brew|mise use aqua:gitleaks/gitleaks|gitleaks|aqua:gitleaks/gitleaks|mise x aqua:gitleaks/gitleaks -- gitleaks"
      echo "ast-grep|ast-grep|cargo|mise use cargo:ast-grep  (npm pkg is @ast-grep/cli and the bin is ast-grep; bare npm ast-grep is an unrelated stub)|ast-grep|cargo:ast-grep|npx --yes -p @ast-grep/cli ast-grep"
      echo "opengrep|opengrep|ubi|mise use ubi:opengrep/opengrep  (LGPL semgrep fork; restores rules the semgrep licence change closed)|opengrep|ubi:opengrep/opengrep|mise x ubi:opengrep/opengrep -- opengrep"
      ;;
    shell)
      echo "shellcheck|shellcheck|brew|mise use aqua:koalaman/shellcheck|shellcheck|aqua:koalaman/shellcheck|mise x aqua:koalaman/shellcheck -- shellcheck"
      echo "shfmt|shfmt|brew|mise use aqua:mvdan/sh|shfmt|aqua:mvdan/sh|mise x aqua:mvdan/sh -- shfmt"
      ;;
    python)
      echo "bandit|bandit|pipx|uvx bandit|bandit|pipx:bandit|uvx bandit"
      echo "atheris|atheris|pip-user|uvx --with atheris python  (needs a matching CPython build)|atheris||uvx --with atheris python"
      echo "hypothesis|hypothesis|pip-user|prefer the project dev deps; else: uvx --with hypothesis pytest|hypothesis||uvx --with hypothesis pytest"
      echo "hypofuzz|hypofuzz|pip-user|OPT-IN coverage-guided hypothesis: uvx --with hypofuzz hypothesis fuzz|hypofuzz||uvx --with hypofuzz hypothesis fuzz"
      ;;
    rust)
      echo "clippy|cargo-clippy|rustup|rustup component add clippy|clippy||cargo clippy"
      echo "cargo-audit|cargo-audit|cargo|mise use cargo:cargo-audit|cargo-audit|cargo:cargo-audit|cargo audit"
      echo "cargo-fuzz|cargo-fuzz|cargo|mise use cargo:cargo-fuzz  (nightly toolchain needed for -Zsanitizer)|cargo-fuzz|cargo:cargo-fuzz|cargo fuzz"
      echo "miri|cargo-miri|rustup|rustup +nightly component add miri  (interprets MIR to find real UB in unsafe: OOB, use-after-free, invalid aliasing)|miri||cargo +nightly miri"
      echo "cargo-careful|cargo-careful|cargo|mise use cargo:cargo-careful  (runs std with debug assertions and extra UB checks)|cargo-careful|cargo:cargo-careful|cargo careful"
      echo "cargo-deny|cargo-deny|cargo|mise use cargo:cargo-deny  (advisory, licence, and banned-crate policy)|cargo-deny|cargo:cargo-deny|cargo deny"
      echo "cargo-semver-checks|cargo-semver-checks|cargo|mise use cargo:cargo-semver-checks  (breaking-change detection vs a baseline)|cargo-semver-checks|cargo:cargo-semver-checks|cargo semver-checks"
      ;;
    go)
      echo "gosec|gosec|go|go run github.com/securego/gosec/v2/cmd/gosec@latest|gosec|go:github.com/securego/gosec/v2/cmd/gosec|go run github.com/securego/gosec/v2/cmd/gosec@latest"
      ;;
    js-ts)
      echo "eslint|eslint|npm-local|npm i -D eslint eslint-plugin-security  (project-local: the repo config and plugin versions must match)|eslint||npx eslint"
      echo "jazzer.js|jazzer|npm-local|npm i -D @jazzer.js/core  (project-local; coverage-guided JS fuzzing)|@jazzer.js/core||npx --yes -p @jazzer.js/core jazzer"
      echo "fast-check|fast-check|npm-local|npm i -D fast-check  (project-local library, imported by a test)|fast-check||"
      ;;
    native)
      echo "afl++|afl-fuzz|brew|mise use ubi:AFLplusplus/AFLplusplus, or brew install afl++  (needs an instrumented build of the target)|afl++|ubi:AFLplusplus/AFLplusplus|"
      echo "llvm|clang|brew|mise use clang, or brew install llvm  (for -fsanitize=address,undefined and libFuzzer)|llvm|clang|"
      ;;
    infra)
      echo "trivy|trivy|brew|mise use aqua:aquasecurity/trivy|trivy|aqua:aquasecurity/trivy|mise x aqua:aquasecurity/trivy -- trivy"
      echo "checkov|checkov|pipx|uvx checkov|checkov|pipx:checkov|uvx checkov"
      echo "hadolint|hadolint|brew|mise use aqua:hadolint/hadolint|hadolint|aqua:hadolint/hadolint|mise x aqua:hadolint/hadolint -- hadolint"
      echo "tflint|tflint|brew|mise use aqua:terraform-linters/tflint|tflint|aqua:terraform-linters/tflint|mise x aqua:terraform-linters/tflint -- tflint"
      echo "kube-linter|kube-linter|brew|mise use aqua:stackrox/kube-linter|kube-linter|aqua:stackrox/kube-linter|mise x aqua:stackrox/kube-linter -- kube-linter"
      ;;
    ci)
      echo "zizmor|zizmor|pipx|uvx zizmor, or: mise use aqua:zizmorcore/zizmor  (workflow-injection dataflow)|zizmor|aqua:zizmorcore/zizmor|uvx zizmor"
      echo "actionlint|actionlint|brew|mise use aqua:rhysd/actionlint|actionlint|aqua:rhysd/actionlint|mise x aqua:rhysd/actionlint -- actionlint"
      echo "pinact|pinact|brew|mise use aqua:suzuki-shunsuke/pinact|pinact|aqua:suzuki-shunsuke/pinact|mise x aqua:suzuki-shunsuke/pinact -- pinact"
      ;;
    deps)
      echo "osv-scanner|osv-scanner|brew|mise use aqua:google/osv-scanner  (prefer the dep-audit package when present)|osv-scanner|aqua:google/osv-scanner|go run github.com/google/osv-scanner/cmd/osv-scanner@latest"
      ;;
    supply)
      echo "guarddog|guarddog|pipx|uvx guarddog  (MALICIOUS package detection: typosquats, install-time exfil, obfuscated payloads -- not CVEs)|guarddog||uvx guarddog"
      echo "poutine|poutine|ubi|mise use ubi:boostsecurityio/poutine  (CI/CD supply-chain: poisoned pipeline execution, artifact tampering; complements zizmor)|poutine|ubi:boostsecurityio/poutine|mise x ubi:boostsecurityio/poutine -- poutine"
      echo "kingfisher|kingfisher|ubi|mise use ubi:mongodb/kingfisher  (secrets scanner that LIVE-VALIDATES a hit against the provider, so a finding is a confirmed live key)|kingfisher|ubi:mongodb/kingfisher|mise x ubi:mongodb/kingfisher -- kingfisher"
      echo "trufflehog|trufflehog|ubi|mise use ubi:trufflesecurity/trufflehog  (800+ verified detectors plus git-history scanning)|trufflehog|ubi:trufflesecurity/trufflehog|mise x ubi:trufflesecurity/trufflehog -- trufflehog"
      ;;
    mutate)
      echo "radamsa|radamsa|brew|brew install radamsa  (compiled, source-only upstream; seed-driven byte mutator)|radamsa||"
      echo "zzuf|zzuf|brew|brew install zzuf  (compiled; deterministic bit-flipping, record the seed to reproduce)|zzuf||"
      echo "honggfuzz|honggfuzz|none|build from source: https://github.com/google/honggfuzz  (Linux-first; coverage-guided)|honggfuzz||"
      ;;
    triage)
      echo "casr|casr-cluster|cargo|mise use cargo:casr  (crash dedup by stack + severity classification)|casr|cargo:casr|"
      echo "shrinkray|shrinkray|pipx|uvx shrinkray  (generic test-case reducer; replaces the archived halfempty)|shrinkray||uvx shrinkray"
      echo "creduce|creduce|brew|brew install creduce  (C/C++ source reduction; cvise is not published to PyPI)|creduce||"
      ;;
    schema)
      echo "genson|genson|pipx|uvx genson  (infer a JSON Schema from the repo's own fixtures)|genson|pipx:genson|uvx genson"
      echo "hypothesis-jsonschema|hypothesis_jsonschema|pip-user|library: uvx --with hypothesis-jsonschema --with hypothesis pytest|hypothesis-jsonschema||uvx --with hypothesis-jsonschema --with hypothesis pytest"
      echo "jsf|jsf|pipx|uvx --from jsf jsf  (fake data from a JSON Schema)|jsf|pipx:jsf|uvx --from jsf jsf"
      echo "schemathesis|schemathesis|pipx|uvx schemathesis  (derive cases from an OpenAPI/GraphQL spec)|schemathesis|pipx:schemathesis|uvx schemathesis"
      ;;
    grammar)
      echo "grammarinator|grammarinator-generate|pipx|uvx --from grammarinator grammarinator-generate  (ANTLR grammar-aware)|grammarinator|pipx:grammarinator|uvx --from grammarinator grammarinator-generate"
      echo "dharma|dharma|pipx|uvx --from dharma dharma  (lighter grammar generation, no ANTLR)|dharma|pipx:dharma|uvx --from dharma dharma"
      ;;
    agentcfg)
      echo "snyk-agent-scan|snyk-agent-scan|pipx|uvx snyk-agent-scan scan <config>  (MCP config audit: tool poisoning, cross-origin escalation, rug-pull. NEEDS a SNYK_TOKEN, and LAUNCHES stdio servers as subprocesses unless the consent prompt is declined)|snyk-agent-scan||uvx snyk-agent-scan"
      echo "agentic-radar|agentic-radar|pipx|uvx agentic-radar  (static map of an agentic system's tools and flows; upstream quiet since 2025-11)|agentic-radar||uvx agentic-radar"
      echo "opengrep-tob|opengrep|ubi|mise x ubi:opengrep/opengrep -- opengrep --config p/trailofbits  (Trail of Bits rule pack via opengrep; fetches over the network, so it needs agreement)|opengrep|ubi:opengrep/opengrep|mise x ubi:opengrep/opengrep -- opengrep --config p/trailofbits"
      ;;
    web)
      echo "retire|retire|npm|npx --yes retire  (known-vulnerable JS libs in the bundle)|retire||npx --yes retire"
      echo "eslint-no-unsanitized|eslint|npm-local|npm i -D eslint-plugin-no-unsanitized eslint-plugin-security  (project-local; DOM-sink lint)|eslint-plugin-no-unsanitized||npx eslint"
      echo "nuclei|nuclei|ubi|mise use ubi:projectdiscovery/nuclei  (live DAST against the project's OWN dev server only)|nuclei|ubi:projectdiscovery/nuclei|mise x ubi:projectdiscovery/nuclei -- nuclei"
      echo "zap|zap-baseline.py|none|docker run --rm -t ghcr.io/zaproxy/zaproxy zap-baseline.py  (passive DAST via the ZAP image; loopback target only)|zap||"
      ;;
    build)
      echo "cargo-metadata|cargo|rustup|ships with cargo: cargo metadata --format-version 1  (enumerate build-deps and proc-macros)|cargo||cargo metadata"
      echo "npm-dryrun|npm|brew|ships with npm: npm install --ignore-scripts --dry-run  (which packages want install scripts)|npm||npm install --ignore-scripts --dry-run"
      ;;
    deep)
      echo "codeql|codeql|brew|mise use codeql  (OPT-IN: interprocedural taint; a database build costs minutes)|codeql|codeql|mise x codeql -- codeql"
      echo "cargo-geiger|cargo-geiger|cargo|mise use cargo:cargo-geiger  (OPT-IN: unsafe census; slow)|cargo-geiger|cargo:cargo-geiger|cargo geiger"
      echo "joern|joern|ubi|mise use ubi:joernio/joern  (code property graph; real interprocedural taint via CPGQL)|joern|ubi:joernio/joern|mise x ubi:joernio/joern -- joern"
      echo "weggli|weggli|cargo|mise use cargo:weggli  (C/C++ semantic pattern search for vuln shapes)|weggli|cargo:weggli|"
      echo "bearer|bearer|ubi|mise use ubi:Bearer/bearer  (dataflow SAST for sensitive-data leak paths)|bearer|ubi:Bearer/bearer|mise x ubi:Bearer/bearer -- bearer"
      ;;
    *)
      return 1
      ;;
  esac
}

# ---- helpers --------------------------------------------------------------

have() { command -v "$1" >/dev/null 2>&1; }

# runnable: a binary may be on PATH yet NOT actually run -- most commonly a
# version-manager shim (mise/asdf) with no version selected, which dies with
# "No version is set for shim: <tool>" on every call. So `command -v` is not
# enough; smoke-test by invoking the tool. Returns 0 only if the tool both
# exists AND a trivial invocation succeeds. Hardening:
#   - stdin from /dev/null so a tool that reads stdin can't block the probe;
#   - a short timeout so a tool that ignores --version can't hang the probe;
#   - try --version then --help; discard output, judge by exit status.
_TIMEOUT=""
if command -v timeout >/dev/null 2>&1; then _TIMEOUT="timeout 8"
elif command -v gtimeout >/dev/null 2>&1; then _TIMEOUT="gtimeout 8"; fi
runnable() {
  command -v "$1" >/dev/null 2>&1 || return 1
  $_TIMEOUT "$1" --version >/dev/null 2>&1 </dev/null && return 0
  $_TIMEOUT "$1" --help >/dev/null 2>&1 </dev/null && return 0
  return 1
}

# Python importables (atheris, hypothesis) are not binaries: probe by import.
py_importable() {
  $_TIMEOUT python3 -c "import $1" >/dev/null 2>&1 </dev/null
}

probe_one() {
  # $1 = probe binary name. Routes the two import-only tools to py_importable.
  case "$1" in
    atheris|hypothesis|hypofuzz|hypothesis-jsonschema) py_importable "${1//-/_}" ;;
    *) runnable "$1" ;;
  esac
}

field() { printf '%s' "$1" | cut -d'|' -f"$2"; }

# mise is a universal version manager. When present (and not disabled) it is the
# preferred *installer* for tools NOT already on PATH: it pins versions and
# installs reproducibly, with no sudo. A tool already on PATH is used as-is.
# When mise DOES install, it does so REPO-LOCALLY (`mise use` in the current dir,
# writing ./mise.toml) -- never `-g`, so the user's global config is untouched.
PREFER_MISE=0
have mise && PREFER_MISE=1

manager_cmd() {
  if [ "$PREFER_MISE" -eq 1 ]; then
    case "$1" in
      cargo)     echo "mise-cargo"; return ;;
      npm)       echo "mise-npm"; return ;;
      pipx)      echo "mise-pipx"; return ;;
      go)        echo "mise-reg"; return ;;
      brew)      echo "mise-reg"; return ;;
      ubi)       echo "mise-reg"; return ;;
      # npm-local stays project-local; rustup stays a toolchain component;
      # pip-user stays a user-site install (atheris needs the real CPython).
    esac
  fi
  case "$1" in
    brew)      if have brew; then echo "brew"; fi ;;
    pipx)      if have pipx; then echo "pipx"; elif have uv; then echo "uv-tool"; fi ;;
    npm)       if have npm; then echo "npm"; fi ;;
    npm-local) if have npm; then echo "npm-local"; fi ;;
    cargo)     if have cargo; then echo "cargo"; fi ;;
    go)        if have go; then echo "go"; fi ;;
    rustup)    if have rustup; then echo "rustup"; fi ;;
    ubi)       if have mise; then echo "mise-reg"; fi ;;
    none)      echo "" ;;
    pip-user)  if have python3; then echo "pip-user"; fi ;;
    *)         echo "" ;;
  esac
}

DRY_RUN=0
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  + %s\n' "$*"
  else
    printf '  + %s\n' "$*"
    "$@"
  fi
}

install_one() {
  rec="$1"
  name="$(field "$rec" 1)"
  bin="$(field "$rec" 2)"
  key="$(field "$rec" 3)"
  hint="$(field "$rec" 4)"

  pkg="$(field "$rec" 5)"
  [ -z "$pkg" ] && pkg="$name"

  mise_spec="$(field "$rec" 6)"
  [ -z "$mise_spec" ] && mise_spec="$bin"

  if probe_one "$bin"; then
    printf '  = %s already installed\n' "$name"
    return 0
  fi
  if have "$bin"; then
    printf '  ~ %s present but not runnable (shim?) -- (re)installing to make it work\n' "$name"
  fi

  mgr="$(manager_cmd "$key")"
  if [ -z "$mgr" ]; then
    printf '  ! %s: no supported manager on PATH -- install manually:\n      %s\n' "$name" "$hint"
    return 0
  fi

  printf '  installing %s via %s ...\n' "$name" "$mgr"
  case "$mgr" in
    brew)      run brew install "$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    pipx)      run pipx install "$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    uv-tool)   run uv tool install "$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    npm)       run npm install -g "$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    cargo)     run cargo install "$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    pip-user)  run python3 -m pip install --user "$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    go)
      go_path="${mise_spec#go:}"
      case "$go_path" in *@*) : ;; *) go_path="${go_path}@latest" ;; esac
      run go install "$go_path" || printf '      (failed -- try: %s)\n' "$hint" ;;
    rustup)    run rustup component add clippy || printf '      (failed -- try: %s)\n' "$hint" ;;
    mise-cargo) run mise use "cargo:$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    mise-npm)   run mise use "npm:$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    mise-pipx)  run mise use "pipx:$pkg" || printf '      (failed -- try: %s)\n' "$hint" ;;
    mise-reg)   run mise use "$mise_spec" || printf '      (failed -- try: %s)\n' "$hint" ;;
    npm-local)
      printf '  ! %s is project-local -- install inside the repo, not globally:\n      %s\n' "$name" "$hint"
      ;;
  esac
}

probe_bundle() {
  b="$1"
  installed=0; missing=0; shim=0
  printf '\n[%s]\n' "$b"
  while IFS= read -r rec; do
    [ -z "$rec" ] && continue
    name="$(field "$rec" 1)"; bin="$(field "$rec" 2)"; hint="$(field "$rec" 4)"
    if probe_one "$bin"; then
      printf '  ok   %s\n' "$name"
      installed=$((installed + 1))
    elif have "$bin"; then
      # On PATH but a trivial invocation fails -- version-manager shim with no
      # version set, broken install, etc. Treat as NOT usable: the run must skip
      # this tool (or install it), never assume it works.
      printf '  SHIM %s   -- on PATH but not runnable; install to activate: %s\n' "$name" "$hint"
      shim=$((shim + 1))
    else
      printf '  MISS %s   -- %s\n' "$name" "$hint"
      missing=$((missing + 1))
    fi
  done <<EOF
$(tools_for "$b")
EOF
  if [ "$shim" -gt 0 ]; then
    printf '  (%d usable, %d unrunnable/shim, %d missing)\n' "$installed" "$shim" "$missing"
  else
    printf '  (%d installed, %d missing)\n' "$installed" "$missing"
  fi
}

route_bundle() {
  b="$1"
  printf '\n[%s]\n' "$b"
  while IFS= read -r rec; do
    [ -z "$rec" ] && continue
    name="$(field "$rec" 1)"; route="$(field "$rec" 7)"; hint="$(field "$rec" 4)"
    if [ -n "$route" ]; then
      printf '  %-22s %s\n' "$name" "$route"
    else
      printf '  %-22s (resident install required) %s\n' "$name" "$hint"
    fi
  done <<EOF
$(tools_for "$b")
EOF
}

list_bundle() {
  b="$1"
  printf '\n[%s]\n' "$b"
  while IFS= read -r rec; do
    [ -z "$rec" ] && continue
    printf '  %-16s %s\n' "$(field "$rec" 1)" "$(field "$rec" 4)"
  done <<EOF
$(tools_for "$b")
EOF
}

install_bundle() {
  b="$1"
  if ! tools_for "$b" >/dev/null 2>&1; then
    printf 'break-stuff: unknown bundle "%s" (known: %s)\n' "$b" "$BUNDLES" >&2
    return 1
  fi
  printf '\n[%s]\n' "$b"
  while IFS= read -r rec; do
    [ -z "$rec" ] && continue
    install_one "$rec"
  done <<EOF
$(tools_for "$b")
EOF
}

usage() {
  cat <<'EOF'
usage: install-tools.sh [--probe | --list | --install <bundle>... | --all] [--dry-run]

  --probe              report installed/missing tools per bundle (default)
  --routes             print the ephemeral run route per tool (uvx/npx/go run/cargo);
                       this is what the skill's run recipes use, so most tools need
                       no install at all
  --list               list every bundle and its tools
  --install <bundle>   install the named bundle(s): core shell python rust go
                       js-ts native infra ci deps supply mutate triage schema
                       grammar llm deep
  --all                install every bundle
  --dry-run            print install commands without running them
  --no-mise            ignore mise even if present; use brew/cargo/npm/pipx directly

Tools are always optional; break-stuff skips and reports the gap when one is
absent. Never sudo. A tool already on PATH is used as-is (never reinstalled). When
a tool is missing and `mise` is on PATH, mise installs it REPO-LOCALLY (`mise use`,
writing ./mise.toml in the current directory -- not global config); pass --no-mise
to use brew/cargo/npm/pipx directly instead. Project-local tools (eslint,
jazzer.js, fast-check) are reported, not installed globally -- add them to the
repo's own devDependencies.

cargo-fuzz needs a nightly toolchain for -Zsanitizer=address; this script installs
the binary and reports the toolchain requirement rather than switching your default.
EOF
}

# ---- arg parsing ----------------------------------------------------------

mode="probe"
targets=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --probe)   mode="probe" ;;
    --routes)  mode="routes" ;;
    --list)    mode="list" ;;
    --no-mise) PREFER_MISE=0 ;;
    --all)     mode="install"; targets="$BUNDLES" ;;
    --install) mode="install" ; shift
               while [ "$#" -gt 0 ] && [ "${1#--}" = "$1" ]; do targets="$targets $1"; shift; done
               continue ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'install-tools.sh: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$mode" in
  probe)
    printf 'break-stuff tool probe (all tools optional; a missing one is a reported gap)\n'
    for b in $BUNDLES; do probe_bundle "$b"; done
    printf '\nInstall a bundle with: install-tools.sh --install <bundle>\n'
    ;;
  list)
    for b in $BUNDLES; do list_bundle "$b"; done
    ;;
  routes)
    printf 'break-stuff run routes (ephemeral where possible; no install needed)\n'
    for b in $BUNDLES; do route_bundle "$b"; done
    printf '\nA tool marked "resident install required" is compiled or needs an\ninstrumented build; install it with --install <bundle>.\n'
    ;;
  install)
    if [ -z "$targets" ]; then
      printf 'install-tools.sh: --install needs at least one bundle name\n' >&2
      usage >&2; exit 2
    fi
    [ "$DRY_RUN" -eq 1 ] && printf '(dry run -- no changes will be made)\n'
    for b in $targets; do install_bundle "$b"; done
    printf '\nDone. Re-run --probe to confirm.\n'
    ;;
esac
