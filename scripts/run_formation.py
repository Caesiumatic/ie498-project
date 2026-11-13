"""Run preregistered balanced batches and the unfinished paper pilot together."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.agents import Caller
from ie498.backup import snapshot
from ie498.cli import load_env,load_config,plan_conditions
from ie498.memory import prompt_hash
from ie498.runner import create_run,coordinator_lock,run_one,git_commit
from ie498.storage import Store,atomic_json


async def execute(store,freeze):
    config=load_config()
    if config!=freeze['config'] or prompt_hash()!=freeze['prompt_hash']:
        raise ValueError('Frozen configuration or prompts changed')
    dirty=subprocess.check_output(['git','status','--porcelain','--','src','prompts','configs','scripts'],cwd=ROOT).decode()
    if dirty.strip():raise ValueError('Commit implementation and frozen plan before formal runs')
    caller=Caller(store,concurrency=24);caller.reconcile();stop=asyncio.Event()
    definitions=plan_conditions(freeze['repeats'])
    for row in definitions:
        c=dict(config,stage='formation',H=row['H'],mode=row['mode'],repetition=row['repetition'])
        existing=store.rows('SELECT config FROM runs WHERE id=?',(row['id'],))
        if not existing:create_run(store,row['id'],c)
        elif json.loads(existing[0]['config'])!=c:raise ValueError('Existing run differs from plan')
    atomic_json(ROOT/'data/manifests/formation.json',dict(freeze,code_commit=git_commit(),runs=definitions))
    paper='pilot-v11-paper'
    paper_task=asyncio.create_task(run_one(store,caller,paper,stop))
    batch_estimate=freeze['estimated_batch_cost_usd']
    try:
        for rep in range(1,freeze['repeats']+1):
            ids=[r['id'] for r in definitions if r['repetition']==rep]
            statuses=store.rows('SELECT id,status FROM runs')
            completed={r['id'] for r in statuses if r['status']=='completed'}
            if set(ids)<=completed:continue
            balance=store.spending()
            paper_left=max(0,300-len(store.history(paper)))
            protected=paper_left*freeze['paper_cost_per_remaining_round']
            needed=batch_estimate*freeze['batch_cost_safety_factor']+protected
            if balance['budget']-balance['spent']-balance['reserved']<needed:
                for row in definitions:
                    if row['repetition']>=rep and row['id'] not in completed:
                        store.status(row['id'],'not_started_budget','Whole balanced batch withheld by preregistered cost guard')
                print(json.dumps({'event':'balanced_budget_stop','next_batch':rep,'needed':needed,'balance':balance}),flush=True)
                break
            print(json.dumps({'event':'batch_start','batch':rep,'balance':balance}),flush=True)
            await asyncio.gather(*(run_one(store,caller,run,stop) for run in ids))
            batch_rows=[r for r in store.rows('SELECT id,status FROM runs') if r['id'] in ids]
            cost=sum(store.rows('SELECT COALESCE(SUM(cost),0) cost FROM api_attempts WHERE run_id=?',(run,))[0]['cost'] for run in ids)
            batch_estimate=max(batch_estimate,cost)
            path=snapshot(store,ROOT/'data/backups/batches')
            atomic_json(ROOT/f'data/manifests/batch-{rep}-results.json',{'runs':batch_rows,'cost_usd':cost,'snapshot':str(path),'code_commit':git_commit()})
            print(json.dumps({'event':'batch_complete','batch':rep,'cost':cost,'statuses':batch_rows}),flush=True)
            if any(r['status']!='completed' for r in batch_rows):break
        await paper_task
    finally:
        if not paper_task.done():
            paper_task.cancel()
            await asyncio.gather(paper_task,return_exceptions=True)
        await caller.close()


if __name__=='__main__':
    load_env();freeze=json.loads((ROOT/'configs/formation-freeze.json').read_text())
    store=Store(ROOT/'data/runs/live')
    with coordinator_lock(store):asyncio.run(execute(store,freeze))
    store.close()
