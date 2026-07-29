#!/usr/bin/env bash
set -euo pipefail

# run-contained.sh
#
# The ONE sanctioned way a break-stuff campaign executes untrusted-shaped work: a
# hostile harness, a build script, a dev server. It runs the command inside a
# locked-down, disposable container and copies back only what the container wrote
# to a named artifacts volume. The agent stays on the host; nothing of the agent
# enters the container.
#
# Isolation, all enforced as flags the kernel honours, proven on this host:
#   -v <target>:/target:ro       target READ-ONLY   (a write to the target is impossible)
#   named volume at /artifacts    the only writable path; copied out after, then removed
#   --network none (default)      no exfil; --net loopback maps a host-loopback port for DAST
#   --memory / --pids-limit       cgroup-enforced resource caps
#   --cap-drop ALL --security-opt no-new-privileges   no caps to escalate
#   image default user is non-root (uid 1000, owns /artifacts) so no root, no uid match
#   --read-only root + tmpfs /scratch             nothing else writable
#   --rm + disposable volume      no state carried between runs
#
# The container backend is colima/finch/docker; on this host `docker` targets a
# Lima VM (context "colima"), so `docker run` is VM-isolated. Findings are copied
# out with `docker cp`, sidestepping colima's $HOME-only bind-mount scope.
#
#   run-contained.sh --target <dir> --artifacts <dir> --image <img>
#                    [--net none|loopback] [--mem 2g] [--pids 512] [--cpus 2]
#                    [--timeout 300] -- <command to run inside>

# --assert-tools <image> <tool[,tool...]>: prove each tool runs INSIDE the image
# before any campaign trusts a clean fuzz result. Containerization guarantees a
# tool is PRESENT (baked into the image); this guarantees it SURVIVED the build.
# A missing coverage-guided fuzzer here is the silent-clean the campaign must
# refuse, not footnote. Exits 0 only if every tool answers; non-zero names the
# missing ones so the caller refuses the fuzz phase.
if [ "${1:-}" = "--assert-tools" ]; then
  AT_IMAGE="${2:?--assert-tools needs <image> <tool,tool>}"
  AT_TOOLS="${3:?--assert-tools needs <image> <tool,tool>}"
  DK="$(command -v docker || command -v finch)"
  [ -n "$DK" ] || { echo "assert-tools: no container runtime" >&2; exit 3; }
  "$DK" image inspect "$AT_IMAGE" >/dev/null 2>&1 || { echo "assert-tools: image absent: $AT_IMAGE" >&2; exit 3; }
  missing=""
  IFS=','; for t in $AT_TOOLS; do
    # try `<tool> --version` then the cargo-subcommand form `cargo <sub> --version`
    if ! "$DK" run --rm --network none "$AT_IMAGE" sh -c "command -v $t >/dev/null 2>&1 && $t --version >/dev/null 2>&1 || ${t#cargo-} --version >/dev/null 2>&1 || cargo ${t#cargo-} --version >/dev/null 2>&1" 2>/dev/null; then
      missing="$missing $t"
    fi
  done
  unset IFS
  if [ -n "$missing" ]; then
    echo "assert-tools: MISSING in $AT_IMAGE:$missing  (rebuild the image, or refuse the fuzz phase)" >&2
    exit 1
  fi
  echo "assert-tools: all present in $AT_IMAGE:$AT_TOOLS"
  exit 0
fi

TARGET=""; ARTIFACTS=""; IMAGE=""; NET="none"; MEM="2g"; PIDS="512"; CPUS="2"; TMO="300"
CMD=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)    TARGET="$2"; shift 2 ;;
    --artifacts) ARTIFACTS="$2"; shift 2 ;;
    --image)     IMAGE="$2"; shift 2 ;;
    --net)       NET="$2"; shift 2 ;;
    --mem)       MEM="$2"; shift 2 ;;
    --pids)      PIDS="$2"; shift 2 ;;
    --cpus)      CPUS="$2"; shift 2 ;;
    --timeout)   TMO="$2"; shift 2 ;;
    --)          shift; CMD=("$@"); break ;;
    *) printf 'run-contained: unknown arg: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -n "$TARGET" ]    || { echo "run-contained: --target required" >&2; exit 2; }
[ -n "$ARTIFACTS" ] || { echo "run-contained: --artifacts required" >&2; exit 2; }
[ -n "$IMAGE" ]     || { echo "run-contained: --image required (a break-stuff/<surface> image)" >&2; exit 2; }
[ "${#CMD[@]}" -gt 0 ] || { echo "run-contained: a command after -- is required" >&2; exit 2; }
[ -d "$TARGET" ]    || { echo "run-contained: target is not a dir: $TARGET" >&2; exit 2; }
mkdir -p "$ARTIFACTS"
TARGET="$(cd "$TARGET" && pwd)"
ARTIFACTS="$(cd "$ARTIFACTS" && pwd)"

DK=""
if command -v docker >/dev/null 2>&1; then DK="docker"
elif command -v finch >/dev/null 2>&1; then DK="finch"
else echo "run-contained: no container runtime (docker/finch) on PATH" >&2; exit 3; fi
CTX="$($DK context show 2>/dev/null || echo default)"

# Refuse rather than false-clean when the image is absent: a missing image means
# a campaign that would run against nothing.
$DK image inspect "$IMAGE" >/dev/null 2>&1 || {
  echo "run-contained: image not found: $IMAGE  (build it from references/containers/)" >&2; exit 3; }

case "$NET" in
  none)     NETFLAG=(--network none) ;;
  loopback) NETFLAG=(--network bridge -p 127.0.0.1::0) ;;
  *) echo "run-contained: --net must be none|loopback" >&2; exit 2 ;;
esac

# The target reaches the VM via a $HOME-scoped path (colima mounts $HOME, not /tmp).
# If the target is outside $HOME, copy it into a $HOME staging dir first.
case "$TARGET" in
  "$HOME"/*) MOUNT_SRC="$TARGET" ;;
  *) STAGE="$HOME/.break-stuff/stage-$$"; mkdir -p "$STAGE"; cp -R "$TARGET/." "$STAGE/"; MOUNT_SRC="$STAGE" ;;
esac

VOL="bs-art-$$-$(date +%s 2>/dev/null || echo r)"
$DK volume create "$VOL" >/dev/null
cleanup() { $DK volume rm "$VOL" >/dev/null 2>&1 || true; [ -n "${STAGE:-}" ] && rm -rf "$STAGE"; }
trap cleanup EXIT

printf 'run-contained: runtime=%s[%s] image=%s net=%s mem=%s pids=%s\n' \
  "$DK" "$CTX" "$IMAGE" "$NET" "$MEM" "$PIDS" >&2

set +e
timeout "$TMO" "$DK" run --rm \
  "${NETFLAG[@]}" \
  --memory "$MEM" --memory-swap "$MEM" --pids-limit "$PIDS" --cpus "$CPUS" \
  --read-only --tmpfs /scratch:size=512m \
  --cap-drop ALL --security-opt no-new-privileges \
  -v "$MOUNT_SRC:/target:ro" \
  -v "$VOL:/artifacts" \
  "$IMAGE" \
  "${CMD[@]}"
RC=$?
set -e

# Copy findings out of the disposable volume, then the trap removes it.
cid="$($DK create -v "$VOL:/artifacts" "$IMAGE" true 2>/dev/null)"
if [ -n "$cid" ]; then
  $DK cp "$cid:/artifacts/." "$ARTIFACTS/" 2>/dev/null || true
  $DK rm "$cid" >/dev/null 2>&1 || true
fi
exit "$RC"
