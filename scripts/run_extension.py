"""Run the frozen five-repeat extension with independent runs overlapped safely."""
import asyncio
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


async def execute(store,plan):
    dirty=subprocess.check_output(['git','status','--porcelain','--','src','prompts','configs','scripts'],cwd=ROOT).decode()
    if dirty.strip():raise ValueError('Commit implementation and frozen plan before paid calls')
    prepare(store,plan)
    caller=Caller(store,concurrency=plan['request_concurrency'])
    caller.reconcile();stop=asyncio.Event()
    completed={r['id'] for r in store.rows("SELECT id FROM runs WHERE status='completed'")}
    pending=[r['id'] for r in plan['runs'] if r['id'] not in completed]
    atomic_json(ROOT/'data/manifests/extension-start.json',{
        'plan':plan,'code_commit':git_commit(),'pending_runs':pending,'balance':store.spending()})
    print(json.dumps({'event':'extension_start','pending_runs':pending,'spending':store.spending()}),flush=True)
    try:
        await asyncio.gather(*(run_one(store,caller,run,stop) for run in pending))
    finally:
        await caller.close()
    ids={r['id'] for r in plan['runs']}
    rows=[r for r in store.rows('SELECT id,status,error FROM runs') if r['id'] in ids]
    path=snapshot(store,ROOT/'data/backups/batches')
    result={'runs':rows,'snapshot':str(path),'spending':store.spending(),'code_commit':git_commit(),
            'all_completed':all(r['status']=='completed' for r in rows)}
    atomic_json(ROOT/'data/manifests/extension-results.json',result)
    print(json.dumps(result),flush=True)
    if not result['all_completed']:raise RuntimeError('Extension paused; inspect per-run status before resuming')


if __name__=='__main__':
    load_env()
    plan=json.loads((ROOT/'configs/extension-freeze.json').read_text())
    store=Store(ROOT/'data/runs/live')
    try:
        with coordinator_lock(store):asyncio.run(execute(store,plan))
    finally:store.close()
