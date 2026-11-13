import asyncio
import fcntl
import json
import subprocess
from contextlib import contextmanager

from .agents import Caller, PermanentAPIError, request_body
from .environment import Market
from .memory import ROOT, TOKEN_MEASURE, build_compressor, build_seller, digest, prompt_hash, tokens, visible_history
from .storage import BudgetStop


def git_commit():
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else "uncommitted"


def same_config(a,b):
    """A global budget amendment does not mutate the scientific run settings."""
    return {k:v for k,v in a.items() if k!='budget_usd'}=={k:v for k,v in b.items() if k!='budget_usd'}


def validate_config(c):
    if c["architecture"] not in ("bullet_memory", "paper_reference") or c["mode"] not in ("clear", "full", "compressed"):
        raise ValueError("Invalid architecture or memory mode")
    if c["H"] not in (0,1,5,20,100) or c["T"] < 1:
        raise ValueError("Invalid horizon or history window")
    if c["architecture"] == "paper_reference" and (c["H"] != 100 or c["mode"] != "full"):
        raise ValueError("Paper reference requires H=100/full")
    if c["provider"] not in ("mock", "openai") or not 1 <= c["max_attempts"] <= 3:
        raise ValueError("Invalid provider or retry limit")
    if c.get("shock"):
        s = c["shock"]
        if s["agent"] not in (0,1) or not 0 < s["factor"] <= 1 or not 1 <= s["t"] <= c["T"]:
            raise ValueError("Invalid shock")


def create_run(store, run, config):
    validate_config(config)
    store.add_run(run, config, git_commit(), prompt_hash())


async def run_one(store, caller, run, stop_event):
    c = store.config(run)
    validate_config(c)
    metadata = store.rows("SELECT * FROM runs WHERE id=?", (run,))[0]
    if metadata["prompt_hash"] != prompt_hash():
        store.status(run,"paused_error","Prompt files changed; restore recorded version")
        return
    store.status(run,"running")
    try:
        history = store.history(run)
        for t in range(len(history)+1, c["T"]+1):
            if (store.root/f'{run}.pause').exists():
                store.status(run,'paused_manual','Pause marker found; round boundary preserved')
                return
            if prompt_hash()!=metadata['prompt_hash']:
                raise ValueError('Prompt files changed during run; checkpoint preserved')
            if stop_event.is_set():
                store.status(run,"paused_access","Batch stopped after permanent API failure")
                return
            archives = [store.archive(run,i) for i in range(2)]
            histories = [visible_history(history,c["H"],i) for i in range(2)]

            async def prepare(i):
                archive = archives[i]
                if c["architecture"] == "paper_reference":
                    paper_state = history[-1]["actions"][i] if history else {"plans":"", "insights":""}
                    view = paper_state["plans"] + "\n" + paper_state["insights"]
                else:
                    paper_state = None
                    if c["mode"] == "clear" or not archive:
                        view = ""
                    elif c["mode"] == "full":
                        view = "\n".join(archive)
                    else:
                        result = await caller.call(run,t,i,"compressor",build_compressor(archive),c)
                        view = result["memory_bullet"]
                payload = {"text":view,"history_tokens":tokens(histories[i]),"memory_tokens":tokens(view),
                           "archive_entries":len(archive),"archive_tokens":tokens("\n".join(archive)),
                           "source_hash":digest(archive),"source_range":[1,len(archive)] if archive else [],
                           "prompt_hash":metadata["prompt_hash"],"resource_measure":TOKEN_MEASURE}
                store.view(run,t,i,payload)
                return build_seller(c,histories[i],view,paper_state)

            prompts = await asyncio.gather(*(prepare(i) for i in range(2)), return_exceptions=True)
            for p in prompts:
                if isinstance(p, BaseException):
                    raise p
            # Both immutable request texts exist before either seller starts.
            action_calls=[f'{run}:{t}:{i}:seller' for i in range(2)]
            if c.get('share_parent_first_actions') and t==metadata['checkpoint']+1:
                if not c.get('shock') or not metadata['parent']:
                    raise ValueError('Shared first actions require a shock branch and parent')
                actions=[]
                for i in range(2):
                    source_call=f"{metadata['parent']}:{t}:{i}:seller"
                    accepted=store.accepted(source_call,digest(request_body(c,prompts[i],'seller')))
                    if accepted is None:raise ValueError('Matching parent action unavailable')
                    actions.append(accepted);action_calls[i]=source_call
            else:
                actions = await asyncio.gather(*(caller.call(run,t,i,"seller",prompts[i],c) for i in range(2)), return_exceptions=True)
            for a in actions:
                if isinstance(a, BaseException):
                    raise a
            proposed = [a["price"] for a in actions]
            executed = proposed.copy()
            shock = c.get("shock")
            flags = [False,False]
            if shock and t == shock["t"]:
                executed[shock["agent"]] *= shock["factor"]
                flags[shock["agent"]] = True
            q, profits = Market().settle(executed)
            payload = {"t":t,"proposed_prices":proposed,"prices":executed,"quantities":q.tolist(),
                       "profits":profits.tolist(),"shock_flags":flags,"ceiling_exceeded":[p>4.51 for p in executed],
                       "actions":actions,"action_call_ids":action_calls}
            store.commit_round(run,payload,actions,c["architecture"])
            history.append(payload)
            if t % 25 == 0 or t == c["T"]:
                print(json.dumps({"run":run,"round":t,"spending":store.spending()}),flush=True)
        store.status(run,"completed")
    except BudgetStop as exc:
        store.status(run,"paused_budget",str(exc))
    except PermanentAPIError as exc:
        store.status(run,"paused_access",str(exc)); stop_event.set()
    except Exception as exc:
        store.status(run,"paused_error",f"{type(exc).__name__}: {exc}")


@contextmanager
def coordinator_lock(store):
    with (store.root / "coordinator.lock").open("w") as f:
        try:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another runner owns this database")
        try:
            yield
        finally:
            fcntl.flock(f,fcntl.LOCK_UN)


async def run_batch(store, run_ids, concurrency=8):
    for run in run_ids:
        c=store.config(run)
        if c['provider']=='openai' and not c.get('model_verified'):
            raise ValueError('Verify model ID, parameters and pricing before paid requests')
    with coordinator_lock(store):
        caller = Caller(store,concurrency=2*concurrency)
        caller.reconcile()
        stop = asyncio.Event()
        sem = asyncio.Semaphore(concurrency)
        async def limited(run):
            async with sem:
                await run_one(store,caller,run,stop)
        try:
            await asyncio.gather(*(limited(r) for r in run_ids))
        finally:
            await caller.close()
