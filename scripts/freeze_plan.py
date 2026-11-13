"""Freeze balanced replication count using complete pilots and actual usage only."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.cli import load_config
from ie498.memory import visible_history,prompt_hash
from ie498.storage import Store,atomic_json


def main():
    store=Store(ROOT/'data/runs/live',readonly=True)
    sources={'clear':'pilot-v11-clear','full':'pilot-v11-full-1','compressed':'pilot-v11-compressed'}
    for run in sources.values():
        status=store.rows('SELECT status FROM runs WHERE id=?',(run,))[0]['status']
        if status!='completed' or len(store.history(run))!=300:raise ValueError('Need complete 300-round memory pilots')
    base=load_config()
    clear=sources['clear'];hist=store.history(clear)
    ratios=[]
    for agent in (0,1):
        rows=store.rows("SELECT t,usage FROM api_attempts WHERE run_id=? AND agent=? AND purpose='seller' AND status='accepted' ORDER BY t",(clear,agent))
        baseline=json.loads(rows[0]['usage'])['prompt_tokens']
        for row in rows[-50:]:
            text=visible_history(hist[:row['t']-1],100,agent)
            ratios.append((json.loads(row['usage'])['prompt_tokens']-baseline)/len(text.encode()))
    # Lowest observed ratio subtracts less cost when projecting shorter histories.
    ratio=min(ratios);cells=[]
    for mode,run in sources.items():
        history=store.history(run)
        rows=store.rows("SELECT t,agent,purpose,usage FROM api_attempts WHERE run_id=? AND status='accepted'",(run,))
        for h in (0,1,5,20,100):
            inputs=outputs=0.0
            for row in rows:
                u=json.loads(row['usage']);inp=u['prompt_tokens']
                if row['purpose']=='seller':
                    full=visible_history(history[:row['t']-1],100,row['agent'])
                    short=visible_history(history[:row['t']-1],h,row['agent'])
                    inp-=max(0,len(full.encode())-len(short.encode()))*ratio
                inputs+=max(0,inp);outputs+=u['completion_tokens']
            cost=(inputs*base['prices']['input']+outputs*base['prices']['output'])/1e6
            cells.append({'H':h,'mode':mode,'projected_input_tokens':inputs,'projected_output_tokens':outputs,'projected_cost_usd':cost})
    batch=sum(c['projected_cost_usd'] for c in cells)
    balance=store.spending();paper_left=max(0,300-len(store.history('pilot-v11-paper')))
    paper_reserve=paper_left*.003
    available=balance['budget']-balance['spent']-balance['reserved']-paper_reserve-.1
    safety=1.04
    repeats=min(3,int(available/(batch*safety)))
    if repeats<1:raise ValueError(f'Balanced batch needs estimated ${batch:.4f}; available ${available:.4f}')
    result={'protocol_version':'1.1','config':base,'prompt_hash':prompt_hash(),'repeats':repeats,'desired_repeats':3,
            'estimated_batch_cost_usd':batch,'batch_cost_safety_factor':safety,'paper_cost_per_remaining_round':.003,
            'budget_at_freeze':balance,'pilot_sources':sources,'history_tokens_per_byte_projection':ratio,
            'projection_method':'Accepted pilot usage, uncached standard rates; shorter H removes history input estimated from minimum observed clear-pilot token/byte ratio; H100 memory/output lengths held fixed for all H; 4% batch margin plus separate paper reserve and $0.10 buffer.',
            'cells':cells,'sampling_decision_uses_behavior':False}
    atomic_json(ROOT/'configs/formation-freeze.json',result)
    print(json.dumps(result,indent=2));store.close()


if __name__=='__main__':main()
