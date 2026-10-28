import httpx2 as httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from translation_mcp.server import create_app
from test_translation import service, good, request

TOKEN = "x" * 40


async def test_authenticated_protocol(tmp_path, caplog):
    translator = service(tmp_path, [good()])
    app = create_app(translator, TOKEN)
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), trust_env=False) as http:
            url = "http://translation-mcp:8000/mcp"
            assert (await http.get("http://translation-mcp:8000/healthz")).status_code == 200
            assert (await http.post(url)).status_code == 401
            headers = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json, text/event-stream"}
            assert (await http.post(url, headers={**headers, "Host": "evil.example"}, json={})).status_code in (400, 421)
            assert (await http.post(url, headers={**headers, "Origin": "http://evil.example"}, json={})).status_code == 403
            http.headers.update(headers)
            async with Client(streamable_http_client(url, http_client=http), mode="legacy") as client:
                listed = await client.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                assert set(tools) == {"list_translation_models", "translate_batch", "validate_translation", "review_batch"}
                assert tools["translate_batch"].annotations.read_only_hint is False
                result = await client.call_tool("translate_batch", {"request": request().model_dump()})
                assert result.structured_content is not None, result
                assert result.structured_content["status"] == "ok"
                repeat = await client.call_tool("translate_batch", {"request": request().model_dump()})
                assert repeat.structured_content["cached"]
                bad = await client.call_tool("translate_batch", {"request": {"secret-test-input": "private-dialogue"}})
                assert bad.is_error
    assert "private-dialogue" not in caplog.text
    assert TOKEN not in caplog.text
