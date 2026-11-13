import argparse
import asyncio
import json
import os
from pathlib import Path
import random

from .analysis import analyze
from .backup import restore, snapshot
from .environment import Market
from .memory import ROOT, prompt_hash
from .runner import create_run, git_commit, run_batch
from .storage import Store, atomic_json


def load_env():
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith('OPENAI_API_KEY='):
                os.environ.setdefault('OPENAI_API_KEY',line.split('=',1)[1].strip().strip('\"').strip("'"))


def load_config(path=None):
    return json.loads(Path(path or ROOT/'configs/base.json').read_text())


def plan_conditions(repeats,seed=498):
    rng=random.Random(seed);result=[]
    for rep in range(1,repeats+1):
        cells=[(h,m) for h in (0,1,5,20,100) for m in ('clear','full','compressed')]
        rng.shuffle(cells)
        result.extend(dict(repetition=rep,H=h,mode=m,id=f'formation-r{rep}-h{h}-{m}') for h,m in cells)
    return result


def main():
    parser=argparse.ArgumentParser(description='IE498 reproducible pricing experiments')
    parser.add_argument('--data',default=str(ROOT/'data/runs/live'))
    parser.add_argument('--config',default=str(ROOT/'configs/base.json'))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('benchmarks');sub.add_parser('status')
    p=sub.add_parser('plan');p.add_argument('--repeats',type=int,default=3)
    for name in ('mock','smoke','pilot','formation'):
        p=sub.add_parser(name);p.add_argument('--concurrency',type=int,default=8)
        if name=='formation':
            p.add_argument('--repeats',type=int,default=3);p.add_argument('--batch',type=int)
        if name=='mock':p.add_argument('--rounds',type=int,default=8)
    p=sub.add_parser('resume');p.add_argument('runs',nargs='*');p.add_argument('--concurrency',type=int,default=8)
    p=sub.add_parser('fork');p.add_argument('parent');p.add_argument('child');p.add_argument('--checkpoint',type=int,default=200)
    p.add_argument('--H',type=int,default=1);p.add_argument('--mode',choices=['clear','full','compressed'],default='clear')
    p.add_argument('--shock-agent',type=int,choices=[0,1]);p.add_argument('--run',action='store_true')
    p=sub.add_parser('analyze');p.add_argument('--out',default=str(ROOT/'reports/live'))
    p=sub.add_parser('snapshot');p.add_argument('--out',default=str(ROOT/'data/backups'))
    p=sub.add_parser('restore');p.add_argument('source');p.add_argument('destination')
    args=parser.parse_args();load_env()
    if args.command=='benchmarks':print(json.dumps(Market().benchmarks(),indent=2));return
    if args.command=='restore':print(restore(args.source,args.destination));return
    c=load_config(args.config)
    store=Store(args.data,c['budget_usd'])
    try:
        if args.command=='status':
            print(json.dumps({'spending':store.spending(),'runs':store.rows('SELECT id,status,error,parent,checkpoint FROM runs')},indent=2));return
        if args.command=='plan':
            cells=plan_conditions(args.repeats)
            pilot=store.rows("SELECT a.run_id,SUM(a.cost) cost,COUNT(*) calls FROM api_attempts a JOIN runs r ON a.run_id=r.id WHERE json_extract(r.config,'$.stage')='pilot' GROUP BY a.run_id")
            print(json.dumps({'model':c['model'],'budget':store.spending(),'seller_calls':9000*args.repeats,
                              'compressor_calls':2990*args.repeats,'pilot_costs':pilot,'conditions':cells},indent=2));return
        if args.command=='analyze':analyze(store,args.out);print(args.out);return
        if args.command=='snapshot':print(snapshot(store,args.out));return
        if args.command=='fork':
            child=store.config(args.parent);child.update(H=args.H,mode=args.mode,stage='maintenance',T=args.checkpoint+100)
            child.pop('shock',None)
            if args.shock_agent is not None:
                child.update(stage='shock',shock={'t':args.checkpoint+1,'agent':args.shock_agent,'factor':.9})
            store.fork(args.parent,args.child,args.checkpoint,child,git_commit(),prompt_hash())
            if args.run:asyncio.run(run_batch(store,[args.child]))
            print(args.child);return
        if args.command=='resume':
            ids=args.runs or [r['id'] for r in store.rows("SELECT id FROM runs WHERE status!='completed'")]
            asyncio.run(run_batch(store,ids,args.concurrency));return
        definitions=[]
        if args.command=='mock':
            c.update(provider='mock',stage='mock',T=args.rounds)
            definitions=[(f'mock-h{h}-{m}',dict(c,H=h,mode=m)) for h in (0,1,5,20,100) for m in ('clear','full','compressed')]
            definitions.append(('mock-paper',dict(c,H=100,mode='full',architecture='paper_reference')))
        elif args.command=='smoke':
            definitions=[('smoke-bullet',dict(c,stage='smoke',T=2,H=0,mode='compressed')),
                         ('smoke-paper',dict(c,stage='smoke',T=1,H=100,mode='full',architecture='paper_reference'))]
        elif args.command=='pilot':
            definitions=[('pilot-paper',dict(c,stage='pilot',architecture='paper_reference',H=100,mode='full')),
                         ('pilot-clear',dict(c,stage='pilot',H=100,mode='clear')),
                         ('pilot-compressed',dict(c,stage='pilot',H=100,mode='compressed'))]
            definitions += [(f'pilot-full-{i}',dict(c,stage='pilot',H=100,mode='full')) for i in (1,2,3)]
        elif args.command=='formation':
            freeze=ROOT/'configs/formation-freeze.json'
            if not freeze.exists():raise ValueError('Freeze model, pilot cost and repetition count in configs/formation-freeze.json first')
            frozen=json.loads(freeze.read_text())
            if frozen['config']!=c or frozen['prompt_hash']!=prompt_hash() or frozen['repeats']!=args.repeats:
                raise ValueError('Formation plan differs from frozen protocol')
            cells=plan_conditions(args.repeats)
            definitions=[(r['id'],dict(c,stage='formation',H=r['H'],mode=r['mode'],repetition=r['repetition']))
                         for r in cells if args.batch is None or r['repetition']==args.batch]
        existing={r['id']:json.loads(r['config']) for r in store.rows('SELECT id,config FROM runs')}
        for run,config in definitions:
            if run not in existing:create_run(store,run,config)
            elif existing[run]!=config:raise ValueError(f'Existing run {run} has different configuration')
        manifest={'stage':args.command,'code_commit':git_commit(),'prompt_hash':prompt_hash(),
                  'runs':[{'id':r,'config':v} for r,v in definitions]}
        atomic_json(ROOT/f'data/manifests/{args.command}.json',manifest)
        asyncio.run(run_batch(store,[r for r,_ in definitions],args.concurrency))
        print(json.dumps(store.spending()))
    finally:store.close()


if __name__=='__main__':main()
