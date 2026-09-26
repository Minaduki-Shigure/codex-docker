# Codex Docker

A personal, non-OpenAI container image for the official Codex CLI. Built on the
official `node:24-bookworm-slim` image, not the large `codex-universal` image.

Image: `ghcr.io/minaduki-shigure/codex-docker:latest`

## Included

- The complete, signed official Codex Linux release package, including its
  adjacent helper binaries and resources.
- Node.js 24 and npm; Python 3 with venv and pip inside virtual environments.
- Git, OpenSSH client, curl, ripgrep, jq, less, procps and CA certificates.
- The non-root `node` user (UID/GID 1000), `/workspace`, and `/home/node/.codex`.
- Native `linux/amd64` and `linux/arm64` builds.

No model credentials, user configuration, workspaces, SSH keys, or proxy
addresses are baked into the image. No API provider is selected by the image.
Compilers, browser runtimes and additional languages are intentionally omitted.

## Run

Create a local `.env` using the settings in `.env.example`. The tracked `config/`
and `workspace/` directories are empty placeholders; their contents are ignored
by Git. Alternatively, set `CODEX_CONFIG_DIR` and `CODEX_WORKSPACE_DIR` to existing
absolute paths. On Linux, both mounts must be writable by UID/GID 1000.

Run Codex, checking for an updated image before each new container starts:

```sh
docker compose run --rm codex
```

The service uses `pull_policy: always`. It checks the registry on each run and
downloads only layers missing from the local cache. Unchanged images are not
downloaded again. An existing running container is not upgraded in place.

Registry access is required for the automatic check. To use an already-cached
image offline, or temporarily skip updates:

```sh
docker compose run --rm --pull never codex
```

Open a shell instead of Codex:

```sh
docker compose run --rm --entrypoint bash codex
```

Keep provider configuration in `config/config.toml` and credentials in the
untracked `.env` or another runtime secret mechanism. OpenCode Go credentials
are supported as an environment passthrough; endpoint/model compatibility is
not tested by the image build.

The example drops all Linux capabilities, disables privilege escalation, and
mounts no Docker socket. Docker isolation does not protect files or credentials
that you explicitly mount or inject. We do not turn off Codex's own approvals
or sandbox in the image. Proxy environment variables are supported, but they
are not a network firewall and cannot force every subprocess through a proxy.

## Build and release

GitHub Actions runs on pushes to `main`, manually, and daily at 03:17 UTC.
Pull requests run static/unit checks only and cannot publish images.

1. Resolve the latest official stable Codex release and the Node base digest.
   Record exact asset URLs and SHA-256 checksums in `build-inputs.json`.
2. Verify each full release archive's checksum and Sigstore signature, including
   the exact `openai/codex` release workflow identity and release tag.
3. Build each architecture on a native GitHub-hosted runner. Refresh Debian
   packages on each build. Publish uniquely named candidate images with SBOMs
   and BuildKit provenance.
4. Pull and test each candidate by digest, without network or model credentials.
   Check CLI startup, language tools, non-root execution and bind-mount writes.
   Generate a Trivy vulnerability report. Scanner failures block promotion;
   vulnerability findings are report-only, not a severity gate.
5. Merge only successful candidates, generate a GitHub artifact attestation,
   then promote the manifest to `latest` and the Codex version tag.

Actions are pinned to full commit SHAs; Buildx, BuildKit, the SBOM generator,
Cosign and the vulnerability scanner are pinned too. Dependabot proposes Action
updates. Other tool pins should be reviewed periodically.

Published tags:

- `latest`: newest build that passed all pipeline steps.
- `<codex-version>`: newest tested base/package rebuild for that CLI version.
- `<codex-version>-build-<run-id>-<attempt>`: unique build, not overwritten by
  this workflow. For content immutability, pin the full `sha256` image digest.
- `candidate-*`: intermediate artifacts; not intended for normal use.

The base and Codex package inputs are locked per build. Debian package indexes,
security updates and vulnerability databases are intentionally refreshed, so
this is not a claim of bit-for-bit reproducible builds. Signatures and SBOMs
establish provenance and visibility, not the absence of vulnerabilities.

Build inputs are embedded at `/usr/local/share/codex-docker/build-inputs.json`.
Inputs, tested digests and scan reports are also retained as workflow artifacts
for 90 days. The workflow does not delete old published images automatically.

## GitHub setup

- Repository: `Minaduki-Shigure/codex-docker`, public, default branch `main`.
- Allow GitHub Actions and the workflow's package/attestation permissions.
- No personal access token or model API key is needed by the workflow. GHCR
  publication uses its short-lived `GITHUB_TOKEN`.
- A new GHCR package may initially be private even for a public repository.
  After the first build, change the package visibility to public in its package
  settings for anonymous pulls. Keep package Actions access linked to this repo.
- Scheduled workflows in public repositories can be disabled after 60 days of
  repository inactivity. GitHub schedules can also be delayed; manual runs are
  available from the Actions tab.
- A deploy key is only needed to push source from a workstation. Never place
  its private key in this repository, a workflow secret or the image.

## Verification

```sh
python3 -m unittest discover -s tests -v
bash -n scripts/smoke-test.sh scripts/scan.sh
docker compose --env-file /dev/null config --quiet
```

For a manual build, use Python 3.12+, Docker Buildx, curl and Cosign 3.x:

```sh
python3 scripts/upstream.py resolve
python3 scripts/upstream.py fetch --arch arm64
docker build \
  --build-arg BASE_IMAGE="$(jq -r .base_image dist/build-inputs.json)" \
  --build-arg CODEX_VERSION="$(jq -r .codex_version dist/build-inputs.json)" \
  --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t codex-docker:test .
bash scripts/smoke-test.sh codex-docker:test "$(jq -r .codex_version dist/build-inputs.json)"
```

Use `--arch amd64` on x86-64. Start with a fresh `dist/package` directory when
preparing another package. The fetch script refuses to overlay existing files.

After publication, verify the build identity with an authenticated GitHub CLI:

```sh
gh attestation verify oci://ghcr.io/minaduki-shigure/codex-docker@sha256:REPLACE_WITH_DIGEST \
  --repo Minaduki-Shigure/codex-docker
```

## Upstream references

- [Official Codex source and releases](https://github.com/openai/codex)
- [Official Node Docker image](https://github.com/nodejs/docker-node)
- [GitHub container publishing](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use)
- [Compose pull policy](https://docs.docker.com/reference/compose-file/services/#pull_policy)
