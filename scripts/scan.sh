#!/usr/bin/env bash
set -euo pipefail
image=${1:?Usage: scan.sh IMAGE}
scanner=ghcr.io/aquasecurity/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
mkdir -p dist
archive=$(mktemp -d)
trap 'rm -rf -- "$archive"' EXIT
docker image save --output "$archive/image.tar" "$image"

# Scan an archive: the scanner gets neither a Docker socket nor registry tokens.
# Findings are reported, not silently treated as an assurance of vulnerability-free software.
docker run --rm \
    --mount "type=bind,source=$archive,target=/input,readonly" \
    --mount "type=bind,source=$(pwd)/dist,target=/output" \
    "$scanner" image --input /input/image.tar \
    --scanners vuln --exit-code 0 --timeout 10m \
    --format json --output /output/vulnerabilities.json
test -s dist/vulnerabilities.json
jq '[.Results[]?.Vulnerabilities[]?] | group_by(.Severity) | map({severity: .[0].Severity, count: length})' dist/vulnerabilities.json
