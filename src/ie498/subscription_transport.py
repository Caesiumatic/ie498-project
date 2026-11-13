"""Stateless Responses transport for the official ChatGPT plan OAuth route.

This module never reads API keys or Codex credentials and never checks a quota.
The caller supplies the access token issued to this experiment's OAuth client.
Actual Responses events remain in the raw envelope; compatibility token fields
are derived separately and do not represent API cash charges.
"""

from copy import deepcopy
import json

import httpx


TRANSPORT = "chatgpt_subscription_responses"
ENDPOINT = "https://api.openai.com/v1/responses"
BILLING_PATH = "chatgpt_subscription"
_OMITTED_FIELDS = (
    "max_completion_tokens", "prompt_cache_options", "service_tier", "temperature",
)
_PAUSE_CODES = frozenset({
    "subscription_sharing_user_not_eligible",
    "subscription_sharing_usage_limit_exceeded",
    # Availability errors can be retried later, but this runner pauses rather
    # than automatically probing subscription availability repeatedly.
    "subscription_sharing_usage_unavailable",
    "subscription_sharing_unsupported_capability",
    "subscription_sharing_route_not_supported",
    "subscription_sharing_invalid_user",
    "chatpass_v2_scope_not_authorized",
    "chatpass_v2_invalid_authorization_context",
    "insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
})


def subscription_request(chat_body):
    """Translate the existing canonical request, preserving its user text.

    Output caps are unsupported on this subscription route. Cache controls and
    service-tier overrides are omitted explicitly and recorded by
    :func:`transport_metadata`. There are no hidden instructions, tools, stored
    conversations, or previous-response references.
    """
    messages = chat_body["messages"]
    if len(messages) != 1 or messages[0].get("role") != "user":
        raise ValueError("Subscription experiment requires one user message")
    content = messages[0]["content"]
    if isinstance(content, list):
        if any(part.get("type") != "text" or not isinstance(part.get("text"), str)
               for part in content):
            raise ValueError("Only text content is supported by this experiment")
        content = "".join(part["text"] for part in content)
    if not isinstance(content, str):
        raise ValueError("User prompt must be text")
    body = {
        "model": chat_body["model"],
        "reasoning": {"effort": chat_body["reasoning_effort"]},
        "input": [{"role": "user", "content": content}],
        "store": False,
        "stream": True,
    }
    if "response_format" in chat_body:
        response_format = chat_body["response_format"]
        if response_format.get("type") != "json_schema":
            raise ValueError("Expected the frozen JSON schema response format")
        body["text"] = {"format": {
            "type": "json_schema", **deepcopy(response_format["json_schema"]),
        }}
    return body


def transport_metadata(chat_body):
    """Describe the interface amendment without adding fields to the wire body."""
    return {
        "transport": TRANSPORT,
        "endpoint": ENDPOINT,
        "authentication": "experiment_client_chatgpt_oauth",
        "billing_path": BILLING_PATH,
        "omitted_request_parameters": {
            name: deepcopy(chat_body[name]) for name in _OMITTED_FIELDS if name in chat_body
        },
        "prompt_preservation": "single_user_message_text_unchanged",
    }


def _error_from_body(body, fallback):
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return deepcopy(body["error"])
    return {"type": fallback, "message": "Request failed; see preserved response body"}


