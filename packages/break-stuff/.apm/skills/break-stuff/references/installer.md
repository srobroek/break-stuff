# Installer flow

How break-stuff handles tool availability. The tools run in the surface image, not
on the host (`references/isolation.md`, What runs where), so step 3 does not install
scanners on the host at all: it builds or extends the image and bakes the target's
dev-deps into it (`isolation.md`, Provisioning). A tool missing from the image
becomes a reported coverage gap, surfaced by `--assert-tools`.

## Host preflight, then image provisioning

The only host requirement is the container runtime plus `bd` and `git`;
`scripts/install-tools.sh --probe` is a preflight that confirms these and reports
which surface images exist. It installs nothing on the host: a host-side scanner
would run the target's code outside the container, so every tool lives in the image.

1. **Preflight (host):** `install-tools.sh --probe` confirms a runtime
   (`docker`/`finch`), `bd`, and `git`, and lists which `break-stuff/<surface>:1`
   images are built. No runtime means the execution phases cannot run
   (`isolation.md`, Degrade loudly).
2. **Provision (image):** build any missing surface image from
   `references/containers/`, and extend it with the target's dev-deps per
   `isolation.md` Provisioning, keyed on the manifest+lock so the layer caches.
3. **Assert (image):** `run-contained.sh --assert-tools <image> <tools>` confirms
   every campaign tool answers inside the image before the run trusts a clean result.

MUST Provision tools into the image, never onto the host. A scanner on the host runs the target's build code unconfined, the exact risk the container removes.
MUST Treat a missing runtime as a hard stop for the execution phases. Report a missing image tool as a coverage gap in the report; never let it pass as a silent skip.

When no container runtime exists at all, the run does not fall back to host tools: it
refuses every execution phase and runs only the host-safe reads, per `isolation.md`
(Degrade loudly). There is no host-install path to reach for.

## Image build notes

These are requirements for the surface `Dockerfile`, not host installs. The
`references/containers/Dockerfile.<surface>` bakes each tool with a pinned version
(see `tooling.md`, Where tools come from); a few carry a toolchain constraint:

| Tool | Build requirement |
|---|---|
| `cargo-fuzz` | a nightly toolchain for `-Zsanitizer=address`; the rust image installs nightly for the fuzz target |
| `atheris` | a matching CPython build (it fails on some 3.13-plus builds), so the python image pins the interpreter version it was built against |
| `go test -fuzz` | Go 1.18 or later, built into the toolchain image; nothing extra |
| AFL++ | needs an instrumented build of the target, so the native image ships the AFL toolchain |

MUST Bake a fuzzer with the toolchain it needs, pinned, and `--assert-tools` it before the run trusts a clean result. A fuzzer that cannot build its instrumented target is unavailable in practice, and the assert catches it up front.
NOT Never provision a fuzzer or its toolchain on the host. It belongs in the image; a host toolchain switch to satisfy a fuzzer is the host contamination the container model removes.
