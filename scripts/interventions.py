"""Plan, then execute preregistered checkpoint-200 maintenance and price shocks."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import subprocess
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.analysis import metrics
from ie498.cli import load_env
from ie498.memory import prompt_hash
from ie498.runner import git_commit,run_batch,same_config
from ie498.storage import Store,atomic_json,remaining_budget


def plan(store,clear_h,compressed_h):
    candidates=[];definitions=[];reserved=0.0
    available=remaining_budget(store.spending())
    formation=store.rows("SELECT * FROM runs WHERE json_extract(config,'$.stage')='formation' AND status!='cancelled_user' ORDER BY id")
    if any(r['status'] not in ('completed','not_started_budget') for r in formation):
        raise ValueError('Complete or budget-close formation before planning interventions')
    for run in formation:
        c=json.loads(run['config'])
        if c['H']!=100 or c['mode']!='full':continue
        history=store.history(run['id'])
        result=metrics(history[150:200]) if len(history)>=200 else {}
        eligible=run['status']=='completed' and result.get('n_eval')==50 and result.get('effective_success',False)
        candidate={'parent':run['id'],'status':run['status'],'eligible':eligible,'window_metrics':result,'selected':False}
        candidates.append(candidate)
        if not eligible:continue
        continuation_cost=store.rows("SELECT COALESCE(SUM(cost),0) cost FROM api_attempts WHERE run_id=? AND t BETWEEN 201 AND 300",(run['id'],))[0]['cost']
        package_estimate=max(.3,1.25*(2*continuation_cost+.08))
        candidate['package_estimate_usd']=package_estimate
        if reserved+package_estimate>available-.10:
            candidate['not_selected_reason']='Budget reserve for a complete three-branch parent package';continue
        candidate['selected']=True;reserved+=package_estimate
        index=sum(x['selected'] for x in candidates)-1
        rep=c['repetition'];shock_agent=index%2
        choices=[(f'maint-r{rep}-clear-h{clear_h}','maintenance',clear_h,'clear',None),
                 (f'maint-r{rep}-compressed-h{compressed_h}','maintenance',compressed_h,'compressed',None),
                 (f'shock-r{rep}-a{shock_agent}','shock',100,'full',shock_agent)]
        for child,stage,h,mode,agent in choices:
            config=dict(c,T=300,H=h,mode=mode,stage=stage,budget_usd=store.spending()['budget'])
            if agent is not None:config.update(shock={'t':201,'agent':agent,'factor':.9},share_parent_first_actions=True)
            definitions.append({'id':child,'parent':run['id'],'checkpoint':200,'config':config,
                                'control':{'run':run['id'],'rounds':[201,300],'natural_continuation_reused':True}})
    return {'prompt_hash':prompt_hash(),'code_commit':git_commit(),'candidates':candidates,'runs':definitions,
            'branch_choices':{'clear_H':clear_h,'compressed_H':compressed_h},'reserved_estimate_usd':reserved,
            'balance_at_plan':store.spending(),'selection_order':'Ascending parent run ID, eligibility then budget only',
            'shock_assignment':'Alternate agent 0/1 among selected parents; share the prespecified first actions'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['plan','execute'])
    parser.add_argument('--clear-H',type=int,choices=[0,1,5,20,100],default=1)
    parser.add_argument('--compressed-H',type=int,choices=[0,1,5,20,100],default=5)
    args=parser.parse_args();load_env();store=Store(ROOT/'data/runs/live')
    path=ROOT/'configs/interventions-freeze.json'
    if args.command=='plan':
        if path.exists() and store.rows("SELECT id FROM runs WHERE json_extract(config,'$.stage') IN ('maintenance','shock')"):
            raise ValueError('Executed intervention plans are immutable; use a separately versioned plan')
        result=plan(store,args.clear_H,args.compressed_H);atomic_json(path,result)
        print(json.dumps(result,indent=2))
    else:
        dirty=subprocess.check_output(['git','status','--porcelain','--',str(path)],cwd=ROOT).decode()
        if dirty.strip():raise ValueError('Commit the concrete intervention plan before executing it')
        result=json.loads(path.read_text())
        if result['prompt_hash']!=prompt_hash():raise ValueError('Prompt version changed')
        for run in result['runs']:
            existing=store.rows('SELECT config FROM runs WHERE id=?',(run['id'],))
            if not existing:store.fork(run['parent'],run['id'],run['checkpoint'],run['config'],git_commit(),prompt_hash())
            elif not same_config(json.loads(existing[0]['config']),run['config']):raise ValueError('Existing branch configuration changed')
        atomic_json(ROOT/'data/manifests/interventions.json',result)
        asyncio.run(run_batch(store,[r['id'] for r in result['runs']],6))
        print(store.spending())
    store.close()


if __name__=='__main__':main()
