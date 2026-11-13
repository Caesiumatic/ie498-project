import asyncio
import copy
import json
import sqlite3
import re
import numpy as np
import pytest

from ie498.agents import Caller, cost_from_usage, request_body
from ie498.analysis import metrics, wilson, analyze
from ie498.backup import snapshot, restore
from ie498.cli import load_config, plan_conditions
from ie498.environment import Market
from ie498.memory import build_compressor, build_seller, digest, parse_output, prompt_hash, validate_bullet, visible_history
from ie498.runner import create_run, git_commit, run_batch
from ie498.storage import Store, BudgetStop, atomic_json


@pytest.fixture
def config():
    c=load_config();c.update(provider='mock',T=4,stage='mock');return c


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'data');yield s;s.close()


def test_market_and_benchmarks():
    market=Market();b=market.benchmarks()
    assert b['nash_price']==pytest.approx([1.47292666]*2,abs=1e-7)
    assert b['joint_price']==pytest.approx([1.92498092]*2,abs=1e-6)
    assert sum(b['nash_profit'])==pytest.approx(44.58533201,abs=1e-6)
    assert sum(b['joint_profit'])==pytest.approx(67.49809190,abs=1e-6)
    assert b['best_response_check']==pytest.approx(b['nash_price'],abs=1e-5)
    q,p=market.settle([.5,1000000]);assert np.isfinite(q).all() and p[0]<0 and q.sum()<=100
    assert Market(a=(2,),c=(1,)).benchmarks()['joint_price'][0]!=pytest.approx(b['joint_price'][0])
    for price in [-1,float('nan'),float('inf')]:
        with pytest.raises(ValueError):market.settle([price,1])


def test_history_boundary_and_order():
    hist=[dict(t=t,prices=[t,t+.1],quantities=[90,5],profits=[8,4]) for t in range(1,4)]
    assert visible_history(hist,0,0)==''
    assert 'Round 2' not in visible_history(hist,1,0)
    text=visible_history(hist,100,1)
    assert text.index('Round 3')<text.index('Round 1')
    assert 'My quantity sold: 5.00' in text and '90.00' not in text


@pytest.mark.parametrize('text',['- I will test 1.75, e.g. a cautious price.','- My price is 1.75.'])
def test_sentence_decimal_abbreviation(text):assert validate_bullet(text)==text


@pytest.mark.parametrize('text',['No bullet.','- First. Second.','- First\n- Second.','- '+('word '*61)+'.','- No ending'])
def test_invalid_bullets(text):
    with pytest.raises(ValueError):validate_bullet(text)


def test_pipeline_memory_and_sampling(store,config):
    for mode in ('clear','full','compressed'):
        c=dict(config,mode=mode,H=0);create_run(store,mode,c)
    asyncio.run(run_batch(store,['clear','full','compressed']))
    for mode in ('clear','full','compressed'):
        assert len(store.history(mode))==4
        for agent in (0,1):assert len(store.archive(mode,agent))==4
        views=[json.loads(r['payload']) for r in store.rows('SELECT * FROM memory_views WHERE run_id=? ORDER BY t,agent',(mode,))]
        assert all(v['history_tokens']==0 for v in views)
        assert views[0]['text']==''
        if mode=='clear':assert all(v['text']=='' for v in views)
        if mode=='full':assert views[-2]['text']=='\n'.join(store.archive(mode,0)[:3])
        if mode=='compressed':
            req=store.rows("SELECT request_json FROM api_attempts WHERE run_id=? AND t=4 AND agent=0 AND purpose='compressor'",(mode,))[0]
            text=json.loads(req['request_json'])['messages'][0]['content']
            assert text==build_compressor(store.archive(mode,0)[:3])
            assert store.archive(mode,1)[0] not in text
    requests=store.rows("SELECT request_hash FROM api_attempts WHERE run_id='clear'")
    assert len(requests)==8 and len({r['request_hash'] for r in requests})==1
    assert len(store.rows("SELECT * FROM api_attempts WHERE purpose='compressor'"))==6


def test_partial_response_resume_and_atomic_commit(store,config,monkeypatch):
    c=dict(config,T=2);create_run(store,'resume',c)
    real=Caller.call
    async def fail_second(self,run,t,agent,purpose,prompt,config):
        if t==1 and agent==1:raise RuntimeError('Injected interruption')
        return await real(self,run,t,agent,purpose,prompt,config)
    monkeypatch.setattr(Caller,'call',fail_second)
    asyncio.run(run_batch(store,['resume']))
    assert store.history('resume')==[]
    assert len(store.rows("SELECT * FROM api_attempts WHERE status='accepted'"))==1
    monkeypatch.setattr(Caller,'call',real)
    asyncio.run(run_batch(store,['resume']))
    assert len(store.history('resume'))==2
    assert len(store.rows('SELECT * FROM api_attempts'))==4
    asyncio.run(run_batch(store,['resume']))
    assert len(store.rows('SELECT * FROM api_attempts'))==4
    assert len(store.archive('resume',0))==2
    reqs=store.rows('SELECT agent,request_json FROM api_attempts WHERE t=1')
    assert reqs[0]['request_json']==reqs[1]['request_json']


