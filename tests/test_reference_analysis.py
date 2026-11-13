"""Keep the later-added paper condition separate from the original matrix."""
import pandas as pd
import pytest

from ie498 import analysis
from ie498.cli import load_config
from ie498.environment import Market
from ie498.runner import create_run
from ie498.storage import Store


def test_reference_analysis_does_not_pool_architectures_or_pilots(tmp_path,monkeypatch):
    store=Store(tmp_path/'data')
    benchmarks=Market().benchmarks()

    def add(run,architecture,stage,price,repetition=1,provider='openai',completed=True,mode='full'):
        config=dict(load_config(),architecture=architecture,stage=stage,H=100,mode=mode,
                    T=2,repetition=repetition,provider=provider)
        create_run(store,run,config)
        prices=[price]*2
        q,profits=Market().settle(prices)
        for t in (1,2):
            actions=[dict(price=price,memory_bullet='- Preserve this original observation.') for _ in range(2)]
            store.commit_round(run,dict(t=t,prices=prices,proposed_prices=prices,
                quantities=q.tolist(),profits=profits.tolist(),shock_flags=[False]*2,
                ceiling_exceeded=[False]*2,actions=actions),actions,architecture)
        store.status(run,'completed' if completed else 'paused_error')

    nash=benchmarks['nash_price'][0];joint=benchmarks['joint_price'][0]
    add('bullet-full','bullet_memory','formation',joint,repetition=3)
    add('bullet-clear','bullet_memory','formation',joint,mode='clear')
    add('bullet-compressed','bullet_memory','formation',joint,mode='compressed')
    add('reference-1','paper_reference','formation_reference',nash)
    add('reference-2','paper_reference','formation_reference',nash,repetition=2)
    add('paper-pilot','paper_reference','pilot',joint)
    add('paper-mock','paper_reference','formation_reference',joint,provider='mock')
    add('paper-incomplete','paper_reference','formation_reference',joint,completed=False)
    # Defensive exclusion even if a paper run is mislabeled as the old formation stage.
    add('paper-wrong-stage','paper_reference','formation',joint)
    monkeypatch.setattr(analysis,'_plots',lambda *args:None)
    out=tmp_path/'report';analysis.analyze(store,out)
    primary=pd.read_csv(out/'conditions.csv')
    assert len(primary)==3
    assert list(primary.n)==[1]*3
    assert list(primary.successes)==[1]*3
    reference=pd.read_csv(out/'paper_reference_conditions.csv')
    assert len(reference)==1
    row=reference.iloc[0]
    assert row.architecture=='paper_reference'
    assert row.condition=='overwritten_plans_insights'
    assert row.n==2 and row.successes==0
    assert row.mean_CI==pytest.approx(0,abs=1e-12)
    assert row.wilson_high>0 and row.CI_bootstrap_low==pytest.approx(0,abs=1e-12)
    compare=pd.read_csv(out/'paper_reference_comparison.csv')
    assert len(compare)==4
    assert compare.groupby('architecture').n.sum().to_dict()=={'bullet_memory':3,'paper_reference':2}
    runs=pd.read_csv(out/'runs.csv').set_index('id')
    assert runs.loc['bullet-full','repetition']==3
    assert not runs.loc['paper-pilot','eligible_reference']
    assert not runs.loc['paper-wrong-stage','eligible_primary']
    parents=pd.read_csv(out/'parent_eligibility.csv')
    assert list(parents.parent)==['bullet-full']
    report=(out/'results.md').read_text()
    assert 'overwritten_plans_insights' in report and 'added after inspecting' in report
    store.close()
