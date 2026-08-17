#!/usr/bin/env bash
set -eux

# rust.sh -- the rust language fragment for the sabot base image.
#
# Installs the TOOLCHAIN ITSELF, not just linters: the target's build/test and the
# dev-dep bake (build-ext-image.sh) need a compiler, and cargo-fuzz's libFuzzer needs
# a nightly toolchain with -Zsanitizer. rustup installs a pinned stable plus a pinned
# nightly; clippy ships inside the toolchain. cargo-fuzz, cargo-audit, and cargo-geiger are the
# rust code/robustness tools on top (cargo-geiger counts unsafe usage across the
# dependency tree, a supply-chain signal for the #2 threat).
#
# OFFLINE DATA baked here so a `--network none` campaign is honest (isolation.md,
# Provisioning): the RUSTSEC advisory-db `cargo audit` reads, and the cargo-fuzz
# runtime crates (libfuzzer-sys, arbitrary) a generated `fuzz/` target links. Without
# these baked, `cargo audit` loads 0 advisories and a fuzz build fails to resolve its
# runtime deps under --network none -- a silent false-clean.
#
# g++ is installed alongside gcc because cargo-fuzz links its libFuzzer target with a
# C++ toolchain (cc-rs invokes `c++`); gcc alone fails "failed to find tool c++".
#
# Runs as root at build time (Dockerfile.rust invokes it); rustup lands under
# /usr/local (RUSTUP_HOME/CARGO_HOME) so the non-root breaker user can run every tool.
#
# Every version is pinned and annotated with a '# renovate:' line so
# containers/renovate.json tracks it. The nightly is DATE-pinned: renovate's semver
# versioning cannot bump a date channel, so it carries no renovate comment and is
# advanced by hand when a toolchain feature requires it. The advisory-db is a rolling
# git repo with no release tags; it is pinned by commit SHA (ADVISORY_DB_SHA) and
# advanced by hand, since renovate's semver datasource cannot track a bare SHA.

# renovate: datasource=github-releases depName=rust-lang/rust
RUST_STABLE=1.97.1
RUST_NIGHTLY=nightly-2026-07-29
# renovate: datasource=crate depName=cargo-fuzz
CARGO_FUZZ_VERSION=0.13.2
# cargo-audit 0.22+ is required to parse the advisory-db's CVSS v4.0 vectors; 0.21.2
# aborts "unsupported CVSS version: 4.0" loading the current db.
# renovate: datasource=crate depName=cargo-audit
CARGO_AUDIT_VERSION=0.22.2
# renovate: datasource=crate depName=cargo-geiger
CARGO_GEIGER_VERSION=0.13.0
# cargo-fuzz 0.13.2 generates a fuzz/ target depending on these; baked so a generated
# target links offline. Kept in lockstep with what `cargo fuzz init` writes.
# renovate: datasource=crate depName=libfuzzer-sys
LIBFUZZER_SYS_VERSION=0.4.13
# renovate: datasource=crate depName=arbitrary
ARBITRARY_VERSION=1.4.2
# RUSTSEC advisory-db, a tag-less rolling repo; pinned by commit SHA and advanced by
# hand (renovate's semver datasource cannot track a bare SHA).
ADVISORY_DB_SHA=69f93e1d081d8b6fbee010e48f0b5e0d13661415

export RUSTUP_HOME=/usr/local/rustup
export CARGO_HOME=/usr/local/cargo
export PATH=/usr/local/cargo/bin:$PATH

apt-get update -q
apt-get install -y --no-install-recommends gcc g++ libc6-dev pkg-config libssl-dev
rm -rf /var/lib/apt/lists/*

# rustup detects the host arch itself, so the download is arch-correct with no map.
curl -fsSL https://sh.rustup.rs |
	sh -s -- -y --no-modify-path --profile minimal \
		--default-toolchain "$RUST_STABLE" --component clippy
rustup toolchain install "$RUST_NIGHTLY" --profile minimal
rustup component add --toolchain "$RUST_NIGHTLY" rust-src

# A `nightly` channel alias -> the dated toolchain, so `cargo +nightly` (what the
# fuzzing recipe invokes) resolves WITHOUT rustup trying to sync `nightly` over the
# network, which fails under --network none.
ln -sfn "$RUSTUP_HOME/toolchains/${RUST_NIGHTLY}-"* \
	"$RUSTUP_HOME/toolchains/nightly-$(rustc -vV | sed -n 's/^host: //p')"

cargo install cargo-fuzz --locked --version "$CARGO_FUZZ_VERSION"
cargo install cargo-audit --locked --version "$CARGO_AUDIT_VERSION"
cargo install cargo-geiger --locked --version "$CARGO_GEIGER_VERSION"

# Bake the RUSTSEC advisory-db `cargo audit --no-fetch --db` reads offline. --depth 1
# on the pinned SHA, then drop .git to shed history weight. The campaign points
# --db here; without it `cargo audit` loads 0 advisories and reports a clean it did
# not earn.
git clone https://github.com/rustsec/advisory-db /usr/local/advisory-db
git -C /usr/local/advisory-db checkout -q "$ADVISORY_DB_SHA"
rm -rf /usr/local/advisory-db/.git

# Bake the cargo-fuzz runtime crates into the /deps/cargo registry so a generated
# fuzz/ target links under --network none. This is the SAME /deps prefix
# build-ext-image.sh fetches a target's dev-deps into and run-contained.sh symlinks
# into the run-time CARGO_HOME, so the fuzz runtime and a target's dev-deps share one
# registry. Owned by the breaker uid so a later ext-image fetch (run as uid 1000) can
# add to it. cargo fetch on a throwaway manifest naming the exact pins populates the
# registry cache+index; the audited source never enters.
mkdir -p /deps
FUZZDEPS="$(mktemp -d)"
cat > "$FUZZDEPS/Cargo.toml" <<EOF
[package]
name = "fuzzdeps"
version = "0.0.0"
edition = "2021"
[dependencies]
libfuzzer-sys = "=$LIBFUZZER_SYS_VERSION"
arbitrary = "=$ARBITRARY_VERSION"
EOF
mkdir -p "$FUZZDEPS/src"
: > "$FUZZDEPS/src/lib.rs"
(cd "$FUZZDEPS" && CARGO_HOME=/deps/cargo cargo fetch)
rm -rf "$FUZZDEPS"
chown -R 1000:1000 /deps

# World-readable so the non-root user reads the toolchain, registry cache, and db.
chmod -R a+rX /usr/local/rustup /usr/local/cargo /usr/local/advisory-db /deps

rustc --version
cargo +nightly --version
cargo-fuzz --version
cargo-audit --version
cargo-geiger --version
test -f /usr/local/advisory-db/crates/time/RUSTSEC-2020-0071.md \
	&& echo "advisory-db baked (pinned $ADVISORY_DB_SHA)"
