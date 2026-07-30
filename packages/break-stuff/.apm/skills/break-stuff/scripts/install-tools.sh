#!/usr/bin/env bash
set -euo pipefail

# install-tools.sh -- host preflight for a break-stuff campaign.
#
# Every target-touching tool runs in the surface image (references/isolation.md,
# "What runs where"), so this script installs NOTHING on the host. A host-side
# scanner would run the target's build code unconfined, the exact risk the container
# removes.
#
# The preflight is AUTHORITATIVE, not advisory: it asserts each expected tool
# actually answers INSIDE its image (via run-contained.sh --assert-tools, which keys
# on the tool's exit code), and exits non-zero when any is missing. It never prints
# a bare "OK" from an unchecked `<tool> --version`; a tool that errors "no such
# command" is a FAIL, because a missing scanner reported as present is why a whole
# threat dimension (supply chain / CI) came back a meaningless "zero findings".
#
#   install-tools.sh --probe   (default)   preflight: runtime + bd + git + assert every image tool
#   install-tools.sh --help
#
# The expected-tool manifest below is the single source of truth. Keep it in lockstep
# with references/isolation.md ("Assert the tools survived the build") and the surface
# Tools tables; a tool added to a surface doc but not here is a tool the preflight will
# not guard.

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_CONTAINED="$SKILL_DIR/scripts/run-contained.sh"

# image  :  comma-separated tools that MUST answer inside it.
# Kept in sync with isolation.md's assert table and each surface's Tools table.
IMAGE_TOOLS_base="semgrep,shellcheck,ripgrep,gitleaks,ast-grep,shfmt,zizmor,actionlint,pinact,trivy,osv-scanner"
IMAGE_TOOLS_rust="cargo-fuzz,cargo-audit,clippy,cargo-geiger"
IMAGE_TOOLS_python="atheris,hypothesis,bandit,ruff,semgrep"
IMAGE_TOOLS_node="jazzer,fast-check,retire"
SURFACES="base rust python node"

find_runtime() {
  for c in docker finch podman nerdctl; do
    command -v "$c" >/dev/null 2>&1 && { echo "$c"; return 0; }
  done
  return 1
}

probe() {
  echo "break-stuff host preflight (tools run in the container, not here):"
  local fail=0

  # Container runtime -- without one, the execution phases cannot run at all.
  local rt=""
  rt="$(find_runtime || true)"
  if [ -n "$rt" ]; then
    echo "  runtime:  $rt  (context: $("$rt" context show 2>/dev/null || echo default))"
  else
    echo "  runtime:  MISSING -- no docker/finch/podman/nerdctl. The campaign ABORTS: no runtime, no run (isolation.md, No container runtime)."
    fail=1
  fi

  # bd + git -- the orchestration primitives the agent needs on the host.
  command -v bd  >/dev/null 2>&1 && echo "  bd:       $(bd version 2>/dev/null | head -1)" || { echo "  bd:       MISSING -- required for the run graph (beads-store.md)."; fail=1; }
  command -v git >/dev/null 2>&1 && echo "  git:      $(git --version 2>/dev/null)"        || { echo "  git:      MISSING -- required to resolve the target (targeting.md)."; fail=1; }

  # Per-image tool assertion. For each built image, prove EVERY expected tool answers
  # inside it. A missing image or a missing tool is a FAIL, not a footnote.
  if [ -n "$rt" ]; then
    echo "  images (asserting every expected tool answers inside each):"
    local s img tools
    for s in $SURFACES; do
      img="break-stuff/$s:1"
      eval "tools=\"\${IMAGE_TOOLS_$s}\""
      if ! "$rt" image inspect "$img" >/dev/null 2>&1; then
        echo "    $img  ABSENT -- build from references/containers/Dockerfile.$s (then re-run --probe)"
        fail=1
        continue
      fi
      # --assert-tools exits 0 only when every named tool answers inside the image;
      # non-zero names the missing ones. This is the authoritative check.
      if out="$(bash "$RUN_CONTAINED" --assert-tools "$img" "$tools" 2>&1)"; then
        echo "    $img  OK ($tools)"
      else
        echo "    $img  FAIL -- $out"
        fail=1
      fi
    done
  fi

  if [ "$fail" -ne 0 ]; then
    echo "preflight: FAILED -- a precondition or a tool is missing above. Fix it before the campaign; a missing scanner reported as present returns a meaningless clean." >&2
    return 1
  fi
  echo "preflight: OK -- runtime, bd, git present and every expected tool answered inside its image."
}

usage() {
  cat <<'EOF'
usage: install-tools.sh [--probe | --help]

  --probe   (default) authoritative host preflight: container runtime, bd, git, and
            an assertion that EVERY expected tool answers inside its surface image.
            Exits non-zero if any precondition or tool is missing.

This script installs nothing. Target-touching tools run in the surface image; see
references/isolation.md (Provisioning) and scripts/detect-stacks.py.
EOF
}

case "${1:---probe}" in
  --probe) probe ;;
  -h|--help) usage ;;
  *) echo "install-tools.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac
