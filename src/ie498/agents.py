import asyncio
import json
import os
import random
import time
import re
import httpx

from .memory import digest, parse_output, tokens
from .storage import atomic_json


class PermanentAPIError(RuntimeError):
    pass


class RateLimiter:
    """Shared admission pacing under the observed 2M-token/minute project tier."""
    def __init__(self, tokens_per_second=30000, burst=200000):
        self.rate=tokens_per_second;self.burst=burst;self.credit=burst
        self.updated=time.monotonic();self.lock=asyncio.Lock()

    async def acquire(self, estimate):
        async with self.lock:
            now=time.monotonic()
            self.credit=min(self.burst,self.credit+(now-self.updated)*self.rate)
            delay=max(0,(estimate-self.credit)/self.rate)
            if delay:await asyncio.sleep(delay)
            self.credit=max(0,self.credit+delay*self.rate-estimate)
            self.updated=time.monotonic()


def request_body(config, prompt, purpose):
    paper = config["architecture"] == "paper_reference" and purpose == "seller"
    body = {"model": config["model"], "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": config.get('paper_output_limit',4096) if paper else config.get('output_limit',2048),
            "reasoning_effort": config.get('reasoning_effort','low'), "store": False, "service_tier":"default"}
    if config.get('temperature') is not None:
        body['temperature']=config['temperature']
    if config.get('cache_mode')=='off':
        body['prompt_cache_options']={'mode':'explicit','ttl':'30m'}
    if config.get('cache_mode') in ('explicit_prefix','explicit_blocks'):
        body['prompt_cache_options']={'mode':'explicit','ttl':'30m'}
        # Text concatenates exactly to the original independent user message.
        # Reuse only archive prefixes; never reuse sampled outputs or hidden reasoning.
        eligible=purpose=='compressor' or (config['architecture']=='bullet_memory' and config['mode']=='full')
        ends=[m.end() for m in re.finditer(r'(?m)^- [^\n]*',prompt)] if eligible else []
        marked=ends[-2:]
        if config['cache_mode']=='explicit_prefix':ends=marked
        if ends:
            parts=[];start=0
            for end in ends:
                part={'type':'text','text':prompt[start:end]}
                if end in marked:part['prompt_cache_breakpoint']={'mode':'explicit'}
                parts.append(part)
                start=end
            if start<len(prompt):parts.append({'type':'text','text':prompt[start:]})
            assert ''.join(p['text'] for p in parts)==prompt
            body['messages'][0]['content']=parts
    if not paper:
        # One sentence, <=60 whitespace-delimited words; decimal points remain legal.
        word = r"(?:[^\s.!?]|\.[0-9])+"
        props = {"memory_bullet": {"type": "string", "pattern": r"^- " + word + r"(?: " + word + r"){0,59}\.$"}}
        if purpose == "seller":
            props["price"] = {"type": "number"}
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "decision", "strict": True,
            "schema": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}}}
    return body


def cost_from_usage(usage, prices):
    inp = usage.get("prompt_tokens", 0)
    cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    writes = usage.get("prompt_tokens_details", {}).get("cache_write_tokens", 0)
    out = usage.get("completion_tokens", 0)
    input_scale=2 if inp>272000 else 1
    output_scale=1.5 if inp>272000 else 1
    return ((max(0,inp-cached-writes)*prices["input"] + cached*prices["cached_input"] +
             writes*prices.get('cache_write',prices['input']))*input_scale + out*prices["output"]*output_scale) / 1e6


