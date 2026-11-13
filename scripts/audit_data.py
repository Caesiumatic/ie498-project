"""Validate stored scientific data, request provenance, raw hashes and cost ledger."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.agents import request_body,cost_from_usage
from ie498.environment import Market
from ie498.memory import build_compressor,build_seller,digest,prompt_hash,visible_history
from ie498.storage import Store,atomic_json


def main():
    store=Store(ROOT/'data/runs/live',readonly=True)
    counts=dict(runs=0,rounds=0,memory_entries=0,attempts=0,accepted_attempts=0,verified_seller_inputs=0,verified_compressor_inputs=0)
    configs={}
    for run in store.rows('SELECT * FROM runs ORDER BY id'):
        counts['runs']+=1;c=json.loads(run['config']);configs[run['id']]=c
        history=store.history(run['id']);counts['rounds']+=len(history)
        archives=[store.archive(run['id'],i) for i in (0,1)]
        assert [r['t'] for r in history]==list(range(1,len(history)+1)),run['id']
        if run['status']=='completed' and c['stage']!='cache_calibration':assert len(history)==c['T'],run['id']
        entries=store.rows('SELECT * FROM memory_entries WHERE run_id=? ORDER BY t,agent',(run['id'],))
        counts['memory_entries']+=len(entries)
        assert len(entries)==(2*len(history) if c['architecture']=='bullet_memory' else 0),run['id']
        for entry in entries:
            assert entry['text']==history[entry['t']-1]['actions'][entry['agent']]['memory_bullet']
        if run['parent']:
            assert history[:run['checkpoint']]==store.history(run['parent'])[:run['checkpoint']]
        for row in history:
            q,p=Market().settle(row['prices'])
            assert np.allclose(q,row['quantities'],rtol=1e-12,atol=1e-12)
            assert np.allclose(p,row['profits'],rtol=1e-12,atol=1e-12)
            assert row['proposed_prices']==[a['price'] for a in row['actions']]
            if row['t']<=run['checkpoint']:continue
            expected=row['proposed_prices'].copy();shock=c.get('shock')
            if shock and row['t']==shock['t']:expected[shock['agent']]*=shock['factor']
            assert expected==row['prices'],(run['id'],row['t'])
            if run['prompt_hash']!=prompt_hash():continue
            for agent in (0,1):
                view=store.rows('SELECT payload FROM memory_views WHERE run_id=? AND t=? AND agent=?',(run['id'],row['t'],agent))[0]
                view=json.loads(view['payload'])
                archive=archives[agent][:row['t']-1]
                assert digest(archive)==view['source_hash']
                assert view['source_range']==([1,len(archive)] if archive else [])
                if c['architecture']=='bullet_memory' and c['mode']=='compressed':
                    if archive:
                        call=f"{run['id']}:{row['t']}:{agent}:compressor"
                        compressed=store.accepted(call,digest(request_body(c,build_compressor(archive),'compressor')))
                        assert compressed is not None and compressed['memory_bullet']==view['text'],call
                        counts['verified_compressor_inputs']+=1
                    else:assert view['text']==''
                if c['architecture']=='bullet_memory' and c['mode']=='clear':assert view['text']==''
                if c['architecture']=='bullet_memory' and c['mode']=='full':assert view['text']=='\n'.join(archive)
                past=history[:row['t']-1]
                paper=past[-1]['actions'][agent] if past and c['architecture']=='paper_reference' else None
                prompt=build_seller(c,visible_history(past,c['H'],agent),view['text'],paper)
                call=row.get('action_call_ids',[f"{run['id']}:{row['t']}:0:seller",f"{run['id']}:{row['t']}:1:seller"])[agent]
                accepted=store.accepted(call,digest(request_body(c,prompt,'seller')))
                assert accepted==row['actions'][agent],call
                counts['verified_seller_inputs']+=1
    for row in store.rows('SELECT * FROM api_attempts'):
        counts['attempts']+=1
        request=store.root/f"requests/{row['id']}.json"
        assert request.exists(),row['id']
        assert digest(json.loads(request.read_text()))==row['request_hash'],row['id']
        if row['raw_path']:
            raw_file=store.root/row['raw_path']
            assert digest(raw_file.read_text())==row['raw_sha256'],row['id']
        if row['status']=='accepted':
            counts['accepted_attempts']+=1
            raw=json.loads((store.root/row['raw_path']).read_text())
            assert raw['model']==configs[row['run_id']]['model']
            if raw.get('usage'):
                expected=cost_from_usage(raw['usage'],configs[row['run_id']]['prices'])
                assert abs(expected-row['cost'])<1e-10,row['id']
    spending=store.spending();assert spending['spent']+spending['reserved']<=spending['budget']+1e-8
    assert spending['reserved']==0,'Wait for all in-flight requests before final audit'
    result={'passed':True,'counts':counts,'spending':spending,'prompt_hash':prompt_hash(),
            'checks':['consecutive rounds','immutable memory and fork lineage','economic recomputation',
                      'price intervention arithmetic','private input reconstruction for current prompts',
                      'full archive compressor input reconstruction','accepted response provenance','raw/request checksums','usage-cost reconciliation','budget']}
    atomic_json(ROOT/'reports/data_audit.json',result);print(json.dumps(result,indent=2));store.close()


if __name__=='__main__':main()
