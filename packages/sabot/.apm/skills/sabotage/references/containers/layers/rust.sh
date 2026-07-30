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
# Runs as root at build time (Dockerfile.rust invokes it); rustup lands under
# /usr/local (RUSTUP_HOME/CARGO_HOME) so the non-root breaker user can run every tool.
#
# Every version is pinned and annotated with a '# renovate:' line so
# containers/renovate.json tracks it. The nightly is DATE-pinned: renovate's semver
# versioning cannot bump a date channel, so it carries no renovate comment and is
# advanced by hand when a toolchain feature requires it.

# renovate: datasource=github-releases depName=rust-lang/rust
RUST_STABLE=1.97.1
RUST_NIGHTLY=nightly-2026-07-29
# renovate: datasource=crate depName=cargo-fuzz
CARGO_FUZZ_VERSION=0.13.2
# renovate: datasource=crate depName=cargo-audit
CARGO_AUDIT_VERSION=0.21.2
# renovate: datasource=crate depName=cargo-geiger
CARGO_GEIGER_VERSION=0.13.0

export RUSTUP_HOME=/usr/local/rustup
export CARGO_HOME=/usr/local/cargo
export PATH=/usr/local/cargo/bin:$PATH

apt-get update -q
apt-get install -y --no-install-recommends gcc libc6-dev pkg-config libssl-dev
rm -rf /var/lib/apt/lists/*

# rustup detects the host arch itself, so the download is arch-correct with no map.
curl -fsSL https://sh.rustup.rs |
	sh -s -- -y --no-modify-path --profile minimal \
		--default-toolchain "$RUST_STABLE" --component clippy
rustup toolchain install "$RUST_NIGHTLY" --profile minimal
rustup component add --toolchain "$RUST_NIGHTLY" rust-src

cargo install cargo-fuzz --locked --version "$CARGO_FUZZ_VERSION"
cargo install cargo-audit --locked --version "$CARGO_AUDIT_VERSION"
cargo install cargo-geiger --locked --version "$CARGO_GEIGER_VERSION"

# World-readable so the non-root user reads the toolchain and registry cache.
chmod -R a+rX /usr/local/rustup /usr/local/cargo

rustc --version
cargo-fuzz --version
cargo-audit --version
cargo-geiger --version
