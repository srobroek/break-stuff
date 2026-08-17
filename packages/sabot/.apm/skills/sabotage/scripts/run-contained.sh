#!/usr/bin/env bash
set -euo pipefail

# run-contained.sh
#
# The ONE sanctioned way a sabot campaign executes untrusted-shaped work: a
# hostile harness, a build script, a dev server. It runs the command inside a
# locked-down, disposable container and copies back only what the container wrote
# to a named artifacts volume. The agent stays on the host; nothing of the agent
# enters the container.
#
# Isolation, all enforced as flags the kernel honours, proven on this host:
#   -v <target>:/target:ro       target READ-ONLY   (a write to the target is impossible)
#   named volume at /artifacts    the only writable path; copied out after, then removed
#   --network none (both modes)   no outbound egress; DAST uses the container's own lo
#   --memory / --pids-limit       cgroup-enforced resource caps
#   --cap-drop ALL --security-opt no-new-privileges   no caps to escalate
#   image default user is non-root (uid 1000, owns /artifacts) so no root, no uid match
#   --read-only root + tmpfs /scratch             nothing else writable
#   workdir=/scratch, CARGO_TARGET_DIR/GOCACHE/TMPDIR/HOME -> /scratch  builds write here, not the ro target
#     (the command after -- reads the target at /target: `cargo test --manifest-path /target/Cargo.toml`)
#   --rm + disposable volume      no state carried between runs
#
# The container backend is colima/finch/docker; on this host `docker` targets a
# Lima VM (context "colima"), so `docker run` is VM-isolated. Findings are copied
# out with `docker cp`, sidestepping colima's $HOME-only bind-mount scope.
#
#   run-contained.sh --target <dir> --artifacts <dir> --image <img>
#                    [--net none|loopback] [--mem 2g] [--pids 512] [--cpus 2]
#                    [--timeout 300] [--workdir /target|/scratch] -- <command inside>
#
# cwd defaults to /target (the repo), because a repo-aware scanner (gitleaks,
# osv-scanner, actionlint, trivy) auto-detects .git and .github/workflows from cwd:
# run one from /scratch and it fails "not a git repository" / "no project found"
# (rc 128/3), which is an INVALID run masquerading as zero findings, not a clean
# result. A build or fuzz step that must WRITE to cwd passes --workdir /scratch and
# reads the target by absolute path (`--manifest-path /target/Cargo.toml`), since
# /target is read-only. Writes are already redirected to /scratch via the env below.

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
    # A tool name interpolates into the in-container `sh -c`, so reject anything
    # outside the safe set for an executable name. Without this a crafted name
    # (`x;id`) would execute in the container.
    case "$t" in
      *[!A-Za-z0-9._-]*|"") echo "assert-tools: illegal tool name: '$t'" >&2; exit 2 ;;
    esac
    # try `<tool> --version`, the cargo-subcommand form `cargo <sub> --version`, then
    # the bare `<tool> version` subcommand. The last form is not decoration: `go
    # --version` exits 2 ("flag provided but not defined"), so without it the go
    # surface's toolchain -- which IS its fuzzer, since `go test -fuzz` is built in --
    # reports as missing and the preflight refuses a working image.
    if ! "$DK" run --rm --network none "$AT_IMAGE" sh -c "command -v $t >/dev/null 2>&1 && { $t --version >/dev/null 2>&1 || $t version >/dev/null 2>&1; } || ${t#cargo-} --version >/dev/null 2>&1 || cargo ${t#cargo-} --version >/dev/null 2>&1" 2>/dev/null; then
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
WORKDIR="/target"
SCRATCH="2g"      # tmpfs size; a real cargo/npm build needs GBs, not the old 512m
COPY_SRC=0        # --copy-src: tar the target into /scratch/src (minus target/ + .git)
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
    --workdir)   WORKDIR="$2"; shift 2 ;;
    --scratch)   SCRATCH="$2"; shift 2 ;;
    --copy-src)  COPY_SRC=1; shift ;;
    --)          shift; CMD=("$@"); break ;;
    *) printf 'run-contained: unknown arg: %s\n' "$1" >&2; exit 2 ;;
  esac
done

case "$WORKDIR" in
  /target|/scratch) : ;;
  *) echo "run-contained: --workdir must be /target or /scratch" >&2; exit 2 ;;
esac

[ -n "$TARGET" ]    || { echo "run-contained: --target required" >&2; exit 2; }
[ -n "$ARTIFACTS" ] || { echo "run-contained: --artifacts required" >&2; exit 2; }
[ -n "$IMAGE" ]     || { echo "run-contained: --image required (a sabot/<surface> image)" >&2; exit 2; }
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

# Both modes deny outbound egress. A DAST run starts its dev server and scans it
# INSIDE the command after `--`, over the container's own loopback interface, which
# `--network none` already provides (`lo` is always up). `--net loopback` is kept as
# an explicit name for that intent; it does NOT add a bridge, because a bridge grants
# full outbound internet and the in-container loopback needs none. There is no
# host-side port map: `docker run` blocks to completion, so a host port could never
# be read back mid-run anyway, and mapping one would only open an egress path.
case "$NET" in
  none|loopback) NETFLAG=(--network none) ;;
  *) echo "run-contained: --net must be none|loopback" >&2; exit 2 ;;
esac

