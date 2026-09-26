#!/usr/bin/env bash
set -euo pipefail

image=${1:?Usage: smoke-test.sh IMAGE EXPECTED_VERSION}
version=${2:?Expected Codex version is required}
options=(--rm --pull never --network none --cap-drop ALL --security-opt no-new-privileges)

test "$(docker run "${options[@]}" "$image" --version)" = "codex-cli $version"
docker run "${options[@]}" "$image" --help >/dev/null
docker run "${options[@]}" "$image" exec --help >/dev/null
docker run "${options[@]}" --entrypoint bash "$image" -euc '
    test "$(id -u)" = 1000
    test "$CODEX_HOME" = /home/node/.codex
    test -w /workspace
    test -w "$CODEX_HOME"
    test -x /opt/codex/bin/codex-code-mode-host
    node --version
    npm --version
    python3 --version
    python3 -m venv /tmp/test-venv
    /tmp/test-venv/bin/python -m pip --version
    git --version
    ssh -V
    curl --version
    rg --version
    jq --version
    codex features list >/dev/null
'

# Bind-mount writes must survive --rm without requiring root on the host.
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/config" "$scratch/workspace"
chmod 777 "$scratch" "$scratch/config" "$scratch/workspace"
docker run "${options[@]}" \
    --mount "type=bind,source=$scratch/config,target=/home/node/.codex" \
    --mount "type=bind,source=$scratch/workspace,target=/workspace" \
    --entrypoint bash "$image" -euc '
        printf persisted > "$CODEX_HOME/smoke-test"
        printf persisted > /workspace/smoke-test
    '
test "$(cat "$scratch/config/smoke-test")" = persisted
test "$(cat "$scratch/workspace/smoke-test")" = persisted
printf 'Smoke tests passed: %s\n' "$image"
