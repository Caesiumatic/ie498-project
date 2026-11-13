"""Replay saved prompts only to measure provider caching; excluded from behavior data."""
import asyncio
import json
from pathlib import Path
import sys
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.agents import Caller
from ie498.cli import load_config,load_env
from ie498.runner import create_run,coordinator_lock
from ie498.storage import Store


async def measure(store,mode,seller_only,offset):
    caller=Caller(store)
    caller.reconcile()
    try:
        for purpose,source in [('seller','pilot-v11-full-1'),('compressor','pilot-v11-compressed')]:
            if seller_only and purpose!='seller':continue
            run='cache-check-'+mode+'-'+purpose
            if offset:run+=f'-offset{offset}'
            config=dict(load_config(),stage='cache_calibration',cache_mode=mode,T=3)
            create_run(store,run,config)
            latest=store.rows('SELECT MAX(t) t FROM rounds WHERE run_id=?',(source,))[0]['t']
            latest-=offset
            rows=store.rows("SELECT request_json FROM api_attempts WHERE run_id=? AND agent=0 AND purpose=? AND status='accepted' AND t BETWEEN ? AND ? ORDER BY t",(source,purpose,latest-2,latest))
            if len(rows)!=3:raise ValueError('Need three consecutive saved prompts')
            for t,row in enumerate(rows,1):
                prompt=json.loads(row['request_json'])['messages'][0]['content']
                await caller.call(run,t,0,purpose,prompt,config)
            store.status(run,'completed')
            for row in store.rows('SELECT t,usage,cost FROM api_attempts WHERE run_id=?',(run,)):print(row,flush=True)
    finally:await caller.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',default='explicit_prefix');parser.add_argument('--seller-only',action='store_true');parser.add_argument('--offset',type=int,default=0);args=parser.parse_args()
    load_env();store=Store(ROOT/'data/runs/live')
    with coordinator_lock(store):asyncio.run(measure(store,args.mode,args.seller_only,args.offset))
    store.close()