async def send(client, body, access_token):
    """Make one inference attempt; return evidence even for an unsuccessful stream.

    No retry or billing fallback occurs here. A terminal response.completed
    event, rather than output deltas, establishes transport success.
    """
    if not access_token:
        raise ValueError("An experiment-client ChatGPT OAuth access token is required")
    envelope = {"transport": TRANSPORT, "endpoint": ENDPOINT, "events": []}
    try:
        async with client.stream(
            "POST", ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "text/event-stream"},
            json=body,
        ) as response:
            envelope.update({
                "http_status": response.status_code,
                "request_id": response.headers.get("x-request-id"),
                "rate_limits": {
                    key: value for key, value in response.headers.items()
                    if key.startswith("x-ratelimit-")
                },
            })
            if "retry-after" in response.headers:
                envelope["retry_after"] = response.headers["retry-after"]
            if not response.is_success:
                body_bytes = await response.aread()
                try:
                    error_body = json.loads(body_bytes)
                except (ValueError, UnicodeDecodeError):
                    error_body = body_bytes.decode("utf-8", errors="replace")
                envelope["http_error_body"] = error_body
                envelope["error"] = _error_from_body(error_body, "HTTPError")
                return envelope

            data_lines = []

            def accept_event():
                if not data_lines:
                    return
                data = "\n".join(data_lines)
                data_lines.clear()
                if data == "[DONE]":
                    return
                try:
                    event = json.loads(data)
                except ValueError:
                    envelope.setdefault("unparsed_sse_data", []).append(data)
                    envelope["error"] = {
                        "type": "MalformedSSE", "message": "A stream event was not valid JSON",
                    }
                    return
                envelope["events"].append(event)
                if not isinstance(event, dict):
                    envelope["error"] = {
                        "type": "MalformedSSE", "message": "A stream event was not an object",
                    }
                    return
                event_type = event.get("type")
                if isinstance(event.get("response"), dict):
                    envelope["response"] = event["response"]
                if event_type in ("response.completed", "response.failed", "response.incomplete"):
                    envelope["terminal_event"] = event_type
                    if event_type != "response.completed":
                        envelope["error"] = _error_from_body(
                            event.get("response"), event_type,
                        )
                elif event_type == "error":
                    # Responses error events may carry code/message directly.
                    envelope["error"] = deepcopy(event.get("error", event))

            async for line in response.aiter_lines():
                if line == "":
                    accept_event()
                    if envelope.get("terminal_event") in ("response.completed", "response.failed", "response.incomplete"):
                        # A terminal event finishes the response. Waiting for EOF
                        # could turn a completed sample into a retry if the server
                        # keeps the connection open or it fails during shutdown.
                        break
                elif line.startswith("data:"):
                    data_lines.append(line[5:].removeprefix(" "))
            accept_event()
            if "error" not in envelope and envelope.get("terminal_event") != "response.completed":
                envelope["error"] = {
                    "type": "IncompleteStream", "message": "Stream ended without response.completed",
                }
    except httpx.HTTPError as exc:
        # Do not include exception text, which can embed credential-bearing
        # request information. The exception class and partial events suffice.
        envelope["error"] = {
            "type": type(exc).__name__, "message": "Transport failure; subscription usage may have occurred",
        }
    return envelope


def extract_text(raw, expected_model):
    """Return only a successfully completed assistant output, or raise ValueError."""
    if raw.get("transport") != TRANSPORT or raw.get("error"):
        raise ValueError("Subscription response was unsuccessful")
    if raw.get("terminal_event") != "response.completed":
        raise ValueError("Subscription response lacks response.completed")
    response = raw.get("response")
    if not isinstance(response, dict) or response.get("status") != "completed":
        raise ValueError("Subscription response status is not completed")
    reported_model = response.get("model")
    if reported_model is not None and reported_model != expected_model:
        raise ValueError(f"Unexpected response model: {reported_model!r}")
    output = response.get("output")
    if not isinstance(output, list):
        raise ValueError("Subscription response has no output list")
    text = []
    for item in output:
        if not isinstance(item, dict):
            raise ValueError("Unexpected response output item")
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            raise ValueError("Unexpected non-message or tool output")
        if item.get("status") not in (None, "completed"):
            raise ValueError("Assistant message is not completed")
        if not isinstance(item.get("content"), list):
            raise ValueError("Assistant message lacks content")
        for part in item["content"]:
            if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise ValueError("Assistant output was refused or was not text")
            text.append(part["text"])
    if not text or not "".join(text).strip():
        raise ValueError("Assistant output was empty")
    return "".join(text)


def normalized_usage(raw):
    """Map observed tokens for existing analysis; never price subscription usage."""
    response = raw.get("response") or {}
    usage = response.get("usage") or {}
    result = {
        "billing_path": BILLING_PATH,
        "cash_cost_usd": 0.0,
        "responses_usage": deepcopy(usage),
    }
    mapping = {
        "input_tokens": "prompt_tokens",
        "output_tokens": "completion_tokens",
        "total_tokens": "total_tokens",
        "input_tokens_details": "prompt_tokens_details",
        "output_tokens_details": "completion_tokens_details",
    }
    for source, target in mapping.items():
        if source in usage:
            result[target] = deepcopy(usage[source])
    return result


def permanent_error(raw):
    """Whether this attempt requires a coordinator pause instead of a retry."""
    error = raw.get("error")
    error = error if isinstance(error, dict) else {}
    return (
        raw.get("http_status") in (400, 401, 403, 404, 422)
        or error.get("type") == "insufficient_quota"
        or error.get("code") in _PAUSE_CODES
    )
