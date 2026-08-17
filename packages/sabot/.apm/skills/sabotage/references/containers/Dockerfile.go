# Go surface. Base + the go toolchain and code/robustness tools.
#
# Composes per the base model: FROM the language-free base, then run the go fragment
# (layers/go.sh) which installs a pinned go toolchain + gosec + golangci-lint. Pins and
# their renovate comments live in the fragment.
#
# Build: docker build -f Dockerfile.go -t sabot/go:1 --build-arg BASE=sabot/base:1 .
ARG BASE=sabot/base:1
FROM ${BASE}
USER root
COPY layers/go.sh /tmp/go.sh
RUN bash /tmp/go.sh && rm /tmp/go.sh

# GOPROXY=off is the offline contract: a missing module fails immediately and names
# itself, instead of blocking on a proxy dial that --network none will never complete.
# GOMODCACHE points at the shared /deps prefix build-ext-image.sh bakes a target's
# module deps into. GOCACHE is deliberately left unset: run-contained.sh points it at
# the writable /scratch tmpfs, and a value under the read-only /deps would break a
# build that ran without the wrapper.
ENV GOROOT=/usr/local/go \
    GOPATH=/deps/go \
    GOMODCACHE=/deps/go/pkg/mod \
    GOPROXY=off \
    GOFLAGS=-mod=mod \
    PATH=/usr/local/go/bin:/deps/go/bin:$PATH
USER breaker
WORKDIR /scratch
VOLUME /artifacts
