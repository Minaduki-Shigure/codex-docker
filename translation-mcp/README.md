# Translation MCP

Text-only Japanese/English to Simplified Chinese localization through Magpie.
Codex extracts text and writes files. This service sees only the supplied text,
has no workspace mount, and never receives upstream provider keys.

Image: `ghcr.io/minaduki-shigure/translation-mcp:latest`

Source and release workflow are maintained in this repository, independently
of the Codex CLI image. Both native `linux/amd64` and `linux/arm64` are supported.

## Tools

- `list_translation_models`: current allowed catalog, defaults and limits; no inference.
- `translate_batch`: ordered text, IDs, scene context, characters, glossary; paid.
- `validate_translation`: local ID, common format-token and glossary checks; free.
- `review_batch`: optional source/translation review; suggestions only; paid.

Tool arguments use a single `request` object (except model listing):

```json
{
  "request": {
    "request_id": "project1-scene12-v1",
    "source_language": "ja",
    "target_language": "zh-Hans",
    "context": "Two friends part at the station; restrained rather than formal.",
    "characters": [{"name": "Aria", "voice": "Reserved, short sentences"}],
    "segments": [
      {"id": "line001", "speaker": "Aria", "text": "また会おう、{name}。"},
      {"id": "line002", "text": "約束だよ。"}
    ],
    "glossary": [{"source": "アリア", "target": "艾莉亚", "required": true}],
    "glossary_version": "v1",
    "preserve_line_breaks": true,
    "allow_fallback": true
  }
}
```

`model` optionally selects a fully qualified Magpie ID. Defaults are
`deepseek/deepseek-flash` and `openrouter/~google/gemini-flash-latest`.
Default-model errors, structured refusals, incomplete responses, invalid JSON,
IDs or hard validation failures can trigger exactly one whole-batch fallback.
There is no automatic quality review or per-line mixing. Selecting a different
model disables this implicit chain; `allow_fallback:false` always permits at
most one inference request. A fallback can use a different provider, including
after a timeout where the first provider's billing outcome is unknown.

Review adds `translations:[{"id":"line001","text":"..."}, ...]` and a new
request ID. To use another model as reviewer, explicitly set `model`. Review
does not mutate previous translations. Suggestions include local format checks.
For local validation, omit `request_id`, `model`, `allow_fallback` and include
`translations` alongside the original batch fields.

## Limits and Reliability

Default 64 segments, 16,000 serialized input characters (including metadata),
8,192 output tokens, 120 seconds per inference, 10 seconds per catalog fetch,
two concurrent requests. Split by scene; carry a curated glossary and relevant
neighboring context between batches. There is no file parser, context retrieval,
automatic terminology memory or long-running background job system.

Required glossary matching is literal and case-sensitive, not semantic. Common
printf, brace placeholders, HTML/ASS tags, RPGMaker codes and line breaks are
checked. Add custom engine markers to each segment's `protected_tokens`.
Space-flag or English-word-adjacent printf forms (such as `% d` or `%dth`) need
explicit protection to avoid confusing natural percentage prose with formats.
Complex ICU/nested markup needs extractor-side validation. Local checks do not
prove translation accuracy, Chinese fluency, encoding suitability or line width.
A refusal hidden as ordinary translated prose cannot be reliably identified by
format validation. Review important dialogue rather than trusting `valid:true`
as a semantic quality score.

Check `status == "ok"`, `validation`, `attempts` and `fallback_used` before
applying output. Requested/resolved/response model IDs and usage are reported
when Magpie supplies them. Latest aliases can change upstream targets.

Reuse `request_id` only with identical input, operation and policy. Completed
results, including failures, are replayed without inference. Changed input under
the same ID is rejected. An interrupted pending request is never silently
reissued; verify its outcome before consciously using a new ID. This is bounded
local duplicate protection, not a guarantee of exactly-once upstream billing.

## Privacy and Deployment

Official MCP Python SDK, Streamable HTTP at `/mcp`, bearer authentication,
Host/Origin checks, 256 KiB request cap, no shell/filesystem tools. `/healthz`
reveals only service status/version. No host port or Docker socket is needed.
Internal Magpie requests deliberately ignore environment proxies and never
follow redirects with credentials. Magpie handles external proxying.

