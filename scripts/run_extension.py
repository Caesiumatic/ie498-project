"""Run the frozen five-repeat extension with independent runs overlapped safely."""
import asyncio
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.agents import Caller
from ie498.backup import snapshot
from ie498.cli import load_env
from ie498.memory import prompt_hash
from ie498.runner import coordinator_lock,create_run,git_commit,run_one,same_config
from ie498.storage import Store,atomic_json


def prepare(store,plan):
    if prompt_hash()!=plan['prompt_hash']:
        raise ValueError('Frozen prompts changed')
    # Validate every run before changing statuses or making any paid call.
    for row in plan['runs']:
        existing=store.rows('SELECT * FROM runs WHERE id=?',(row['id'],))
        if existing:
            old=existing[0]
            if not same_config(json.loads(old['config']),row['config']) or old['prompt_hash']!=plan['prompt_hash']:
                raise ValueError(f"Existing run differs: {row['id']}")
            if old['status']=='cancelled_user':
                attempts=store.rows('SELECT COUNT(*) n FROM api_attempts WHERE run_id=?',(row['id'],))[0]['n']
                if attempts or store.history(row['id']):
                    raise ValueError('Only unstarted canceled plans may be reactivated')
    for row in plan['runs']:
        existing=store.rows('SELECT status FROM runs WHERE id=?',(row['id'],))
        if not existing:create_run(store,row['id'],row['config'])
        elif existing[0]['status']=='cancelled_user':
            store.status(row['id'],'planned','Reactivated by frozen five-repeat user amendment')


async def run_pending(store, caller, pending, stop, first_run=None):
    if first_run is not None:
        if first_run not in pending:
            raise ValueError('The first run must be an unfinished frozen run')
        await run_one(store,caller,first_run,stop)
    if not stop.is_set():
        await asyncio.gather(*(run_one(store,caller,run,stop) for run in pending if run!=first_run))


async def execute(store,plan, *, transport='openai_chat_completions', auth_file=None, resume_paused=False, first_run=None):
    dirty=subprocess.check_output(['git','status','--porcelain','--','src','prompts','configs','scripts'],cwd=ROOT).decode()
    if dirty.strip():raise ValueError('Commit implementation and frozen plan before paid calls')
    subscription_auth=None
    if transport=='chatgpt_subscription_responses':
        from ie498.subscription_auth import SubscriptionAuth
        subscription_auth=SubscriptionAuth(auth_file or ROOT/'data/auth/chatgpt-plan.json')
        # Token readiness only: no balance/usage/entitlement query and no sample inference.
        # Complete official sign-in before changing any run or pause-marker state.
        await subscription_auth.access_token()
    prepare(store,plan)
    completed={r['id'] for r in store.rows("SELECT id FROM runs WHERE status='completed'")}
    pending=[r['id'] for r in plan['runs'] if r['id'] not in completed]
    if first_run is not None and first_run not in pending:
        raise ValueError('The first run must be an unfinished frozen run')
    caller=Caller(store,concurrency=plan['request_concurrency'],transport=transport,subscription_auth=subscription_auth)
    caller.reconcile();stop=asyncio.Event()
    checkpoints={run:len(store.history(run)) for run in pending}
    remaining=sum(store.config(run)['T']-checkpoint for run,checkpoint in checkpoints.items())
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    start_path=ROOT/'data/manifests'/f'extension-resume-{stamp}.json'
    atomic_json(start_path,{
        'code_commit':git_commit(),'prompt_hash':prompt_hash(),'pending_runs':pending,
        'checkpoints':checkpoints,'remaining_rounds':remaining,'transport':transport,
        'api_ledger':store.spending(),'equivalence_experiment':False,
        'authorization':'User requested same-model continuation via official ChatGPT subscription authorization',
        'resume_paused':resume_paused,'first_run':first_run})
    if resume_paused:
        for run in pending:
            (store.root/f'{run}.pause').unlink(missing_ok=True)
    print(json.dumps({'event':'extension_start','transport':transport,'remaining_rounds':remaining,
                      'pending_runs':pending,'spending':store.spending()}),flush=True)
    try:
        await run_pending(store,caller,pending,stop,first_run)
    finally:
        await caller.close()
    ids={r['id'] for r in plan['runs']}
    rows=[r for r in store.rows('SELECT id,status,error FROM runs') if r['id'] in ids]
    path=snapshot(store,ROOT/'data/backups/batches')
    result={'runs':rows,'snapshot':str(path),'spending':store.spending(),'code_commit':git_commit(),
            'transport':transport,'resume_manifest':str(start_path.relative_to(ROOT)),
            'all_completed':all(r['status']=='completed' for r in rows)}
    atomic_json(ROOT/'data/manifests/extension-results.json',result)
    print(json.dumps(result),flush=True)
    if not result['all_completed']:raise RuntimeError('Extension paused; inspect per-run status before resuming')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport',choices=('openai_chat_completions','chatgpt_subscription_responses'),default='openai_chat_completions')
    parser.add_argument('--auth-file',type=Path,default=ROOT/'data/auth/chatgpt-plan.json')
    parser.add_argument('--resume-paused',action='store_true',help='Remove pause markers only after successful transport authorization')
    parser.add_argument('--first-run',help='Finish this actual pending run before launching the others; permanent access failure stops before they start')
    args=parser.parse_args()
    if args.transport=='openai_chat_completions':load_env()
    plan=json.loads((ROOT/'configs/extension-freeze.json').read_text())
    store=Store(ROOT/'data/runs/live')
    try:
        with coordinator_lock(store):asyncio.run(execute(store,plan,transport=args.transport,
            auth_file=args.auth_file,resume_paused=args.resume_paused,first_run=args.first_run))
    finally:store.close()
