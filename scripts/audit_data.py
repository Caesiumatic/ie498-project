"""Validate stored scientific data, request provenance, raw hashes and cost ledger."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.agents import request_body,cost_from_usage
from ie498.environment import Market
from ie498.memory import build_compressor,build_seller,digest,parse_output,prompt_hash,visible_history
from ie498.storage import Store,atomic_json
from ie498 import subscription_transport as subscription


def verify_original_run_immutability(store, manifest_path):
    """Check frozen payloads one run at a time using the original JSON encoding."""
    expected=json.loads(Path(manifest_path).read_text())
    required={f'formation-r{r}-h{h}-{mode}' for r in (1,2,3)
              for h in (0,1,5,20,100) for mode in ('clear','full','compressed')}
    assert set(expected)==required,'Original-run fingerprint manifest must cover all 45 original runs'
    for run_id, frozen_hash in expected.items():
        payload={table:store.rows(f'SELECT * FROM {table} WHERE run_id=? ORDER BY rowid',(run_id,))
                 for table in ('rounds','memory_entries','memory_views','api_attempts')}
        # Keep json.dumps defaults (including ensure_ascii=True and separators):
        # these fingerprints were captured with json.dumps(payload, sort_keys=True).
        observed=digest(json.dumps(payload,sort_keys=True))
        assert observed==frozen_hash,('Original run payload changed',run_id)
        del payload
    return len(expected)


def verify_reference_memory_view(history, t, agent, view):
    previous=history[t-2]['actions'][agent] if t>1 else {'plans':'','insights':''}
    assert view['text']==previous['plans']+'\n'+previous['insights'],('Paper memory overwrite mismatch',t,agent)


def verify_subscription_attempt(store, row, canonical, raw, config):
    """Verify the actual subscription request without rewriting canonical history.

    The canonical Chat Completions request identifies the scientific call across
    interfaces. The separate wire request records exactly what Responses received.
    A crash can leave that request without a response; it must still be checked.
    """
    expected_path=f"wire_requests/{row['id']}.json"
    wire_path=store.root/expected_path
    assert wire_path.exists(),('Missing subscription wire request',row['id'])
    wire=json.loads(wire_path.read_text())
    assert wire==subscription.subscription_request(canonical),('Subscription request changed',row['id'])
    assert row['reserved']==0 and row['cost']==0,('Subscription request entered API cash ledger',row['id'])
    if raw is None:
        assert row['status']=='uncertain',('Missing subscription response',row['id'])
        return None
    assert raw.get('transport')==subscription.TRANSPORT,('Missing subscription transport marker',row['id'])
    provenance=raw.get('transport_provenance',{})
    assert provenance=={
        'canonical_request_sha256':row['request_hash'],
        'wire_request_sha256':digest(wire),
        'wire_request_path':expected_path,
        'endpoint':'https://api.openai.com/v1/responses',
        'billing_path':'chatgpt_subscription',
        'interface_changes':subscription.transport_metadata(canonical),
    },('Subscription provenance mismatch',row['id'])
    assert json.loads(row['usage'] or '{}')==subscription.normalized_usage(raw),('Subscription usage mismatch',row['id'])
    if row['status']=='accepted':
        return subscription.extract_text(raw,config['model'])
    return None


def main():
    store=Store(ROOT/'data/runs/live',readonly=True)
    assert store.spending()['reserved']==0,'Stop requests before final audit'
    assert not store.rows("SELECT id FROM runs WHERE status='running'"),'Stop the runner before final audit'
    counts=dict(verified_original_runs=0,verified_reference_memory_views=0,runs=0,rounds=0,memory_entries=0,attempts=0,accepted_attempts=0,verified_seller_inputs=0,verified_compressor_inputs=0,reparsed_current_outputs=0,verified_subscription_requests=0,accepted_subscription_attempts=0)
    fingerprint_manifest=ROOT/'data/manifests/pre-extension-original-run-hashes.json'
    counts['verified_original_runs']=verify_original_run_immutability(store,fingerprint_manifest)
    configs={};hashes={}
    for run in store.rows('SELECT * FROM runs ORDER BY id'):
        counts['runs']+=1;c=json.loads(run['config']);configs[run['id']]=c;hashes[run['id']]=run['prompt_hash']
        history=store.history(run['id']);counts['rounds']+=len(history)
        archives=[store.archive(run['id'],i) for i in (0,1)]
        assert [r['t'] for r in history]==list(range(1,len(history)+1)),run['id']
        if run['status']=='completed' and c['stage']!='cache_calibration':assert len(history)==c['T'],run['id']
        entries=store.rows('SELECT * FROM memory_entries WHERE run_id=? ORDER BY t,agent',(run['id'],))
        counts['memory_entries']+=len(entries)
        assert len(entries)==(2*len(history) if c['architecture']=='bullet_memory' else 0),run['id']
        if c['architecture']=='paper_reference':
            assert not entries,('Paper reference must not append bullet entries',run['id'])
            for stored_view in store.rows('SELECT t,agent,payload FROM memory_views WHERE run_id=? ORDER BY t,agent',(run['id'],)):
                verify_reference_memory_view(history,stored_view['t'],stored_view['agent'],json.loads(stored_view['payload']))
                counts['verified_reference_memory_views']+=1
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
    for stored_row in store.db.execute('SELECT id,request_hash,request_json,raw_path,raw_sha256,status,run_id,purpose,parsed,cost,reserved,usage FROM api_attempts'):
        row=dict(stored_row)
        counts['attempts']+=1
        request=store.root/f"requests/{row['id']}.json"
        assert request.exists(),row['id']
        canonical=json.loads(request.read_text())
        assert digest(canonical)==row['request_hash'],row['id']
        assert canonical==json.loads(row['request_json']),row['id']
        raw=None
        if row['raw_path']:
            raw_file=store.root/row['raw_path']
            assert digest(raw_file.read_text())==row['raw_sha256'],row['id']
            raw=json.loads(raw_file.read_text())
        is_subscription=(raw is not None and raw.get('transport')==subscription.TRANSPORT) or (store.root/f"wire_requests/{row['id']}.json").exists()
        if is_subscription:
            text=verify_subscription_attempt(store,row,canonical,raw,configs[row['run_id']])
            counts['verified_subscription_requests']+=1
        if row['status']=='accepted':
            counts['accepted_attempts']+=1
            assert raw is not None,row['id']
            if is_subscription:
                counts['accepted_subscription_attempts']+=1
            else:
                assert raw['model']==configs[row['run_id']]['model']
                text=raw['choices'][0]['message']['content']
            if hashes[row['run_id']]==prompt_hash():
                reparsed=parse_output(text,row['purpose'],configs[row['run_id']]['architecture'])
                assert reparsed==json.loads(row['parsed']),row['id']
                counts['reparsed_current_outputs']+=1
            if not is_subscription and raw.get('usage'):
                expected=cost_from_usage(raw['usage'],configs[row['run_id']]['prices'])
                assert abs(expected-row['cost'])<1e-10,row['id']
    spending=store.spending()
    if spending['budget'] is not None:assert spending['spent']+spending['reserved']<=spending['budget']+1e-8
    assert spending['reserved']==0,'Wait for all in-flight requests before final audit'
    result={'passed':True,'counts':counts,'spending':spending,'prompt_hash':prompt_hash(),
            'checks':['original_run_immutability','reference_memory_overwrite','consecutive rounds','immutable memory and fork lineage','economic recomputation',
                      'price intervention arithmetic','private input reconstruction for current prompts',
                      'full archive compressor input reconstruction','accepted response provenance','reparse current-protocol raw outputs','raw/request checksums','subscription wire request and usage provenance','subscription requests excluded from API cash ledger','usage-cost reconciliation','budget']}
    atomic_json(ROOT/'reports/data_audit.json',result);print(json.dumps(result,indent=2));store.close()


if __name__=='__main__':main()
