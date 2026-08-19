#!/usr/bin/env bash
set -eux

# rust-extras.sh -- the second tier of rust robustness tools, on top of layers/rust.sh.
#
# Split from rust.sh because these are SLOW to build (each is a cargo install from
# source) and because the first tier -- cargo-fuzz, cargo-audit, clippy, cargo-geiger --
# is what a campaign always runs, while these are reached for by finding. Keeping them
# in a separate layer means a pin bump here does not rebuild the toolchain above.
#
# WHAT IS HERE, and what each answers that the first tier does not
#   cargo-deny            license and duplicate-dependency policy, plus advisories.
#                         Reads the SAME baked advisory-db as cargo-audit, pointed at it
#                         by db-path in the generated deny.toml below; without that it
#                         tries to clone the db and fails under --network none.
#   cargo-vet            whether a dependency has been human-audited. Offline it can
#                         only report "no audits imported", which is honest, not a bug.
#   cargo-careful        runs the test suite with extra UB checks the normal profile
#                         skips. Needs the nightly toolchain and rust-src, both from
#                         rust.sh.
#   cargo-semver-checks  API-break detection. Needs a BASELINE to compare against,
#                         which offline means a local git rev, never a crates.io release.
#   Miri                 an interpreter that catches UB the compiler permits. A rustup
#                         COMPONENT, not a crate, so it is added to the pinned nightly.
#   weggli               C/C++ pattern matcher, for a rust target's FFI and build.rs.
#                         Self-contained: patterns come from the campaign, not a DB.
#
# proptest and CASR are deliberately NOT installed here:
#   proptest  is a dev-DEPENDENCY, not a binary. A target that uses it declares it, and
#             build-ext-image.sh bakes the target's dev-deps into /deps. Installing it
#             globally would install nothing usable.
#   CASR      needs the `casr-*` binaries plus gdb to be useful on a rust crash, and its
#             value overlaps what libFuzzer already prints for a rust panic. Recorded as
#             a declined bake in tool-coverage-matrix.md rather than shipped unused.
#
# Runs as root at build time (Dockerfile.rust-extras invokes it), so the installs land
# in the shared /usr/local/cargo that layers/rust.sh set up.
#
# Every version is pinned with a '# renovate:' line so containers/renovate.json tracks
# it. The nightly is inherited from rust.sh, not re-pinned here.

# renovate: datasource=crate depName=cargo-deny
CARGO_DENY_VERSION=0.20.2
# renovate: datasource=crate depName=cargo-vet
CARGO_VET_VERSION=0.10.2
# renovate: datasource=crate depName=cargo-careful
CARGO_CAREFUL_VERSION=0.4.10
# renovate: datasource=crate depName=cargo-semver-checks
CARGO_SEMVER_CHECKS_VERSION=0.50.0
# renovate: datasource=crate depName=weggli
WEGGLI_VERSION=0.2.4

export RUSTUP_HOME=/usr/local/rustup
export CARGO_HOME=/usr/local/cargo
export PATH=/usr/local/cargo/bin:$PATH

# cargo-semver-checks links libz and libgit2 via its trustfall/gix stack; cmake is
# needed by the libgit2 build script. Without them the install fails deep in a build
# script with a linker error rather than a missing-package message.
apt-get update -q
apt-get install -y --no-install-recommends cmake zlib1g-dev
rm -rf /var/lib/apt/lists/*

cargo install cargo-deny --locked --version "$CARGO_DENY_VERSION"
cargo install cargo-vet --locked --version "$CARGO_VET_VERSION"
cargo install cargo-careful --locked --version "$CARGO_CAREFUL_VERSION"
cargo install cargo-semver-checks --locked --version "$CARGO_SEMVER_CHECKS_VERSION"
cargo install weggli --locked --version "$WEGGLI_VERSION"

# Miri is a rustup COMPONENT of the nightly, not a crate. rust.sh installed the dated
# nightly and aliased `nightly` to it, so this adds miri to that same toolchain and
# `cargo +nightly miri` resolves offline.
NIGHTLY="$(rustup toolchain list | sed -n 's/^\(nightly-[0-9-]*\)-.*/\1/p' | head -1)"
[ -n "$NIGHTLY" ] || {
	echo "rust-extras: no dated nightly found; layers/rust.sh must run first" >&2
	exit 1
}
rustup component add --toolchain "$NIGHTLY" miri

# A default deny.toml pointing cargo-deny at the BAKED advisory-db. Without db-path and
# db-urls, `cargo deny check advisories` clones the db from github and dies under
# --network none -- or worse, on a partial clone, loads zero advisories and reports a
# clean. The campaign passes `--config /opt/sabot-db/deny.toml` unless the target ships
# its own.
mkdir -p /opt/sabot-db
cat >/opt/sabot-db/deny.toml <<'EOF'
# sabot default cargo-deny config. Points at the advisory-db baked into the image so
# `cargo deny check advisories` works under --network none. A target's own deny.toml
# takes precedence; this is the fallback, not an override.
#
# db-path is /scratch/advisory-db, NOT the baked /usr/local/advisory-db, and that is
# deliberate. cargo-deny takes an EXCLUSIVE lock on db.lock inside db-path before
# reading, and against the read-only image that fails outright:
#
#   failed to obtain lock file '/usr/local/advisory-db/db.lock': attempted to take an
#   exclusive lock on a read-only path
#
# `--offline` does NOT skip that lock (measured), so the path must be writable whatever
# the flags. run-contained.sh copies the baked db (6MB) to this path.
#
# db-path is also a PARENT, not the db: cargo-deny expects one child per db-url, named
# advisory-db-<hash-of-url>. The wrapper creates that child. Point db-path at a flat copy
# of the db and cargo-deny tries to clone the child it cannot find, which under
# --network none fails on DNS rather than on anything about the db.
#
# The campaign must ALSO pass `--offline` BEFORE the subcommand (`cargo deny --offline
# check advisories`). It is a top-level flag; after `check` it is rejected as unknown.
# Without it cargo-deny attempts a fetch even with a valid local db.
[advisories]
db-path = "/scratch/advisory-db"
db-urls = ["https://github.com/rustsec/advisory-db"]
EOF

