#!/usr/bin/env bash
set -euo pipefail

# build-ext-image.sh
#
# Extend a surface image with the TARGET's own dev-dependencies, baked at build
# time so a `--network none` campaign can use them (isolation.md, Provisioning). A
# `cargo test` harness that pulls `proptest` cannot fetch it under the run-time
# network-none contract, so the dep must already be in the image.
#
#   build-ext-image.sh --target <dir> --base <img> --tag <out> [--stacks a,b] [--dry-run]
#     --target   the repo under test (read-only; only its manifests+locks are read)
#     --base     the surface image to extend, e.g. sabot/rust:1
#     --tag      the output image tag, e.g. sabot/rust-ext:1
#     --stacks   comma-separated stacks to bake (default: all detected). A surface
#                image carries ONE toolchain, so baking every stack of a
#                multi-language target into it fails: `cargo fetch` has no cargo in
#                sabot/node:1, `pnpm install` has no pnpm in sabot/rust:1.
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

usage() { sed -n '4,28p' "$0" | sed 's/^# \{0,1\}//'; }

TARGET=""; BASE=""; TAG=""; DRYRUN=0; STACKS=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --target)  TARGET="$2"; shift 2 ;;
    --base)    BASE="$2"; shift 2 ;;
    --tag)     TAG="$2"; shift 2 ;;
    --stacks)  STACKS="$2"; shift 2 ;;
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
  BASE="$BASE" TARGET="$TARGET" CTX="$CTX" STACKS="$STACKS" python3 - "$DETECT_JSON" <<'PY'
import json, os, shutil, sys

result = json.loads(sys.argv[1])
base = os.environ["BASE"]
target = os.environ["TARGET"]
ctx = os.environ["CTX"]

want = {s for s in os.environ.get("STACKS", "").split(",") if s}
if want:
    result["bake_units"] = [u for u in result["bake_units"] if u["stack"] in want]

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
# Node deps land in a PERSISTENT prefix, not the workdir. `pnpm install` writes a
# node_modules tree next to the manifest, and run-contained.sh mounts /scratch as a
# fresh tmpfs, so a tree baked at the default WORKDIR (/scratch) is masked at run time
# and the offline harness finds nothing. /deps survives, and the .bin dirs are put on
# PATH plus NODE_PATH below so `vitest` and `require()` resolve with the target
# mounted read-only elsewhere.
NODE_PREFIX = "/deps/node"


def node_context_files(result, unit):
    """Manifest, lockfile, workspace file, and every member manifest under this root.

    `pnpm install --frozen-lockfile` at a workspace root verifies the lockfile against
    ALL members, so copying the root package.json alone fails
    ERR_PNPM_OUTDATED_LOCKFILE. npm and yarn workspaces verify the same way.
    """
    d = unit["dir"]
    files = [unit["manifest"]]
    files += [(m if d == "." else f"{d}/{m}") for m in unit["lockfiles"]]
    if unit.get("workspace_root"):
        for extra in ("pnpm-workspace.yaml", ".npmrc", ".nvmrc"):
            files.append(extra if d == "." else f"{d}/{extra}")
        prefix = "" if d == "." else d.rstrip("/") + "/"
        files += [m["manifest"] for m in result["manifests"]
                  if m["stack"] == "node" and m["manifest"] != unit["manifest"]
                  and m["manifest"].startswith(prefix)]
    return files


