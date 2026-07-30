#!/usr/bin/env bash
set -euo pipefail

# build-ext-image.sh
#
# Extend a surface image with the TARGET's own dev-dependencies, baked at build
# time so a `--network none` campaign can use them (isolation.md, Provisioning). A
# `cargo test` harness that pulls `proptest` cannot fetch it under the run-time
# network-none contract, so the dep must already be in the image.
#
#   build-ext-image.sh --target <dir> --base <img> --tag <out> [--dry-run]
#     --target   the repo under test (read-only; only its manifests+locks are read)
#     --base     the surface image to extend, e.g. sabot/rust:1
#     --tag      the output image tag, e.g. sabot/rust-ext:1
#     --dry-run  print the generated Dockerfile and exit; build nothing
#
# What it does NOT do: it NEVER copies the target source into the image. The build
# context is a temp dir holding ONLY the discovered manifests and lockfiles, so no
# audited code enters a persisted layer and the read-only-target guarantee holds
# (isolation.md, "Never COPY the target source into the image"). The target is
# mounted read-only at /target at run time by run-contained.sh; this image carries
# only the fetched deps.
#
# The dep caches are baked into a persistent /deps prefix (CARGO_HOME et al), NOT
# under /scratch: run-contained.sh mounts /scratch as a fresh tmpfs per run, which
# would mask anything baked there. run-contained does not override CARGO_HOME, so a
# cargo bake is resolvable offline; the other cache vars it does override at run
# time are set here for the build-time fetch (see the report/caveat in isolation.md).

TARGET=""; BASE=""; TAG=""; DRYRUN=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)  TARGET="$2"; shift 2 ;;
    --base)    BASE="$2"; shift 2 ;;
    --tag)     TAG="$2"; shift 2 ;;
    --dry-run) DRYRUN=1; shift ;;
    *) printf 'build-ext-image: unknown arg: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -n "$TARGET" ] || { echo "build-ext-image: --target required" >&2; exit 2; }
[ -n "$BASE" ]   || { echo "build-ext-image: --base required (a sabot/<surface> image)" >&2; exit 2; }
[ -n "$TAG" ]    || { echo "build-ext-image: --tag required (the output image, e.g. sabot/rust-ext:1)" >&2; exit 2; }
[ -d "$TARGET" ] || { echo "build-ext-image: target is not a dir: $TARGET" >&2; exit 2; }
TARGET="$(cd "$TARGET" && pwd)"

HERE="$(cd "$(dirname "$0")" && pwd)"
DETECT="$HERE/detect-stacks.py"
[ -f "$DETECT" ] || { echo "build-ext-image: detect-stacks.py not next to this script" >&2; exit 3; }

# Discover the manifests/locks/fetch per bake unit deterministically. The default
# JSON output carries the manifest+lock paths (needed for the COPY set) and the fetch
# command in one call, so there is no second re-derivation of the same map.
DETECT_JSON="$(python3 "$DETECT" --repo "$TARGET")" || {
  echo "build-ext-image: detect-stacks.py failed on $TARGET" >&2; exit 3; }

# Build the Dockerfile and the minimal context (manifests+locks only) from the map,
# with python emitting BOTH so the COPY list and the temp-context file list agree.
CTX="$(mktemp -d "${TMPDIR:-/tmp}/bs-ext-XXXXXX")"
cleanup() { rm -rf "$CTX"; }
trap cleanup EXIT

DOCKERFILE="$(
  BASE="$BASE" TARGET="$TARGET" CTX="$CTX" python3 - "$DETECT_JSON" <<'PY'
import json, os, shutil, sys

result = json.loads(sys.argv[1])
base = os.environ["BASE"]
target = os.environ["TARGET"]
ctx = os.environ["CTX"]

lines = [
    f"FROM {base}",
    # Persistent dep prefix, outside the run-time tmpfs at /scratch. Owned by the
    # non-root breaker uid so the fetch (and a run-time read) needs no root.
    "USER root",
    "RUN mkdir -p /deps && chown 1000:1000 /deps",
    "USER 1000:1000",
    "ENV CARGO_HOME=/deps/cargo \\",
    "    GOMODCACHE=/deps/go/pkg/mod \\",
    "    npm_config_cache=/deps/npm \\",
    "    PIP_CACHE_DIR=/deps/pip \\",
    "    UV_CACHE_DIR=/deps/uv",
]

# One COPY + one RUN per bake unit, ordered so the dep layer caches on the
# manifest+lock: only a lock change re-fetches. Copy ONLY manifest+lock, never the
# source, so no audited code enters a layer.
for u in result["bake_units"]:
    d = u["dir"]
    dest = "./" if d == "." else f"{d}/"
    copy_rel = [u["manifest"]] + [
        (m if d == "." else f"{d}/{m}") for m in u["lockfiles"]
    ]
    for rel in copy_rel:
        src = os.path.join(target, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(ctx, rel)
        os.makedirs(os.path.dirname(dst) or ctx, exist_ok=True)
        shutil.copy2(src, dst)
    present = [rel for rel in copy_rel if os.path.exists(os.path.join(ctx, rel))]
    if not present:
        continue
    lines.append(f"COPY {' '.join(present)} {dest}")
    cd = "" if d == "." else f'cd "{d}" && '
    lines.append(f"RUN {cd}{u['fetch']}")

sys.stdout.write("\n".join(lines) + "\n")
PY
)"

printf '%s' "$DOCKERFILE" > "$CTX/Dockerfile"

if [ "$DRYRUN" -eq 1 ]; then
  printf '%s' "$DOCKERFILE"
  exit 0
fi

DK=""
if command -v docker >/dev/null 2>&1; then DK="docker"
elif command -v finch >/dev/null 2>&1; then DK="finch"
else echo "build-ext-image: no container runtime (docker/finch) on PATH" >&2; exit 3; fi

$DK image inspect "$BASE" >/dev/null 2>&1 || {
  echo "build-ext-image: base image not found: $BASE (build it from references/containers/)" >&2; exit 3; }

# Network is ON at build (the default): the toolchain's own resolver fetches exactly
# what the manifest names, while no target code runs. Re-tagging is idempotent; the
# layer cache keyed on the copied lock skips an unchanged re-fetch.
printf 'build-ext-image: runtime=%s base=%s tag=%s units=%s\n' \
  "$DK" "$BASE" "$TAG" "$(printf '%s' "$DETECT_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["bake_units"]))')" >&2
exec "$DK" build -f "$CTX/Dockerfile" -t "$TAG" "$CTX"
