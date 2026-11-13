"""Replay saved prompts only to measure provider caching; excluded from behavior data."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.agents import Caller
from ie498.cli import load_config,load_env
from ie498.runner import create_run,coordinator_lock
from ie498.storage import Store


async def measure(store):
    caller=Caller(store)
    caller.reconcile()
    try:
        for purpose,source in [('seller','pilot-v11-full-1'),('compressor','pilot-v11-compressed')]:
            run='cache-check-'+purpose
            config=dict(load_config(),stage='cache_calibration',cache_mode='explicit_prefix',T=3)
            create_run(store,run,config)
            latest=store.rows('SELECT MAX(t) t FROM rounds WHERE run_id=?',(source,))[0]['t']
            rows=store.rows("SELECT request_json FROM api_attempts WHERE run_id=? AND agent=0 AND purpose=? AND status='accepted' AND t BETWEEN ? AND ? ORDER BY t",(source,purpose,latest-2,latest))
            if len(rows)!=3:raise ValueError('Need three consecutive saved prompts')
            for t,row in enumerate(rows,1):
                prompt=json.loads(row['request_json'])['messages'][0]['content']
                await caller.call(run,t,0,purpose,prompt,config)
            store.status(run,'completed')
            for row in store.rows('SELECT t,usage,cost FROM api_attempts WHERE run_id=?',(run,)):print(row,flush=True)
    finally:await caller.close()


if __name__=='__main__':
    load_env();store=Store(ROOT/'data/runs/live')
    with coordinator_lock(store):asyncio.run(measure(store))
    store.close()