node_units = [u for u in result["bake_units"] if u["stack"] == "node"]
for u in node_units:
    d = u["dir"]
    workdir = NODE_PREFIX if d == "." else f"{NODE_PREFIX}/{d}"
    copied = []
    for rel in node_context_files(result, u):
        src = os.path.join(target, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(ctx, rel)
        os.makedirs(os.path.dirname(dst) or ctx, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    if not copied:
        continue
    strip = "" if d == "." else d.rstrip("/") + "/"
    # One COPY per file: a multi-source COPY into a directory flattens to basenames,
    # which collapses every member package.json onto the root one.
    for rel in copied:
        lines.append(f"COPY --chown=1000:1000 {rel} {workdir}/{rel[len(strip):]}")
    # engine-strict off: the image pins one node major, and a target that declares a
    # newer `engines.node` aborts the install outright rather than warning. The bake
    # is a dep fetch, not a compatibility claim.
    lines.append(f'WORKDIR {workdir}')
    lines.append('ENV PNPM_HOME=/deps/pnpm npm_config_engine_strict=false \\')
    lines.append('    npm_config_store_dir=/deps/pnpm-store')
    lines.append(f"RUN {u['fetch']}")

if node_units:
    bins = []
    node_paths = []
    for m in result["manifests"]:
        if m["stack"] != "node":
            continue
        root = NODE_PREFIX if m["dir"] == "." else f"{NODE_PREFIX}/{m['dir']}"
        bins.append(f"{root}/node_modules/.bin")
        node_paths.append(f"{root}/node_modules")
    # Baked bins go LAST: the target's own eslint would otherwise shadow the image's
    # pinned eslint + no-unsanitized config that the web recipe invokes by name.
    lines.append("ENV PATH=$PATH:" + ":".join(bins) + " \\")
    lines.append("    NODE_PATH=" + ":".join(node_paths) + ":/usr/local/lib/node_modules")

def rust_context_files(result, unit):
    """Root manifest+lock plus EVERY member manifest of the workspace.

    `cargo fetch` at a workspace root reads each member's Cargo.toml to resolve the
    graph; with only the root copied it aborts "failed to read <member>/Cargo.toml".
    """
    d = unit["dir"]
    files = [unit["manifest"]] + [(m if d == "." else f"{d}/{m}") for m in unit["lockfiles"]]
    if unit.get("workspace_root"):
        prefix = "" if d == "." else d.rstrip("/") + "/"
        files += [m["manifest"] for m in result["manifests"]
                  if m["stack"] == "rust" and m["manifest"] != unit["manifest"]
                  and m["manifest"].startswith(prefix)]
    return files


for u in result["bake_units"]:
    if u["stack"] == "node":
        continue
    d = u["dir"]
    dest = "./" if d == "." else f"{d}/"
    copy_rel = rust_context_files(result, u) if u["stack"] == "rust" else (
        [u["manifest"]] + [(m if d == "." else f"{d}/{m}") for m in u["lockfiles"]]
    )
    present = []
    for rel in copy_rel:
        src = os.path.join(target, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(ctx, rel)
        os.makedirs(os.path.dirname(dst) or ctx, exist_ok=True)
        shutil.copy2(src, dst)
        present.append(rel)
    if not present:
        continue
    strip = "" if d == "." else d.rstrip("/") + "/"
    base_dir = "." if d == "." else d.rstrip("/")
    # --chown is not cosmetic: COPY writes root-owned files whatever USER is in
    # effect, and a fetch REWRITES the lock it was given -- `cargo fetch` failed
    # "failed to write /scratch/Cargo.lock: Permission denied" as uid 1000, aborting
    # the whole ext build. npm and pip rewrite their locks the same way.
    #
    # One COPY per file, since a multi-source COPY into a directory flattens to
    # basenames and would collapse every member manifest onto the root one.
    for rel in present:
        lines.append(f"COPY --chown=1000:1000 {rel} {dest}{rel[len(strip):]}")
    # Rust: `cargo fetch` parses each manifest, which resolves targets by
    # autodiscovery (src/lib.rs, src/main.rs). With only the manifests copied there
    # are zero targets and cargo aborts ("no targets specified in the manifest").
    # Inject an EMPTY stub lib per manifest dir so every manifest parses and every
    # dependency resolves; the stub is not the audited source (the real tree mounts
    # read-only at /target at run time), so no product code enters a layer. A
    # committed Cargo.lock, when present, is copied above and makes the fetch exact.
    if u["stack"] == "rust":
        for rel in present:
            if os.path.basename(rel) != "Cargo.toml":
                continue
            rel_dir = os.path.dirname(rel)
            stub_dir = os.path.join(ctx, rel_dir, "src")
            os.makedirs(stub_dir, exist_ok=True)
            open(os.path.join(stub_dir, "lib.rs"), "a").close()
            src_rel = os.path.join(rel_dir, "src", "lib.rs") if rel_dir else "src/lib.rs"
            in_unit = src_rel[len(strip):]
            lines.append(f"COPY --chown=1000:1000 {src_rel} {dest}{in_unit}")
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