class Caller:
    def __init__(self, store, concurrency=16):
        self.store = store
        self.sem = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=20), follow_redirects=False)
        self.not_before=0.0
        self.limiter=RateLimiter()

    async def close(self):
        await self.client.aclose()

    def accept_raw(self, row, raw, config):
        usage = raw.get("usage", {})
        cost = 0 if config["provider"] == "mock" else (cost_from_usage(usage, config["prices"]) if usage else row['reserved'])
        path = f"raw/{row['id']}.json"
        if "error" in raw:
            status_code = raw.get("http_status", 0)
            # Unknown server processing remains conservatively charged.
            uncertain = not status_code or status_code >= 500
            self.store.finish_attempt(row["id"], "uncertain" if uncertain else "failed", row["reserved"] if uncertain else (cost if usage else 0),
                                      usage, raw_path=path, error=json.dumps(raw["error"])[:1000])
            return None
        try:
            if raw["choices"][0].get("finish_reason") != "stop":
                raise ValueError("Model output was truncated or refused")
            parsed = parse_output(raw["choices"][0]["message"]["content"], row["purpose"], config["architecture"])
        except (ValueError, KeyError, TypeError) as exc:
            self.store.finish_attempt(row["id"], "invalid", cost, usage, raw_path=path, error=str(exc))
            return None
        self.store.finish_attempt(row["id"], "accepted", cost, usage, parsed, path)
        return parsed

    def reconcile(self):
        for row in self.store.rows("SELECT * FROM api_attempts WHERE status='pending'"):
            path = self.store.root / f"raw/{row['id']}.json"
            if path.exists():
                self.accept_raw(row, json.loads(path.read_text()), self.store.config(row["run_id"]))
            else:
                self.store.finish_attempt(row["id"], "uncertain", row["reserved"], error="Interrupted before response persisted")

    async def call(self, run, t, agent, purpose, prompt, config):
        call_id = f"{run}:{t}:{agent}:{purpose}"
        body = request_body(config, prompt, purpose)
        req_hash = digest(body)
        cached = self.store.accepted(call_id, req_hash)
        if cached is not None:
            return cached
        if tokens(prompt) + body["max_completion_tokens"] + 4096 > config["context_limit"]:
            raise ValueError("Context capacity exceeded; archive will not be truncated")
        attempts = self.store.rows("SELECT * FROM api_attempts WHERE call_id=? ORDER BY attempt", (call_id,))
        if any(r["request_hash"] != req_hash for r in attempts):
            raise ValueError("Request changed between attempts")
        for number in range(len(attempts)+1, config["max_attempts"]+1):
            attempt_id = call_id.replace(":", "_") + f"_a{number}"
            # UTF-8 bytes bound token count; overhead covers schema and chat framing.
            byte_bound=len(json.dumps(body).encode())+4096
            reserve = (byte_bound*max(config["prices"]["input"],config['prices'].get('cache_write',0))*(2 if byte_bound>272000 else 1) +
                       body["max_completion_tokens"]*config["prices"]["output"]*(1.5 if byte_bound>272000 else 1)) / 1e6
            if config["provider"] == "mock":
                reserve = 0
            row = dict(id=attempt_id, call_id=call_id, attempt=number, run_id=run,t=t,agent=agent,purpose=purpose,
                       request_hash=req_hash,request_json=json.dumps(body),reserved=reserve)
            prior=self.store.rows("SELECT request_json,usage FROM api_attempts WHERE run_id=? AND agent=? AND purpose=? AND status='accepted' ORDER BY t DESC LIMIT 1",(run,agent,purpose))
            rate_estimate=len(json.dumps(body).encode())*.35+body['max_completion_tokens']
            if prior:
                previous=json.loads(prior[0]['usage'] or '{}').get('prompt_tokens')
                if previous is not None:
                    # New bytes are conservatively one token each; unchanged content
                    # uses observed usage. This only paces requests, never bills them.
                    growth=max(0,len(row['request_json'].encode())-len(prior[0]['request_json'].encode()))
                    observed_output=json.loads(prior[0]['usage']).get('completion_tokens',256)
                    output_allowance=min(body['max_completion_tokens'],max(256,1.5*observed_output))
                    rate_estimate=previous+growth+256+output_allowance
            async with self.sem:
                if config['provider']=='openai':
                    await self.limiter.acquire(rate_estimate)
                if self.not_before>time.monotonic():
                    await asyncio.sleep(self.not_before-time.monotonic())
                self.store.reserve(row)
                atomic_json(self.store.root / f"requests/{attempt_id}.json", body)
                if config["provider"] == "mock":
                    raw = self.mock(call_id, body, config, purpose)
                else:
                    key = os.environ.get("OPENAI_API_KEY")
                    if not key:
                        self.store.finish_attempt(attempt_id,"failed",0,error="OPENAI_API_KEY missing")
                        raise PermanentAPIError("OPENAI_API_KEY missing")
                    try:
                        response = await self.client.post("https://api.openai.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {key}"}, json=body)
                        try:
                            raw = response.json()
                        except ValueError:
                            raw = {"error": {"message": "Non-JSON HTTP response", "status": response.status_code}}
                        raw["http_status"] = response.status_code
                        raw["request_id"] = response.headers.get("x-request-id")
                        raw['rate_limits']={k:v for k,v in response.headers.items() if k.startswith('x-ratelimit-')}
                        if response.status_code==429:
                            try:delay=float(response.headers.get('retry-after','60'))
                            except ValueError:delay=60
                            self.not_before=max(self.not_before,time.monotonic()+max(1,delay))
                    except httpx.HTTPError as exc:
                        raw = {"error": {"type": type(exc).__name__, "message": "Transport failure; billing uncertain"}}
                atomic_json(self.store.root / f"raw/{attempt_id}.json", raw)
                result = self.accept_raw(row, raw, config)
            if result is not None:
                return result
            code = raw.get("error", {}).get("code") if isinstance(raw.get("error"), dict) else None
            if raw.get("http_status") in (400,401,403,404) or code in ("insufficient_quota", "billing_hard_limit_reached"):
                raise PermanentAPIError(f"API HTTP {raw.get('http_status')}: {code or 'request rejected'}")
            if number < config["max_attempts"]:
                await asyncio.sleep(min(2**number, 8))
        raise RuntimeError(f"Exhausted {config['max_attempts']} attempts for {call_id}")

    @staticmethod
    def mock(call_id, body, config, purpose):
        rng = random.Random(int(digest(call_id)[:16],16))
        price = 1.75 + rng.uniform(-.04,.04)
        bullet = f"- I will test a price of {price:.3f} to learn about profitability."
        if purpose == "compressor":
            text = json.dumps({"memory_bullet": "- I plan to test prices around 1.75 to learn about profitability."})
        elif config["architecture"] == "paper_reference":
            text = f"My observations and thoughts:\nI will explore.\nNew content for PLANS.txt:\nTest a profitable price.\nNew content for INSIGHTS.txt:\nDemand is uncertain.\nMy chosen price:\n{price}"
        else:
            text = json.dumps({"memory_bullet": bullet, "price": price})
        return {"id": f"mock-{call_id}", "model": "mock", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": tokens(json.dumps(body)), "completion_tokens": tokens(text)}}