`/config/policy.json` and `/run/secrets/{magpie_key,mcp_token}` are read-only.
`/data/requests.sqlite` stores request IDs, input hashes and translated/review
results, not complete source payloads. It is **plaintext sensitive state**, with
no automatic expiry; directory 0700, database 0600. Retain it for idempotency,
or remove it only with the service stopped, accepting loss of deduplication.
Source hashes and model metadata can also be sensitive. Do not commit secrets
or state. Codex sessions and upstream vendor retention are independent.

Console access logs are disabled. No model response/error bodies are logged by
the application. `DO_NOT_TRACK=1` is set; no telemetry exporter is installed.
No full-request trace or hidden retries are implemented.

The local runtime uses a non-root, read-only container with dropped capabilities,
no-new-privileges and a temporary `/tmp`. It shares the existing agent bridge,
not a firewall-enforced egress sandbox. Its Magpie key initially permits only
the two configured models. Expand the key scope and provider model selection in
Magpie when adding another translator. Provider secrets stay exclusively there.

The `compose.example.yml` is a sidecar-only example joining an existing Magpie
network. Create private `config/`, `secrets/` and `state/` directories first,
copy `policy.example.json` to `config/policy.json`, and supply separate gateway
and MCP secrets in `secrets/magpie_key` and `secrets/mcp_token`. On Linux, these
mounts must be accessible to UID/GID 65532; only state needs write permission.
Set `MAGPIE_NETWORK` when your network has a different name. Do not publish
port 8000 unless you deliberately add a separately secured access path.

```bash
docker compose -f compose.example.yml pull translation-mcp
docker compose -f compose.example.yml run --rm --use-aliases translation-mcp
```

For an existing disposable Codex/Magpie setup, copy the service into its Compose
file and have the launcher own all three one-off containers. A bare Compose
`run codex` does not automatically clean up sidecars. Configure Codex with:

```toml
[mcp_servers.translation]
url = "http://translation-mcp:8000/mcp"
bearer_token_env_var = "TRANSLATION_MCP_TOKEN"
startup_timeout_sec = 30
tool_timeout_sec = 300
```

Inject the same MCP token into Codex as `TRANSLATION_MCP_TOKEN`, not the Magpie
key. Add `translation-mcp` and `magpie` to Codex's `NO_PROXY` when it uses a
host proxy. Never commit these runtime credentials or personal configuration.

Configuration changes apply on restart. For a timeout above 120 seconds, adjust
Codex's MCP `tool_timeout_sec` to cover two calls plus the catalog/transport.
Code changes are built by GitHub Actions; users pull the published image instead
of building locally. The example checks `latest` at each start and downloads
only changed layers. `TRANSLATION_MCP_PULL_POLICY=never` uses a cached image.
`TRANSLATION_MCP_IMAGE=ghcr.io/minaduki-shigure/translation-mcp@sha256:...` pins
an exact build for rollback. Running containers are never replaced in place.

## Release Maintenance

Pushes affecting this directory, manual runs and a daily 03:47 UTC schedule run
the separate translation workflow. PRs test without registry-write credentials.
Both architectures must pass unit/protocol tests and network-isolated image
smoke checks before `latest` is promoted. Candidates carry SBOMs and provenance;
the final multi-platform manifest has a GitHub artifact attestation. Trivy
findings are retained as reports, not a vulnerability severity gate.

Actions and build/scanner tools follow the root image's pinned versions. The
Python base is digest-pinned and Python packages have exact version pins.
Dependabot proposes weekly pip/Docker updates for review; the daily job does
not silently upgrade those locked inputs. Provenance is not proof that an
image is vulnerability-free. No model credentials or paid inference are used
by CI. The Docker build context includes only runtime code and dependencies.

Tags: `latest`, `sha-<full-commit>` (latest tested rebuild of that revision),
`build-<run-id>-<attempt>` (unique workflow build), and intermediate
`candidate-*` tags. Pin a digest for content immutability. Scan reports and
tested architecture digests are retained for 90 days. Old packages are not
automatically deleted.

On first publication, the GHCR package may be private; set it to public in
GitHub package settings to allow anonymous pulls. Publication itself uses the
workflow's short-lived `GITHUB_TOKEN`, not an extra PAT or provider key.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests are offline and do not use provider credentials. Real inference tests
must be explicitly authorized and separately budgeted. Local migration scripts,
personal runtime snapshots, credentials and translation state are not published.

References: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp),
[Magpie reference](https://github.com/yetone/magpie/blob/main/docs/reference.md).
