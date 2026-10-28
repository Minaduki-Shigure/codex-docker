import asyncio
import json

import httpx2 as httpx


class GatewayError(Exception):
    def __init__(self, code, metadata=None):
        super().__init__(code)
        self.code = code
        self.metadata = metadata or {}


class Gateway:
    def __init__(self, base_url, key, timeout, transport=None):
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + key},
            timeout=timeout, follow_redirects=False, trust_env=False, transport=transport,
        )

    async def _request(self, method, path, *, deadline=None, **kwargs):
        try:
            async with asyncio.timeout(deadline or self.timeout):
                async with self.client.stream(method, path, **kwargs) as response:
                    if response.status_code != 200:
                        # Upstream bodies can echo credentials or source text.
                        raise GatewayError("upstream_http_" + str(response.status_code))
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            raise GatewayError("upstream_response_too_large")
                        chunks.append(chunk)
                    try:
                        body = json.loads(b"".join(chunks))
                    except (ValueError, UnicodeDecodeError, RecursionError):
                        raise GatewayError("upstream_invalid_json") from None
                    return body, response.headers
        except (TimeoutError, httpx.TimeoutException):
            raise GatewayError("upstream_timeout_outcome_unknown") from None
        except httpx.HTTPError:
            raise GatewayError("upstream_connection_error") from None

    async def models(self):
        body, _ = await self._request("GET", "models", deadline=10)
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise GatewayError("invalid_model_catalog")
        return sorted({item["id"] for item in body["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)})

    async def generate(self, model, messages, max_tokens, request_id):
        body, headers = await self._request("POST", "chat/completions", json={
            "model": model, "messages": messages, "stream": False,
            "max_tokens": max_tokens,
        }, headers={"X-Magpie-Session": "translation-mcp-" + request_id})
        metadata = {"requested_model": model, "resolved_model": headers.get("X-Magpie-Model"), "provider": headers.get("X-Magpie-Provider")}
        if isinstance(body, dict):
            metadata["response_model"] = body.get("model") if isinstance(body.get("model"), str) else None
            usage = body.get("usage", {})
            metadata["usage"] = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(usage, dict) and isinstance(usage.get(k), int)}
        try:
            choice = body["choices"][0]
            message = choice["message"]
            if message.get("refusal") or choice.get("finish_reason") == "content_filter":
                raise GatewayError("upstream_refusal", metadata)
            if choice.get("finish_reason") != "stop":
                raise GatewayError("upstream_incomplete", metadata)
            content = message["content"]
            if not isinstance(content, str) or not content.strip() or message.get("tool_calls"):
                raise GatewayError("upstream_invalid_content", metadata)
        except (KeyError, TypeError, IndexError, AttributeError):
            raise GatewayError("upstream_invalid_response", metadata) from None
        return content, metadata

    async def close(self):
        await self.client.aclose()
