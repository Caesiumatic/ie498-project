import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from ie498.agents import request_body
from ie498.cli import load_config
from ie498.subscription_transport import (
    BILLING_PATH, ENDPOINT, TRANSPORT, extract_text, normalized_usage,
    permanent_error, send, subscription_request, transport_metadata,
)


def _completed(text='{"memory_bullet":"- I will explore prices.","price":1.75}'):
    return {
        "type": "response.completed",
        "response": {
            "id": "resp_test", "model": "gpt-6-luna", "status": "completed",
            "output": [{"type": "reasoning", "summary": []}, {
                "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }],
            "usage": {"input_tokens": 31, "output_tokens": 14, "total_tokens": 45,
                      "input_tokens_details": {"cached_tokens": 3},
                      "output_tokens_details": {"reasoning_tokens": 4}},
        },
    }


def _sse(events):
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


def _call(events, *, status=200, body=None):
    async def run():
        async def handler(request):
            assert str(request.url) == ENDPOINT
            assert request.headers["authorization"] == "Bearer test-only"
            return httpx.Response(status, text=body if body is not None else _sse(events),
                                  headers={"x-request-id": "test-request"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await send(client, {"model": "gpt-6-luna", "store": False, "stream": True}, "test-only")
    return asyncio.run(run())


@pytest.mark.parametrize("purpose,architecture", [
    ("seller", "bullet_memory"), ("compressor", "bullet_memory"), ("seller", "paper_reference"),
])
def test_translation_preserves_prompt_and_schema_without_agent_context(purpose, architecture):
    config = load_config()
    config["architecture"] = architecture
    prompt = "Exact prompt\n  keep whitespace, 雪, and decimals 1.75.\n"
    canonical = request_body(config, prompt, purpose)
    original = deepcopy(canonical)
    body = subscription_request(canonical)
    assert body["input"] == [{"role": "user", "content": prompt}]
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"] == {"effort": "low"}
    assert body["store"] is False and body["stream"] is True
    assert set(body) <= {"model", "reasoning", "input", "store", "stream", "text"}
    if "response_format" in canonical:
        assert body["text"]["format"] == {"type": "json_schema", **canonical["response_format"]["json_schema"]}
    else:
        assert "text" not in body
    assert canonical == original
    assert transport_metadata(canonical)["omitted_request_parameters"]["max_completion_tokens"] == canonical["max_completion_tokens"]


def test_stream_success_keeps_raw_evidence_and_maps_usage_separately():
    events = [{"type": "response.output_text.delta", "delta": "partial"}, _completed()]
    raw = _call(events)
    assert raw["transport"] == TRANSPORT and raw["request_id"] == "test-request"
    assert raw["events"] == events
    assert extract_text(raw, "gpt-6-luna") == events[-1]["response"]["output"][-1]["content"][0]["text"]
    usage = normalized_usage(raw)
    assert usage["prompt_tokens"] == 31 and usage["completion_tokens"] == 14
    assert usage["completion_tokens_details"] == {"reasoning_tokens": 4}
    assert usage["cash_cost_usd"] == 0 and usage["billing_path"] == BILLING_PATH
    assert usage["responses_usage"] == events[-1]["response"]["usage"]
    assert "usage" not in raw


@pytest.mark.parametrize("code", [
    "subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable",
])
def test_late_stream_error_does_not_accept_partial_text_or_retry(code):
    events = [{"type": "response.output_text.delta", "delta": "plausible partial output"}, {
        "type": "response.failed", "response": {"status": "failed", "error": {"code": code}},
    }]
    raw = _call(events)
    assert raw["http_status"] == 200 and raw["error"]["code"] == code
    assert permanent_error(raw)
    with pytest.raises(ValueError, match="unsuccessful"):
        extract_text(raw, "gpt-6-luna")


def test_no_terminal_event_and_nonstandard_admission_error_are_preserved():
    raw = _call([{"type": "response.output_text.delta", "delta": "not a complete response"}])
    assert raw["error"]["type"] == "IncompleteStream"
    raw = _call([], status=403, body='{"detail":"Direct route not permitted"}')
    assert raw["http_error_body"] == {"detail": "Direct route not permitted"}
    assert permanent_error(raw)


def test_completed_event_does_not_accept_a_different_model_or_tool_call():
    raw = _call([_completed()])
    raw["response"]["model"] = "gpt-6-luna-2026-11-01"
    with pytest.raises(ValueError, match="Unexpected response model"):
        extract_text(raw, "gpt-6-luna")
    raw["response"]["model"] = "gpt-6-luna"
    raw["response"]["output"] = [{"type": "function_call", "name": "shell"}]
    with pytest.raises(ValueError, match="non-message or tool"):
        extract_text(raw, "gpt-6-luna")


def test_interrupted_stream_retains_the_observed_events():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _sse([{"type": "response.output_text.delta", "delta": "partial"}]).encode()
            raise httpx.ReadError("test disconnect")

    async def run():
        async def handler(request):
            return httpx.Response(200, stream=BrokenStream())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await send(client, {}, "test-only")
    raw = asyncio.run(run())
    assert raw["events"] == [{"type": "response.output_text.delta", "delta": "partial"}]
    assert raw["error"]["type"] == "ReadError"
    with pytest.raises(ValueError):
        extract_text(raw, "gpt-6-luna")


def test_completed_sample_does_not_wait_for_connection_shutdown():
    class CompletedThenBroken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _sse([_completed()]).encode()
            raise httpx.ReadError("Connection failed after completed response")

    async def run():
        async def handler(request):
            return httpx.Response(200, stream=CompletedThenBroken())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await send(client, {}, "test-only")
    raw=asyncio.run(run())
    assert 'error' not in raw
    assert extract_text(raw,'gpt-6-luna')
    assert raw['events']==[_completed()]
