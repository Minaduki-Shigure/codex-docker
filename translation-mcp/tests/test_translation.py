import asyncio
import json

import httpx2 as httpx
import pytest
from pydantic import ValidationError

from translation_mcp.gateway import Gateway, GatewayError
from translation_mcp.models import Batch, Policy, ReviewRequest, TranslateRequest, Translation
from translation_mcp.service import Translator, parse_output
from translation_mcp.storage import Store
from translation_mcp.validation import validate

PRIMARY = Policy().primary_model
BACKUP = Policy().fallback_model


class FakeGateway:
    def __init__(self, outputs=(), models=None):
        self.outputs = iter(outputs)
        self.catalog = models or [PRIMARY, BACKUP, "other/model"]
        self.calls = []

    async def models(self):
        return self.catalog

    async def generate(self, model, messages, max_tokens, request_id):
        self.calls.append((model, messages))
        output = next(self.outputs)
        if isinstance(output, BaseException):
            raise output
        return json.dumps(output), {"requested_model": model, "resolved_model": model, "usage": {"total_tokens": 12}}

    async def close(self):
        pass


def request(**kwargs):
    return TranslateRequest.model_validate({"request_id": "scene-1", "segments": [{"id": "a", "text": "Hello, {name}!"}], **kwargs})


def good():
    return {"translations": [{"id": "a", "text": "你好，{name}！"}]}


def service(tmp_path, outputs, **kwargs):
    gateway = FakeGateway(outputs, **kwargs)
    return Translator(Policy(), gateway, Store(tmp_path / "test.sqlite"))


@pytest.mark.parametrize("source,target,code", [
    ("Hello {name}", "你好", "protected_token_mismatch"),
    ("%s has %d", "%d属于%s", "printf_order_mismatch"),
    ("<b><i>Hello</i></b>", "<i><b>你好</b></i>", "tag_order_mismatch"),
    ("one\ntwo", "一二", "line_break_mismatch"),
    ("\\C[1]Hello\\C[0]", "你好", "protected_token_mismatch"),
    ("\\N[1]Hello", "\\N[2]你好", "protected_token_mismatch"),
    ("Hello", "", "empty_translation"),
])
def test_validation_errors(source, target, code):
    result = validate(Batch(segments=[{"id": "a", "text": source}]), [Translation(id="a", text=target)])
    assert not result["valid"]
    assert code in {issue["code"] for issue in result["issues"]}


def test_validation_ids_glossary_explicit():
    batch = Batch(segments=[{"id": "a", "text": "Aria @21", "protected_tokens": ["@21"]}], glossary=[{"source": "Aria", "target": "艾莉亚"}])
    result = validate(batch, [Translation(id="a", text="爱丽亚"), Translation(id="a", text="爱丽亚"), Translation(id="b", text="多余")])
    assert {i["code"] for i in result["issues"]} >= {"duplicate_ids", "unexpected_id", "required_glossary_term_missing", "explicit_token_mismatch"}
    assert not validate(batch, [Translation(id="b", text="测试")])["valid"]


def test_positioned_placeholders_can_move():
    assert validate(Batch(segments=[{"id": "a", "text": "%1$s: %2$d"}]), [Translation(id="a", text="%2$d属于%1$s")])["valid"]


@pytest.mark.parametrize("source,target", [("100% of it", "全部"), ("50%off", "五折"), ("%02d points, %s", "%02d分，%s")])
def test_percent_prose_and_common_formats(source, target):
    assert validate(Batch(segments=[{"id": "a", "text": source}]), [Translation(id="a", text=target)])["valid"]


@pytest.mark.parametrize("payload", [
    {"segments": [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]},
    {"segments": [{"id": "a", "text": "x", "protected_tokens": ["absent"]}]},
    {"glossary": [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}]},
    {"unknown": True},
    {"request_id": "bad\nheader"},
])
def test_invalid_input(payload):
    with pytest.raises(ValidationError):
        request(**payload)


async def test_primary_dedup_and_conflict(tmp_path):
    s = service(tmp_path, [good()])
    result = await s.run("translate", request())
    assert result["status"] == "ok" and not result["fallback_used"]
    assert (await s.run("translate", request()))["cached"]
    assert len(s.gateway.calls) == 1
    assert (await s.run("translate", request(context="changed")))["error"] == "request_id_reused_with_different_input"
    s.store.close()
    s.store = Store(tmp_path / "test.sqlite")
    assert (await s.run("translate", request()))["cached"]