def test_budget_reservation_and_unknown_recovery(store,config):
    create_run(store,'budget',config)
    row=dict(id='one',call_id='budget:1:0:seller',attempt=1,run_id='budget',t=1,agent=0,purpose='seller',
             request_hash='hash',request_json='{}',reserved=10)
    store.reserve(row)
    with pytest.raises(BudgetStop):store.reserve(dict(row,id='two',call_id='other'))
    caller=Caller(store);caller.reconcile();asyncio.run(caller.close())
    assert store.spending()['spent']==10 and store.spending()['reserved']==0
    with pytest.raises(BudgetStop):store.reserve(dict(row,id='two',call_id='other'))


def test_raw_response_reconciliation(store,config):
    create_run(store,'raw',config)
    body=request_body(config,'hello','seller');call='raw:1:0:seller'
    row=dict(id='raw_a1',call_id=call,attempt=1,run_id='raw',t=1,agent=0,purpose='seller',
             request_hash=digest(body),request_json=json.dumps(body),reserved=0)
    store.reserve(row)
    atomic_json(store.root/'raw/raw_a1.json',Caller.mock(call,body,config,'seller'))
    caller=Caller(store);caller.reconcile();asyncio.run(caller.close())
    assert store.accepted(call,digest(body))['price']>0


def test_cost_reasoning_not_double_counted():
    u={'prompt_tokens':1000,'prompt_tokens_details':{'cached_tokens':500},'completion_tokens':100,
       'completion_tokens_details':{'reasoning_tokens':80}}
    prices={'input':.1,'cached_input':.01,'output':.5}
    assert cost_from_usage(u,prices)==pytest.approx(.000105)


def test_structured_sentence_constraint(config):
    body=request_body(config,'test','seller')
    pattern=body['response_format']['json_schema']['schema']['properties']['memory_bullet']['pattern']
    assert re.fullmatch(pattern,'- My cost is $1.00; I will test $1.75 to assess profit.')
    for invalid in ['- One sentence. Another sentence.','- '+('word '*61).strip()+'.','- New\nline.']:
        assert not re.fullmatch(pattern,invalid)


@pytest.mark.parametrize('cache_mode',['explicit_prefix','explicit_blocks'])
def test_cache_segmentation_does_not_change_information(config,cache_mode):
    c=dict(config,mode='full',cache_mode=cache_mode)
    prompt=build_seller(c,'', '- I will test $1.50.\n- I will next test $1.75.')
    body=request_body(c,prompt,'seller')
    parts=body['messages'][0]['content']
    assert ''.join(p['text'] for p in parts)==prompt
    assert sum('prompt_cache_breakpoint' in p for p in parts)==2
    assert len(body['messages'])==1 and body['store'] is False
    clear=request_body(dict(c,mode='clear'),build_seller(c,'',''),'seller')
    assert isinstance(clear['messages'][0]['content'],str)


def test_fork_metrics_backup_analysis(store,config,tmp_path):
    create_run(store,'parent',config);asyncio.run(run_batch(store,['parent']))
    c=dict(config,T=4,H=0,mode='clear',stage='shock',shock={'t':3,'agent':0,'factor':.9})
    store.fork('parent','child',2,c,git_commit(),prompt_hash());asyncio.run(run_batch(store,['child']))
    hist=store.history('child');assert hist[:2]==store.history('parent')[:2]
    assert hist[2]['prices'][0]==hist[2]['proposed_prices'][0]*.9
    assert hist[3]['prices']==hist[3]['proposed_prices']
    assert store.archive('child',0)[:2]==store.archive('parent',0)[:2]
    assert len(store.history('parent'))==4
    b=Market().benchmarks();q,p=Market().settle(b['joint_price'])
    result=metrics([dict(prices=b['joint_price'],profits=p)]*50)
    assert result['CI']==pytest.approx(1) and result['effective_success']
    assert wilson(0,3)[0]==0
    backup=snapshot(store,tmp_path/'backups');restored=restore(backup,tmp_path/'restored')
    db=sqlite3.connect(restored/'experiments.sqlite');assert db.execute('SELECT COUNT(*) FROM rounds').fetchone()[0]==8;db.close()
    analyze(store,tmp_path/'report');assert (tmp_path/'report/trajectories/child.png').exists()
    import pandas as pd
    pairs=pd.read_csv(tmp_path/'report/paired_conditions.csv')
    assert pairs.iloc[0]['n_parents']==1 and pairs.iloc[0]['H']==0 and pairs.iloc[0]['mode']=='clear'


def test_balanced_plan():
    plan=plan_conditions(3);assert len(plan)==45
    for rep in (1,2,3):assert len({(r['H'],r['mode']) for r in plan if r['repetition']==rep})==15


def test_shock_shares_only_prespecified_first_actions(store,config):
    c=dict(config,T=6);create_run(store,'source',c);asyncio.run(run_batch(store,['source']))
    child=dict(c,T=8,stage='shock',share_parent_first_actions=True,shock={'t':4,'agent':0,'factor':.9})
    store.fork('source','shock-shared',3,child,git_commit(),prompt_hash())
    asyncio.run(run_batch(store,['shock-shared']))
    source=store.history('source')[3];shocked=store.history('shock-shared')[3]
    assert shocked['actions']==source['actions']
    assert shocked['prices'][0]==source['prices'][0]*.9 and shocked['prices'][1]==source['prices'][1]
    assert shocked['action_call_ids']==['source:4:0:seller','source:4:1:seller']
    assert len(store.rows("SELECT * FROM api_attempts WHERE run_id='shock-shared'"))==8
