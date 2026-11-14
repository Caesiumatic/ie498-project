"""Independent, resumable execution of the six-condition paper reconstruction.

Historical memory experiments are never opened by this module. Every actual
request and response is retained; only the same logical call can be recovered.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

import httpx

from . import subscription_transport
from .agents import cost_from_usage
from .memory import ROOT, digest
from .paper_replication import PaperCondition, PaperDecision, build_round_prompts, parse_decision, settle_round
from .runner import coordinator_lock, git_commit
from .storage import Store, atomic_json


PROTOCOL = "paper-core-six-conditions-v1"
DATA_ROOT = ROOT / "data/runs/paper_replication"
PROMPTS = ROOT / "experiments/paper_replication/prompts"
TRANSPORTS = ("api_key", "chatgpt_subscription")
PRICES = {"input": .1, "cached_input": .01, "cache_write": .125, "output": .5}


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    paths = [ROOT / "docs/sources/paper-v6.pdf", ROOT / "src/ie498/paper_replication.py",
             ROOT / "src/ie498/paper_execution.py", ROOT / "src/ie498/environment.py",
             ROOT / "src/ie498/storage.py", ROOT / "src/ie498/subscription_transport.py",
             ROOT / "src/ie498/subscription_auth.py"]
    paths += sorted(PROMPTS.glob("*.txt"))
    return {str(p.relative_to(ROOT)): file_hash(p) for p in paths}


def prompt_hash():
    return digest({p.name: p.read_text() for p in sorted(PROMPTS.glob("*.txt"))})


def request_body(prompt, transport):
    """Do not translate or silently discard a scientific sampling parameter."""
    if transport == "api_key":
        return {"model": "gpt-6-luna", "messages": [{"role": "user", "content": prompt}],
                "reasoning_effort": "none", "temperature": 1, "top_p": 1, "store": False}
    if transport == "chatgpt_subscription":
        return {"model": "gpt-6-luna", "input": [{"role": "user", "content": prompt}],
                "reasoning": {"effort": "none"}, "store": False, "stream": True}
    raise ValueError("Choose an explicitly authorized transport")


def plan(transport):
    if transport not in TRANSPORTS:
        raise ValueError("Unknown transport")
    configs = []
    for prefix in ("P1", "P2"):
        for alpha in (1., 3.2, 10.):
            label = f"{alpha:g}".replace(".", "p")
            configs.append({"id": f"paper-{prefix.lower()}-a{label}-r1", "config": {
                "protocol": PROTOCOL, "architecture": "paper_replication", "prefix": prefix,
                "alpha": alpha, "ceiling_policy": "footnote_18", "T": 300, "H": 100,
                "model": "gpt-6-luna", "reasoning_effort": "none", "transport": transport,
                "temperature": 1 if transport == "api_key" else None,
                "top_p": 1 if transport == "api_key" else None,
                "maximum_consecutive_malformed_outputs": 10,
                "transport_failures_before_pause": 3, "budget_usd": None,
            }})
    return {"protocol": PROTOCOL, "scope": "Section 3: P1/P2 x alpha 1,3.2,10, one run per cell",
            "transport": transport, "created_utc": datetime.now(timezone.utc).isoformat(),
            "code_commit": git_commit(), "source_hashes": source_hashes(), "prompt_hash": prompt_hash(),
            "runs": configs, "total_rounds": 1800, "successful_seller_calls": 3600,
            "request_concurrency": 6, "api_pricing_per_million_tokens": PRICES,
            "pricing_source": "https://developers.openai.com/api/docs/models/gpt-6-luna",
            "sampling_limitations": ([] if transport == "api_key" else [
                "Subscription interface prohibits explicit temperature and top_p.",
                "Server defaults are observed per response, not assumed equal to the paper."]),
            "reconstruction_limitations": [
                "No official implementation repository identified; exact original formatting/parser unspecified.",
                "Footnote 18 ceiling formula takes priority over the slightly inconsistent worked example.",
                "History uses str(round(value,2)); numerical actions are not rounded or clipped.",
                "Reasoning none is a model-substitution setting; the original GPT-4 had no such parameter.",
                "One trajectory per condition cannot reproduce the original between-run uncertainty.",
            ]}


def open_store(root):
    root = Path(root)
    path = root / "experiments.sqlite"
    if path.exists():
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
            row = db.execute("SELECT value FROM settings WHERE key='paper_protocol'").fetchone()
        if row is None or row[0] != PROTOCOL:
            raise ValueError("Refusing to open an unrelated experiment database")
    store = Store(root, budget=None)
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO settings VALUES('paper_protocol',?)", (PROTOCOL,))
    return store


def prepare(store, transport):
    manifest_path = store.root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["transport"] != transport or manifest["source_hashes"] != source_hashes():
            raise ValueError("Frozen transport or implementation changed; do not mix protocols")
        if manifest["prompt_hash"] != prompt_hash():
            raise ValueError("Frozen paper prompts changed")
    else:
        manifest = plan(transport)
        atomic_json(manifest_path, manifest)
    for row in manifest["runs"]:
        existing = store.rows("SELECT config,prompt_hash FROM runs WHERE id=?", (row["id"],))
        if not existing:
            store.add_run(row["id"], row["config"], manifest["code_commit"], manifest["prompt_hash"])
        elif json.loads(existing[0]["config"]) != row["config"] or existing[0]["prompt_hash"] != manifest["prompt_hash"]:
            raise ValueError("Saved run differs from frozen protocol")
    return manifest


class ExecutionPause(RuntimeError):
    pass


class PaperCaller:
    def __init__(self, store, manifest, *, api_key=None, auth=None, client=None):
        self.store, self.manifest = store, manifest
        self.transport = manifest["transport"]
        self.api_key, self.auth = api_key, auth
        self.stop = asyncio.Event()
        self.sem = asyncio.Semaphore(manifest["request_concurrency"])
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(180, connect=20),
            follow_redirects=False, limits=httpx.Limits(max_connections=6, max_keepalive_connections=6))

    def accept(self, row, raw):
        subscription = self.transport == "chatgpt_subscription"
        usage = subscription_transport.normalized_usage(raw) if subscription else raw.get("usage", {})
        path = f"raw/{row['id']}.json"
        cost = 0 if subscription or not usage else cost_from_usage(usage, PRICES)
        if raw.get("error"):
            reported_usage = raw.get("response", {}).get("usage") if subscription else raw.get("usage")
            usage = dict(usage, usage_unknown=not bool(reported_usage) and raw.get("http_status", 0) not in (400, 401, 403, 429))
            self.store.finish_attempt(row["id"], "transport_error", cost, usage, raw_path=path,
                                      error=json.dumps(raw["error"])[:1000])
            return None
        try:
            if subscription:
                reported = raw.get("response", {})
                if reported.get("model") != "gpt-6-luna":
                    raise ExecutionPause("Provider returned a different or unreported model")
                if reported.get("reasoning", {}).get("effort") != "none":
                    raise ExecutionPause("Provider did not confirm reasoning none")
                text = subscription_transport.extract_text(raw, "gpt-6-luna")
            else:
                if raw.get("model") != "gpt-6-luna":
                    raise ExecutionPause("Provider returned a different or unreported model")
                choice = raw["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("Output incomplete, truncated, or refused")
                text = choice["message"]["content"]
            decision = asdict(parse_decision(text))
        except ExecutionPause as exc:
            self.stop.set()
            self.store.finish_attempt(row["id"], "protocol_error", cost, usage, raw_path=path, error=str(exc))
            raise
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.store.finish_attempt(row["id"], "invalid", cost, usage, raw_path=path, error=str(exc))
            return None
        self.store.finish_attempt(row["id"], "accepted", cost, usage, decision, path)
        return decision

    def reconcile(self):
        for row in self.store.rows("SELECT * FROM api_attempts WHERE status='pending'"):
            path = self.store.root / f"raw/{row['id']}.json"
            if path.exists():
                self.accept(row, json.loads(path.read_text()))
            else:
                self.store.finish_attempt(row["id"], "transport_error", 0,
                    {"usage_unknown": True}, error="Interrupted before response was saved; usage unknown")

    async def send(self, body):
        if self.transport == "chatgpt_subscription":
            token = await self.auth.access_token()
            return await subscription_transport.send(self.client, body, token)
        try:
            response = await self.client.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
            try:
                raw = response.json()
            except ValueError:
                raw = {"error": {"type": "NonJSONResponse"}}
            if not isinstance(raw, dict):
                raw = {"error": {"type": "UnexpectedJSONResponse"}}
            raw["http_status"] = response.status_code
            raw["request_id"] = response.headers.get("x-request-id")
            raw["retry_after"] = response.headers.get("retry-after")
            if not response.is_success and not raw.get("error"):
                raw["error"] = {"type": "HTTPError", "code": response.status_code}
            return raw
        except httpx.HTTPError as exc:
            return {"error": {"type": type(exc).__name__, "message": "Transport failed; usage unknown"}}

    async def call(self, run, t, seller, prompt):
        body = request_body(prompt, self.transport)
        request_hash = digest(body)
        call_id = f"{run}:{t}:{seller}:seller"
        cached = self.store.accepted(call_id, request_hash)
        if cached is not None:
            return cached
        attempts = self.store.rows("SELECT * FROM api_attempts WHERE call_id=? ORDER BY attempt", (call_id,))
        if any(a["request_hash"] != request_hash for a in attempts):
            raise ExecutionPause("Request changed within a logical call")
        if any(a["status"] == "protocol_error" for a in attempts):
            raise ExecutionPause("Saved protocol error requires explicit review")
        malformed = sum(a["status"] == "invalid" for a in attempts)
        network_failures = sum(a["status"] == "transport_error" for a in attempts)
        number = len(attempts)
        while malformed < 10 and network_failures < 3:
            if self.stop.is_set():
                raise ExecutionPause("Coordinator paused after another request failed")
            async with self.sem:
                if self.stop.is_set():
                    raise ExecutionPause("Coordinator paused before request")
                number += 1
                attempt_id = f"{run}-{t:03d}-{seller}-{number:02d}"
                row = {"id": attempt_id, "call_id": call_id, "attempt": number,
                       "run_id": run, "t": t, "agent": seller, "purpose": "seller",
                       "request_hash": request_hash, "request_json": json.dumps(body, ensure_ascii=False),
                       "reserved": 0}
                atomic_json(self.store.root / f"requests/{attempt_id}.json", body)
                self.store.reserve(row)
                try:
                    raw = await self.send(body)
                except Exception:
                    self.stop.set()
                    raise ExecutionPause("Authorization or request failed before a response; checkpoint retained") from None
                raw["experiment_provenance"] = {"protocol": PROTOCOL, "transport": self.transport,
                    "logical_call_id": call_id, "request_hash": request_hash}
                atomic_json(self.store.root / f"raw/{attempt_id}.json", raw)
                accepted = self.accept(row, raw)
                if accepted is not None:
                    return accepted
            if raw.get("error"):
                network_failures += 1
                error = raw["error"]
                code = error.get("code") if isinstance(error, dict) else None
                kind = error.get("type") if isinstance(error, dict) else None
                status = raw.get("http_status", 0)
                permanent = (code in subscription_transport._PAUSE_CODES or kind in subscription_transport._PAUSE_CODES
                             or status in (400, 401, 403, 404))
                if permanent:
                    self.stop.set()
                    raise ExecutionPause(f"Provider rejected request: {code or kind or status}")
                try:
                    delay = min(60, max(1, float(raw.get("retry_after") or 2 ** network_failures)))
                except (ValueError, TypeError):
                    delay = 2 ** network_failures
                await asyncio.sleep(delay)
            else:
                malformed += 1
        raise ExecutionPause("Ten malformed outputs" if malformed >= 10 else "Three transport failures; retained for review")


def history_integrity(store, run):
    history = store.history(run)
    config = store.config(run)
    condition = PaperCondition(prefix=config["prefix"], alpha=config["alpha"], ceiling_policy=config["ceiling_policy"])
    if [r["t"] for r in history] != list(range(1, len(history) + 1)):
        raise ValueError("Saved periods are not consecutive")
    for n, r in enumerate(history):
        rebuilt = settle_round(condition, r["t"], [PaperDecision(**a) for a in r["actions"]])
        if any(rebuilt[k] != r[k] for k in ("prices", "quantities", "profits")):
            raise ValueError("Saved market settlement failed verification before resume")
        prompts = build_round_prompts(condition, history[:n])
        for seller, saved in enumerate(r["actions"]):
            body = request_body(prompts[seller], config["transport"])
            if store.accepted(f"{run}:{r['t']}:{seller}:seller", digest(body)) != saved:
                raise ValueError("Settled action differs from accepted response")
    return history


async def run_one(store, caller, item):
    run, config = item["id"], item["config"]
    condition = PaperCondition(prefix=config["prefix"], alpha=config["alpha"], ceiling_policy=config["ceiling_policy"])
    history = history_integrity(store, run)
    store.status(run, "running")
    try:
        for t in range(len(history) + 1, 301):
            if caller.stop.is_set() or (store.root / f"{run}.pause").exists():
                raise ExecutionPause("Paused at period boundary")
            if source_hashes() != caller.manifest["source_hashes"]:
                raise ExecutionPause("Source changed after protocol freeze")
            prompts = build_round_prompts(condition, history)
            for seller, prompt in enumerate(prompts):
                store.view(run, t, seller, {"prompt_sha256": digest(prompt), "visible_history_periods": min(100, t - 1)})
            answers = await asyncio.gather(*(caller.call(run, t, i, prompts[i]) for i in range(2)), return_exceptions=True)
            errors = [a for a in answers if isinstance(a, BaseException)]
            if errors:
                raise ExecutionPause(str(errors[0]))
            payload = settle_round(condition, t, [PaperDecision(**a) for a in answers])
            payload["action_call_ids"] = [f"{run}:{t}:{i}:seller" for i in range(2)]
            store.commit_round(run, payload, answers, "paper_replication")
            history.append(payload)
            if t == 1 or t % 10 == 0:
                print(json.dumps({"event": "period", "run": run, "completed": t}), flush=True)
        store.status(run, "completed")
    except ExecutionPause as exc:
        store.status(run, "paused", str(exc))
        print(json.dumps({"event": "paused", "run": run, "completed": len(history), "reason": str(exc)}), flush=True)
    except Exception:
        caller.stop.set()
        store.status(run, "paused", "Unexpected local error; inspect execution log")
        raise


def status(store):
    runs = store.rows("SELECT id,status,error FROM runs ORDER BY id")
    for row in runs:
        row["rounds"] = store.rows("SELECT count(*) n FROM rounds WHERE run_id=?", (row["id"],))[0]["n"]
    return {"protocol": PROTOCOL, "runs": runs, "rounds": sum(r["rounds"] for r in runs),
            "accepted_calls": store.rows("SELECT count(*) n FROM api_attempts WHERE status='accepted'")[0]["n"],
            "api_cash_cost_usd_recorded": store.spending()["spent"],
            "unknown_usage_attempts": store.rows("SELECT count(*) n FROM api_attempts WHERE usage LIKE '%\"usage_unknown\": true%'")[0]["n"]}


async def execute(store, manifest, *, api_key=None, auth=None):
    if manifest["transport"] == "api_key" and not api_key:
        raise ValueError("API key not configured; no subscription fallback")
    if manifest["transport"] == "chatgpt_subscription" and auth is None:
        raise ValueError("Subscription authentication not configured; no API billing fallback")
    caller = PaperCaller(store, manifest, api_key=api_key, auth=auth)
    try:
        caller.reconcile()
        pending = [x for x in manifest["runs"] if store.rows("SELECT status FROM runs WHERE id=?", (x["id"],))[0]["status"] != "completed"]
        # The first actual seller call completes before the rest launch, avoiding
        # a burst of identical permanent access rejections. It is reused only for
        # that same call in the first experimental period, never as a test sample.
        if auth is not None:
            await auth.access_token()
        if pending:
            first = pending[0]
            if not store.history(first["id"]):
                c = first["config"]
                condition = PaperCondition(prefix=c["prefix"], alpha=c["alpha"], ceiling_policy=c["ceiling_policy"])
                prompts = build_round_prompts(condition, [])
                try:
                    await caller.call(first["id"], 1, 0, prompts[0])
                except ExecutionPause as exc:
                    store.status(first["id"], "paused", str(exc))
                    raise
            await asyncio.gather(*(run_one(store, caller, item) for item in pending))
    finally:
        await caller.client.aclose()
        receipt = status(store)
        atomic_json(store.root / "status.json", receipt)
        print(json.dumps(receipt), flush=True)


def audit(store):
    manifest = json.loads((store.root / "manifest.json").read_text())
    if manifest["source_hashes"] != source_hashes():
        raise ValueError("Frozen sources do not match")
    checked = 0
    for item in manifest["runs"]:
        c = item["config"]
        condition = PaperCondition(prefix=c["prefix"], alpha=c["alpha"], ceiling_policy=c["ceiling_policy"])
        history = history_integrity(store, item["id"])
        for n, r in enumerate(history):
            prompts = build_round_prompts(condition, history[:n])
            rebuilt = settle_round(condition, n + 1, [PaperDecision(**a) for a in r["actions"]])
            if any(rebuilt[k] != r[k] for k in ("prices", "quantities", "profits")):
                raise ValueError("Saved settlement differs from market formula")
            for seller, prompt in enumerate(prompts):
                accepted = store.accepted(f"{item['id']}:{n+1}:{seller}:seller", digest(request_body(prompt, manifest["transport"])))
                if accepted != r["actions"][seller]:
                    raise ValueError("Historical input or action mismatch")
                checked += 1
    return {"passed": True, "checked_calls": checked, **status(store)}
