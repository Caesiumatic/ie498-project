"""Offline execution/recovery scenarios; all model transport is fake."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json

import httpx
import pytest

from ie498 import paper_execution as execution
from ie498.memory import digest
from ie498.paper_replication import PaperCondition, PaperDecision, build_round_prompts, settle_round
from ie498.storage import Store, atomic_json


def decision_text(price=1.8, plans="Retain this plan", insights="Retain this insight"):
    return ("My observations and thoughts:\nReview previous outcomes.\n"
            f"New content for PLANS.txt:\n{plans}\n"
            f"New content for INSIGHTS.txt:\n{insights}\n"
            f"My chosen price:\nMy chosen price is ${price}.")


def chat_response(text=None, *, model="gpt-6-luna"):
    return {"model": model, "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": decision_text() if text is None else text}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}}


def subscription_event(text=None, *, model="gpt-6-luna", reasoning="none"):
    response = {"status": "completed", "reasoning": {"effort": reasoning},
                "temperature": 1.0, "top_p": 0.98,
                "output": [{"type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": text or decision_text()}]}],
                "usage": {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50}}
    if model is not None:
        response["model"] = model
    return {"type": "response.completed", "response": response}


class FakeAuth:
    async def access_token(self):
        return "test-only-oauth-token"


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Freeze deterministic provenance without referring to mutable work-in-progress source files.
    monkeypatch.setattr(execution, "source_hashes", lambda: {"test-source": "frozen"})
    monkeypatch.setattr(execution, "prompt_hash", lambda: "test-prompt-fingerprint")
    monkeypatch.setattr(execution, "git_commit", lambda: "test-commit")
    result = execution.open_store(tmp_path / "new-paper-experiment")
    yield result
    result.close()


def prepared(store, transport="api_key"):
    manifest = execution.prepare(store, transport)
    return manifest, manifest["runs"][0]


def caller_with_handler(store, manifest, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return execution.PaperCaller(store, manifest, api_key="test-only-api-key", auth=FakeAuth(), client=client)


def test_api_request_preserves_single_prompt_and_records_actual_wire(store):
    manifest, item = prepared(store)
    sent = []

    async def handler(request):
        sent.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-only-api-key"
        return httpx.Response(200, json=chat_response())

    async def scenario():
        caller = caller_with_handler(store, manifest, handler)
        try:
            answer = await caller.call(item["id"], 1, 0, "Exact prompt\n  preserve spacing.\n")
            assert answer["price"] == 1.8
        finally:
            await caller.client.aclose()

    asyncio.run(scenario())
    assert len(sent) == 1
    body = sent[0]
    assert body["messages"] == [{"role": "user", "content": "Exact prompt\n  preserve spacing.\n"}]
    assert body["reasoning_effort"] == "none" and body["temperature"] == body["top_p"] == 1
    assert set(body) == {"model", "messages", "reasoning_effort", "temperature", "top_p", "store"}
    attempt = store.rows("SELECT * FROM api_attempts")[0]
    assert json.loads(attempt["request_json"]) == body
    assert json.loads((store.root / "requests" / (attempt["id"] + ".json")).read_text()) == body
    assert attempt["status"] == "accepted" and attempt["cost"] > 0
    for path in (store.root / "raw").glob("*.json"):
        assert "test-only-api-key" not in path.read_text()


def test_subscription_omits_unsupported_controls_and_same_call_resume_is_free(store):
    manifest, item = prepared(store, "chatgpt_subscription")
    sent = []

    async def handler(request):
        sent.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-only-oauth-token"
        return httpx.Response(200, text="data: " + json.dumps(subscription_event()) + "\n\n")

    async def scenario():
        caller = caller_with_handler(store, manifest, handler)
        try:
            first = await caller.call(item["id"], 1, 0, "One independent user prompt")
            recovered = await caller.call(item["id"], 1, 0, "One independent user prompt")
            assert first == recovered
            # Identical text at another logical call must still be sampled.
            await caller.call(item["id"], 1, 1, "One independent user prompt")
        finally:
            await caller.client.aclose()

    asyncio.run(scenario())
    assert len(sent) == 2
    assert sent[0] == {"model": "gpt-6-luna", "input": [{"role": "user", "content": "One independent user prompt"}],
                       "reasoning": {"effort": "none"}, "store": False, "stream": True}
    assert store.spending()["spent"] == 0
    attempt = store.rows("SELECT * FROM api_attempts ORDER BY id")[0]
    raw = json.loads((store.root / attempt["raw_path"]).read_text())
    assert raw["response"]["temperature"] == 1 and raw["response"]["top_p"] == .98
    assert json.loads(attempt["usage"])["billing_path"] == "chatgpt_subscription"
    assert "test-only-oauth-token" not in (store.root / attempt["raw_path"]).read_text()


def test_ten_malformed_outputs_stop_without_eleventh_attempt_even_on_resume(store, monkeypatch):
    manifest, item = prepared(store)
    sent = []

    async def no_delay(_):
        return None

    monkeypatch.setattr(execution.asyncio, "sleep", no_delay)

    async def handler(request):
        sent.append(json.loads(request.content))
        # Two transient HTTP failures do not consume the ten malformed-output allowance.
        if len(sent) in (3, 7):
            return httpx.Response(503, json={"error": {"type": "server_error"}})
        return httpx.Response(200, json=chat_response("malformed model output"))

    async def scenario():
        for _ in range(2):
            caller = caller_with_handler(store, manifest, handler)
            try:
                with pytest.raises(execution.ExecutionPause, match="Ten malformed"):
                    await caller.call(item["id"], 1, 0, "unchanged request")
            finally:
                await caller.client.aclose()

    asyncio.run(scenario())
    assert len(sent) == 12
    assert all(body == sent[0] for body in sent)
    statuses = [x["status"] for x in store.rows("SELECT status FROM api_attempts")]
    assert statuses.count("invalid") == 10 and statuses.count("transport_error") == 2
    assert store.history(item["id"]) == []


def test_valid_tenth_response_is_accepted_and_not_retried(store):
    manifest, item = prepared(store)
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json=chat_response("malformed" if count < 10 else decision_text(2.1)))

    async def scenario():
        caller = caller_with_handler(store, manifest, handler)
        try:
            assert (await caller.call(item["id"], 1, 0, "fixed"))["price"] == 2.1
        finally:
            await caller.client.aclose()

    asyncio.run(scenario())
    assert count == 10
    assert len(store.rows("SELECT * FROM api_attempts WHERE status='accepted'")) == 1


def test_partial_round_retains_first_seller_and_commits_only_after_both_accept(store):
    manifest, item = prepared(store)
    first_calls = []

    async def first_handler(request):
        first_calls.append(json.loads(request.content))
        if len(first_calls) == 1:
            return httpx.Response(200, json=chat_response(decision_text(1.81, plans="Original first seller")))
        return httpx.Response(401, json={"error": {"type": "invalid_api_key"}})

    async def first_attempt():
        caller = caller_with_handler(store, manifest, first_handler)
        try:
            await execution.run_one(store, caller, item)
        finally:
            await caller.client.aclose()

    asyncio.run(first_attempt())
    assert store.history(item["id"]) == []
    assert len(store.rows("SELECT * FROM api_attempts WHERE status='accepted'")) == 1
    assert first_calls[0]["messages"] == first_calls[1]["messages"]
    resumed_calls = []

    async def resume():
        async def handler(request):
            resumed_calls.append(json.loads(request.content))
            caller.stop.set()  # Stop at the next period boundary after completing this actual period.
            return httpx.Response(200, json=chat_response(decision_text(2.21, plans="Second seller")))

        caller = caller_with_handler(store, manifest, handler)
        try:
            await execution.run_one(store, caller, item)
        finally:
            await caller.client.aclose()

    asyncio.run(resume())
    assert len(resumed_calls) == 1
    history = store.history(item["id"])
    assert len(history) == 1 and history[0]["prices"] == [1.81, 2.21]
    assert history[0]["actions"][0]["plans"] == "Original first seller"
    assert len(store.rows("SELECT * FROM api_attempts WHERE status='accepted'")) == 2
    assert store.rows("SELECT * FROM memory_entries") == []
    assert execution.audit(store)["checked_calls"] == 2


def test_corrupted_raw_response_cannot_be_reused_or_resampled(store):
    manifest, item = prepared(store)
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json=chat_response())

    async def scenario():
        caller = caller_with_handler(store, manifest, handler)
        try:
            await caller.call(item["id"], 1, 0, "fixed")
            row = store.rows("SELECT raw_path FROM api_attempts WHERE status='accepted'")[0]
            path = store.root / row["raw_path"]
            path.write_text(path.read_text() + " ")
            with pytest.raises(ValueError, match="integrity"):
                await caller.call(item["id"], 1, 0, "fixed")
        finally:
            await caller.client.aclose()

    asyncio.run(scenario())
    assert count == 1


def test_changed_settlement_is_rejected_before_resumed_inference(store):
    manifest, item = prepared(store)
    condition = PaperCondition(prefix="P1", alpha=1, ceiling_policy="footnote_18")
    prompts = build_round_prompts(condition, [])
    requests = 0

    async def handler(request):
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=chat_response())

    async def scenario():
        caller = caller_with_handler(store, manifest, handler)
        try:
            answers = [await caller.call(item["id"], 1, i, prompts[i]) for i in range(2)]
            payload = settle_round(condition, 1, [PaperDecision(**a) for a in answers])
            payload["action_call_ids"] = [f"{item['id']}:1:{i}:seller" for i in range(2)]
            store.commit_round(item["id"], payload, answers, "paper_replication")
            corrupted = deepcopy(payload)
            corrupted["profits"][0] += 5
            with store.db:
                store.db.execute("UPDATE rounds SET payload=? WHERE run_id=? AND t=1", (json.dumps(corrupted), item["id"]))
            with pytest.raises(ValueError, match="(?i)(settlement|market|profit)"):
                await execution.run_one(store, caller, item)
        finally:
            await caller.client.aclose()

    asyncio.run(scenario())
    assert requests == 2


@pytest.mark.parametrize("model,reasoning", [(None, "none"), ("wrong-model", "none"), ("gpt-6-luna", "low")])
def test_subscription_model_or_reasoning_mismatch_pauses_without_format_retry(store, model, reasoning):
    manifest, item = prepared(store, "chatgpt_subscription")
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(200, text="data: " + json.dumps(subscription_event(model=model, reasoning=reasoning)) + "\n\n")

    async def scenario():
        caller = caller_with_handler(store, manifest, handler)
        try:
            with pytest.raises(execution.ExecutionPause):
                await caller.call(item["id"], 1, 0, "fixed")
            assert caller.stop.is_set()
        finally:
            await caller.client.aclose()

    asyncio.run(scenario())
    assert count == 1
    assert store.rows("SELECT status FROM api_attempts") == [{"status": "protocol_error"}]


def test_pending_saved_response_is_reconciled_without_new_request(store):
    manifest, item = prepared(store)
    body = execution.request_body("fixed", "api_key")
    row = {"id": "test-interrupted", "call_id": f"{item['id']}:1:0:seller", "attempt": 1,
           "run_id": item["id"], "t": 1, "agent": 0, "purpose": "seller", "request_hash": digest(body),
           "request_json": json.dumps(body), "reserved": 0}
    store.reserve(row)
    atomic_json(store.root / "raw/test-interrupted.json", chat_response())

    async def handler(request):
        pytest.fail("A saved completed response must not be requested again")

    async def scenario():
        caller = caller_with_handler(store, manifest, handler)
        try:
            caller.reconcile()
            assert (await caller.call(item["id"], 1, 0, "fixed"))["price"] == 1.8
        finally:
            await caller.client.aclose()

    asyncio.run(scenario())
    assert store.rows("SELECT status FROM api_attempts") == [{"status": "accepted"}]


def test_existing_experiment_database_is_rejected_without_mutation(tmp_path):
    root = tmp_path / "historical"
    old = Store(root, budget=15)
    old.add_run("original", {"T": 300}, "old-commit", "old-prompts")
    old.close()
    before = (root / "experiments.sqlite").read_bytes()
    with pytest.raises(ValueError, match="unrelated"):
        execution.open_store(root)
    assert (root / "experiments.sqlite").read_bytes() == before


def test_prepare_refuses_transport_source_or_saved_configuration_changes(store, monkeypatch):
    manifest, item = prepared(store)
    assert len(manifest["runs"]) == 6 and manifest["total_rounds"] == 1800
    with pytest.raises(ValueError, match="Frozen"):
        execution.prepare(store, "chatgpt_subscription")
    monkeypatch.setattr(execution, "source_hashes", lambda: {"test-source": "modified"})
    with pytest.raises(ValueError, match="Frozen"):
        execution.prepare(store, "api_key")
    monkeypatch.setattr(execution, "source_hashes", lambda: {"test-source": "frozen"})
    altered = deepcopy(item["config"])
    altered["alpha"] = 3.2
    with store.db:
        store.db.execute("UPDATE runs SET config=? WHERE id=?", (json.dumps(altered), item["id"]))
    with pytest.raises(ValueError, match="Saved run"):
        execution.prepare(store, "api_key")