@pytest.mark.parametrize("failure", [
    GatewayError("upstream_http_429"), GatewayError("upstream_timeout_outcome_unknown"),
    GatewayError("upstream_refusal"), {"refusal": "Cannot translate"}, {"wrong": []},
    {"translations": [{"id": "a", "text": "缺少占位符"}]},
])
async def test_whole_batch_fallback(tmp_path, failure):
    s = service(tmp_path, [failure, good()])
    result = await s.run("translate", request())
    assert result["status"] == "ok" and result["fallback_used"]
    assert [call[0] for call in s.gateway.calls] == [PRIMARY, BACKUP]
    assert s.gateway.calls[0][1] == s.gateway.calls[1][1]


@pytest.mark.parametrize("kwargs", [{"allow_fallback": False}, {"model": BACKUP}, {"model": "other/model"}])
async def test_no_hidden_fallback(tmp_path, kwargs):
    s = service(tmp_path, [GatewayError("upstream_refusal"), good()])
    assert (await s.run("translate", request(**kwargs)))["status"] == "error"
    assert len(s.gateway.calls) == 1


async def test_catalog_and_size_do_not_charge(tmp_path):
    s = service(tmp_path, [], models=["unrelated/model"])
    assert (await s.run("translate", request()))["status"] == "error"
    s.policy.max_input_chars = 100
    assert (await s.run("translate", request(request_id="large")))["error"] == "input_too_large_split_by_scene"
    assert not s.gateway.calls


async def test_cancel_does_not_fallback_and_is_not_replayed(tmp_path):
    s = service(tmp_path, [asyncio.CancelledError(), good()])
    with pytest.raises(asyncio.CancelledError):
        await s.run("translate", request())
    assert len(s.gateway.calls) == 1
    assert (await s.run("translate", request()))["error"] == "request_interrupted_outcome_unknown"


async def test_review_validates_suggestions(tmp_path):
    s = service(tmp_path, [{"reviewed_ids": ["a"], "issues": [{"id": "a", "severity": "suggestion", "category": "voice", "explanation": "语气", "suggested_translation": "你好"}]}])
    req = ReviewRequest(**request().model_dump(), translations=good()["translations"])
    result = await s.run("review", req)
    assert result["status"] == "ok"
    assert not result["issues"][0]["suggestion_validation"]["valid"]
    bad = ReviewRequest(**request(request_id="bad-review").model_dump(), translations=[{"id": "a", "text": "丢失"}])
    assert (await s.run("review", bad))["status"] == "validation_failed"
    assert len(s.gateway.calls) == 1


def test_output_parser():
    assert parse_output('```json\n{"translations": []}\n```') == {"translations": []}
    for content in ['{"a":1,"a":2}', 'not json', '```json\n{}\n``` trailing']:
        with pytest.raises(GatewayError):
            parse_output(content)


@pytest.mark.parametrize("body,error", [
    ({"choices": [None]}, "upstream_invalid_response"),
    ({"choices": [{"message": None}]}, "upstream_invalid_response"),
    ({"choices": [{"message": {"refusal": "private"}}]}, "upstream_refusal"),
    ({"choices": [{"message": {"content": "private"}, "finish_reason": "length"}]}, "upstream_incomplete"),
])
async def test_gateway_bad_outputs(body, error):
    g = Gateway("http://magpie:3425/v1", "secret-key", 5, httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    with pytest.raises(GatewayError, match=error):
        await g.generate(PRIMARY, [], 100, "test")
    await g.close()


async def test_gateway_no_redirect_no_payload_leak():
    calls = []
    def handler(r):
        calls.append(r)
        return httpx.Response(302, headers={"Location": "http://outside.example"}, text="private-source secret-key")
    g = Gateway("http://magpie:3425/v1", "secret-key", 5, httpx.MockTransport(handler))
    with pytest.raises(GatewayError) as error:
        await g.generate(PRIMARY, [], 100, "test")
    assert str(error.value) == "upstream_http_302"
    assert len(calls) == 1
    await g.close()