# The target reaches the VM via a $HOME-scoped path (colima mounts $HOME, not /tmp).
# If the target is outside $HOME, copy it into a $HOME staging dir first.
case "$TARGET" in
  "$HOME"/*) MOUNT_SRC="$TARGET" ;;
  *) STAGE="$HOME/.sabot/stage-$$"; mkdir -p "$STAGE"; cp -R "$TARGET/." "$STAGE/"; MOUNT_SRC="$STAGE" ;;
esac

VOL="bs-art-$$-$(date +%s 2>/dev/null || echo r)"
$DK volume create "$VOL" >/dev/null
cleanup() { $DK volume rm "$VOL" >/dev/null 2>&1 || true; [ -n "${STAGE:-}" ] && rm -rf "$STAGE"; }
trap cleanup EXIT

printf 'run-contained: runtime=%s[%s] image=%s net=%s mem=%s pids=%s\n' \
  "$DK" "$CTX" "$IMAGE" "$NET" "$MEM" "$PIDS" >&2

# CARGO_HOME is a writable tmpfs path (/scratch/cargo), but the target's baked
# dev-deps live in the ext-image's read-only /deps/cargo/registry. Seed the writable
# home with a symlink to that registry so `cargo ... --offline` resolves the baked
# crates without a network fetch and without writing the read-only layer. No-op when
# the image has no baked registry (a base image, or a non-Rust surface). The command
# after the preamble runs via `exec "$@"` so its exit code is preserved.
PREAMBLE='mkdir -p "$CARGO_HOME" /scratch/tmp; [ -d /deps/cargo/registry ] && [ ! -e "$CARGO_HOME/registry" ] && ln -s /deps/cargo/registry "$CARGO_HOME/registry";'
# --copy-src: a build/fuzz step needs a WRITABLE source tree (cargo writes Cargo.lock
# and target/ beside the manifest), but /target is read-only. Copy the target into
# /scratch/src, excluding its own build dir and .git (the space hogs that overflow
# the tmpfs), and cd there. The audited bytes never change; this is a working copy on
# a disposable tmpfs. The command then runs from /scratch/src.
if [ "$COPY_SRC" -eq 1 ]; then
  PREAMBLE="$PREAMBLE"' mkdir -p /scratch/src; tar -C /target --exclude=./target --exclude=./.git -cf - . | tar -C /scratch/src -xf -; cd /scratch/src;'
  WORKDIR="/scratch"
fi

set +e
# Two cwd regimes, selected by --workdir:
#   /target (default): a repo-aware scanner (gitleaks, osv-scanner, actionlint,
#     trivy) auto-detects .git and .github/workflows relative to cwd, so it MUST
#     run from the repo root. /target is read-only, but these scanners only read;
#     any temp write lands in /scratch via HOME/TMPDIR/XDG_CACHE_HOME below.
#   /scratch: a build or fuzz step that writes to cwd (`cargo test`, `go test`, npm)
#     runs here (a tmpfs) and reads the target by absolute path
#     (`--manifest-path /target/Cargo.toml`), never writing the read-only mount.
# CARGO_TARGET_DIR/GOCACHE/etc. point at /scratch regardless, so a build launched
# from /target still writes its output to the writable tmpfs, not the target tree.
#
# TMPDIR is a SUBDIRECTORY of /scratch, never /scratch itself. Go refuses to read a
# go.mod that sits in the temp root ("ignoring go.mod in system temp root"), so with
# TMPDIR=/scratch every contained go command failed "directory prefix . does not
# contain main module" -- while `go vet` still exited 0, which is the false-clean this
# wrapper exists to prevent.
timeout "$TMO" "$DK" run --rm \
  "${NETFLAG[@]}" \
  --memory "$MEM" --memory-swap "$MEM" --pids-limit "$PIDS" --cpus "$CPUS" \
  --read-only --tmpfs "/scratch:size=$SCRATCH,mode=1777,exec" \
  --cap-drop ALL --security-opt no-new-privileges \
  --user 1000:1000 \
  --workdir "$WORKDIR" \
  --env HOME=/scratch \
  --env TMPDIR=/scratch/tmp \
  --env CARGO_HOME=/scratch/cargo \
  --env CARGO_TARGET_DIR=/scratch/target \
  --env CARGO_NET_OFFLINE=true \
  --env GOCACHE=/scratch/go-build \
  --env GOPATH=/scratch/go \
  --env npm_config_cache=/scratch/npm \
  --env RUFF_CACHE_DIR=/scratch/ruff \
  --env XDG_CACHE_HOME=/scratch/cache \
  --env LANG=C.UTF-8 --env LC_ALL=C.UTF-8 \
  -v "$MOUNT_SRC:/target:ro" \
  -v "$VOL:/artifacts" \
  "$IMAGE" \
  sh -c "$PREAMBLE"' exec "$@"' _ "${CMD[@]}"
RC=$?
set -e

# Copy findings out of the disposable volume, then the trap removes it. A copy-out
# failure strands every finding in the volume, so it must not read as a clean run:
# exit 4 (distinct from the campaign's own RC) so a caller keying on the exit code
# treats the run as INVALID rather than trusting an empty artifacts dir.
COPY_OK=1
cid="$($DK create -v "$VOL:/artifacts" "$IMAGE" true 2>/dev/null)"
if [ -z "$cid" ]; then
  echo "run-contained: ERROR could not open the artifacts volume to copy findings out; output is stranded in $VOL (treat this run as INVALID)" >&2
  COPY_OK=0
else
  if ! $DK cp "$cid:/artifacts/." "$ARTIFACTS/" 2>/dev/null; then
    echo "run-contained: ERROR findings copy-out failed; output may be stranded in $VOL (treat this run as INVALID, not clean)" >&2
    COPY_OK=0
  fi
  $DK rm "$cid" >/dev/null 2>&1 || true
fi
[ "$COPY_OK" -eq 1 ] || exit 4
exit "$RC"