# Prove each tool RUNS. cargo-deny gets more than --version: it is the one tool here
# whose failure mode is loading ZERO advisories and reporting a clean, so assert it
# actually reads the baked db by checking a known-vulnerable lockfile and requiring the
# RUSTSEC id in the output.
cargo deny --version
cargo vet --version
cargo semver-checks --version
weggli --version
cargo +nightly miri --version

# cargo-careful has NO --version: it forwards every argument to cargo, so
# `cargo careful --version` exits 1 listing its subcommands. `setup` is the right
# assertion anyway, because it is also a BAKE step -- it compiles a sysroot from
# rust-src with the extra checks enabled. At campaign time the image is read-only and
# the network is off, so a sysroot that was not built here cannot be built then, and
# `cargo careful test` fails on a network fetch that has nothing to do with the finding
# under investigation.
#
# It writes to $XDG_CACHE_HOME/cargo-careful, defaulting to ~/.cache. Left at the
# default the sysroot landed in /root/.cache and was unreadable by the uid 1000 the
# campaign runs as (measured: `find / -iname "*careful*"` as breaker returned only the
# binary). Baked under /deps instead, the prefix run-contained.sh symlinks into the
# writable HOME it gives the container.
export XDG_CACHE_HOME=/deps/cache
mkdir -p "$XDG_CACHE_HOME"
cargo +nightly careful setup
test -d "$XDG_CACHE_HOME/cargo-careful" || {
	echo "rust-extras: cargo careful setup wrote no sysroot to $XDG_CACHE_HOME" >&2
	exit 1
}

# Miri needs the SAME treatment for the same reason, and `miri --version` hides it: the
# component answers while the sysroot it needs does not exist. Measured, a run-time
# `cargo +nightly miri test --offline` died building one:
#
#   failed to build sysroot: error: no matching package named `hashbrown` found
#
# The sysroot compiles the nightly's own std from rust-src and pulls std's registry
# deps, so it needs crates.io -- available here, never at campaign time.
cargo +nightly miri setup
test -d "$XDG_CACHE_HOME/miri" || {
	echo "rust-extras: cargo miri setup wrote no sysroot to $XDG_CACHE_HOME" >&2
	exit 1
}

probe=/opt/sabot-rust-probe
mkdir -p "$probe/src"
cat >"$probe/Cargo.toml" <<'EOF'
[package]
name = "probe"
version = "0.0.0"
edition = "2021"
[dependencies]
time = "=0.1.44"
EOF
: >"$probe/src/lib.rs"
cat >"$probe/Cargo.lock" <<'EOF'
version = 3

[[package]]
name = "probe"
version = "0.0.0"
dependencies = ["time"]

[[package]]
name = "time"
version = "0.1.44"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "6db9e6914ab8b1ae1c260a4ae7a49b6c5611b40328a735b21862567685e73255"
EOF
# The probe gets its OWN config rather than /opt/sabot-db/deny.toml, whose db-path points
# at the run-time tmpfs copy that does not exist yet at build time. It mirrors the exact
# shape the wrapper builds: a WRITABLE parent holding the db under cargo-deny's own
# advisory-db-<hash> child name.
#
# --offline is what makes this probe mean anything. `docker build` HAS network, so without
# it cargo-deny silently clones the db from github and passes no matter what was baked --
# which is how a broken bake shipped once already. With it, a fetch is refused, so
# finding RUSTSEC-2020-0071 can only come from the baked bytes.
mkdir -p "$probe/db"
cp -r /usr/local/advisory-db "$probe/db/advisory-db-3157b0e258782691"
cat >"$probe/deny.toml" <<EOF
[advisories]
db-path = "$probe/db"
db-urls = ["https://github.com/rustsec/advisory-db"]
EOF
(
	cd "$probe"
	# Resolve the crate graph FIRST, with the build's network. `--offline` gates crate
	# downloads as well as the db, and `time 0.1.44` pulls winapi and wasi, which the
	# baked registry does not carry: without this the probe fails "failed to download
	# winapi" and says nothing about the advisory-db it exists to test.
	#
	# Not `--locked`: the lockfile above is hand-written to pin `time` at the version
	# carrying RUSTSEC-2020-0071 and names none of its transitive deps, so cargo would
	# reject it as out of date. The pin that matters is the `=0.1.44` in Cargo.toml.
	cargo fetch
	cargo deny --offline --config "$probe/deny.toml" check advisories 2>&1 |
		tee "$probe/out.txt" || true
	grep -q RUSTSEC-2020-0071 "$probe/out.txt"
	echo "cargo-deny reads the baked advisory-db offline (RUSTSEC-2020-0071, no network)"
)
rm -rf "$probe"

# LAST, not earlier: `cargo careful setup` above writes a sysroot into rustup, and the
# probe build wrote to the cargo registry. A chmod before them leaves the new files
# root-only, and the campaign runs as uid 1000 against a read-only image where nothing
# can be fixed at run time.
chmod -R a+rX /usr/local/cargo /usr/local/rustup /deps/cache /opt/sabot-db/deny.toml
