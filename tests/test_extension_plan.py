import importlib.util
from pathlib import Path
import pytest
from ie498.cli import load_config
from ie498.memory import prompt_hash
from ie498.runner import create_run
from ie498.storage import Store

spec=importlib.util.spec_from_file_location('extension',Path(__file__).resolve().parents[1]/'scripts/run_extension.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_extension_reactivates_only_unstarted_matching_plans(tmp_path):
    store=Store(tmp_path)
    config=dict(load_config(),provider='mock',stage='formation',T=1)
    create_run(store,'old',config);store.status('old','cancelled_user')
    plan={'prompt_hash':prompt_hash(),'runs':[{'id':'old','config':config}]}
    module.prepare(store,plan)
    assert store.rows('SELECT status FROM runs')[0]['status']=='planned'
    store.status('old','completed')
    module.prepare(store,plan)
    assert store.rows('SELECT status FROM runs')[0]['status']=='completed'
    store.close()


def test_extension_validates_entire_plan_before_mutation(tmp_path):
    store=Store(tmp_path)
    config=dict(load_config(),provider='mock',stage='formation',T=1)
    create_run(store,'old',config);store.status('old','cancelled_user')
    create_run(store,'conflict',dict(config,H=0))
    plan={'prompt_hash':prompt_hash(),'runs':[{'id':'old','config':config},{'id':'conflict','config':config}]}
    with pytest.raises(ValueError,match='differs'):module.prepare(store,plan)
    assert store.rows("SELECT status FROM runs WHERE id='old'")[0]['status']=='cancelled_user'
    store.close()
