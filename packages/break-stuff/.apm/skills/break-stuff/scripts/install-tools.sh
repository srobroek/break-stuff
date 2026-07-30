#!/usr/bin/env bash
set -euo pipefail

# install-tools.sh -- host preflight for a break-stuff campaign.
#
# Since every target-touching tool runs in the surface image (references/isolation.md,
# "What runs where"), this script installs NOTHING on the host. A host-side scanner
# would run the target's build code unconfined, the exact risk the container removes.
#
# Its only job is the host preflight the run needs before step 3: is a container
# runtime present, are bd and git present, and which break-stuff surface images are
# built. The scanners, fuzzers, and the target's dev-deps live in the image and are
# provisioned there (isolation.md, "Provisioning and extending the image");
# scripts/detect-stacks.py discovers the manifests to bake.
#
#   install-tools.sh --probe   (default)   report runtime + bd + git + built images
#   install-tools.sh --help

SURFACES="base rust python node"

probe() {
  echo "break-stuff host preflight (tools run in the container, not here):"

  # Container runtime -- without one, the execution phases cannot run at all.
  rt=""
  for c in docker finch podman nerdctl; do
    if command -v "$c" >/dev/null 2>&1; then rt="$c"; break; fi
  done
  if [ -n "$rt" ]; then
    echo "  runtime:  $rt  (context: $("$rt" context show 2>/dev/null || echo default))"
  else
    echo "  runtime:  MISSING -- no docker/finch/podman/nerdctl. The campaign ABORTS: no runtime, no run (isolation.md, No container runtime)."
  fi

  # bd + git -- the orchestration primitives the agent needs on the host.
  command -v bd  >/dev/null 2>&1 && echo "  bd:       $(bd version 2>/dev/null | head -1)" || echo "  bd:       MISSING -- required for the run graph (beads-store.md)."
  command -v git >/dev/null 2>&1 && echo "  git:      $(git --version 2>/dev/null)"        || echo "  git:      MISSING -- required to resolve the target (targeting.md)."

  # Which surface images are built. Missing ones are built/extended at step 3.
  if [ -n "$rt" ]; then
    echo "  images:"
    for s in $SURFACES; do
      if "$rt" image inspect "break-stuff/$s:1" >/dev/null 2>&1; then
        echo "    break-stuff/$s:1  built"
      else
        echo "    break-stuff/$s:1  ABSENT -- build from references/containers/Dockerfile.$s"
      fi
    done
  fi
}

usage() {
  cat <<'EOF'
usage: install-tools.sh [--probe | --help]

  --probe   (default) report the host preflight: container runtime, bd, git, and
            which break-stuff surface images are built.

This script installs nothing. Target-touching tools run in the surface image; see
references/isolation.md (Provisioning) and scripts/detect-stacks.py.
EOF
}

case "${1:---probe}" in
  --probe) probe ;;
  -h|--help) usage ;;
  *) echo "install-tools.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac
