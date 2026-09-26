ARG BASE_IMAGE=node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
FROM ${BASE_IMAGE}

ARG CODEX_VERSION
ARG BUILD_DATE
ARG VCS_REF
ARG BASE_IMAGE

# Refresh Debian security updates on each scheduled build, not each startup.
RUN test -n "$BUILD_DATE" \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git jq less openssh-client procps \
        python3 python3-venv ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o node -g node /workspace /home/node/.codex

# Prepared by scripts/upstream.py only after checksum and signature verification.
COPY dist/package/ /opt/codex/
COPY dist/build-inputs.json /usr/local/share/codex-docker/build-inputs.json
RUN test -x /opt/codex/bin/codex \
    && test -x /opt/codex/bin/codex-code-mode-host \
    && ln -s /opt/codex/bin/codex /usr/local/bin/codex \
    && test "$(codex --version)" = "codex-cli ${CODEX_VERSION}"

LABEL org.opencontainers.image.title="Codex Docker" \
      org.opencontainers.image.description="Official Codex CLI with Node.js and Python in a disposable container" \
      org.opencontainers.image.source="https://github.com/Minaduki-Shigure/codex-docker" \
      org.opencontainers.image.version="${CODEX_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="${BASE_IMAGE}"

ENV CODEX_HOME=/home/node/.codex
USER node
WORKDIR /workspace
ENTRYPOINT ["/opt/codex/bin/codex"]
CMD []
