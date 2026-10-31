FROM python:3.15-slim-bookworm@sha256:4e03260adeeebafccd084f3584e6b84823aba5651cfb53ef8a078ed441ddf9cd
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 DO_NOT_TRACK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt
COPY translation_mcp ./translation_mcp
ARG VCS_REF=unknown
ARG BUILD_DATE
LABEL org.opencontainers.image.source="https://github.com/Minaduki-Shigure/codex-docker" \
      org.opencontainers.image.title="Translation MCP" \
      org.opencontainers.image.description="Text-only localization MCP through Magpie" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.created=$BUILD_DATE
USER 65532:65532
EXPOSE 8000
CMD ["python", "-m", "translation_mcp.server"]
