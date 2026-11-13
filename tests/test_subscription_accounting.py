"""Mixed billing must not turn unpriced subscription usage into free resources."""
import importlib.util
import json
from pathlib import Path

from ie498.analysis import subscription_accounting
from ie498.cli import load_config
from ie498.runner import create_run
from ie498.storage import Store, atomic_json


def script(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/f'scripts/{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def usage_rows(tmp_path):
    atomic_json(tmp_path/'wire_requests/interrupted.json',{'model':'gpt-6-luna'})
    return [
        {'id':'api','cost':0.25,'usage':json.dumps({'prompt_tokens':100,'completion_tokens':10})},
        {'id':'subscription','cost':0,'usage':json.dumps({'billing_path':'chatgpt_subscription',
            'prompt_tokens':200,'completion_tokens':20,'completion_tokens_details':{'reasoning_tokens':15}})},
        {'id':'interrupted','cost':0,'usage':'{}'},
    ]


def test_subscription_counts_include_interrupted_calls_without_inventing_tokens(tmp_path):
    result=subscription_accounting(usage_rows(tmp_path),tmp_path)
    assert result=={
        'subscription_calls':2,'subscription_input_tokens':200,
        'subscription_output_tokens':20,'subscription_reasoning_tokens':15,
        'subscription_calls_without_usage':1,'api_cash_ledger_usd':0.25,
    }


def test_progress_separates_subscription_usage_and_labels_mixed_throughput(tmp_path):
    progress=script('extension_progress')
    data=tmp_path/'live'
    store=Store(data,budget=None)
    config=dict(load_config(),repetition=4,H=0,mode='clear')
    create_run(store,'extension',config)
    attempts=usage_rows(data)
    for number,attempt in enumerate(attempts,1):
        store.reserve(dict(id=attempt['id'],call_id=f'extension:{number}:0:seller',attempt=1,
            run_id='extension',t=number,agent=0,purpose='seller',request_hash='fixture',request_json='{}',reserved=0))
        store.finish_attempt(attempt['id'],'uncertain',attempt['cost'],json.loads(attempt['usage']))
    store.close()
    freeze=tmp_path/'freeze.json'
    atomic_json(freeze,{'runs':[{'id':'extension','config':config}],
        'amendment':{'prior_repeats':3,'balance':{'spent':0}},'new_bullet_runs':1,'new_reference_runs':0})
    result=progress.summarize(data,freeze)
    assert result['ledger_spent_usd']==result['selected_run_cost_usd']==0.25
    assert result['token_usage']=={'prompt_tokens':300,'completion_tokens':30}
    assert result['subscription_calls']==2 and result['subscription_calls_without_usage']==1
    assert result['subscription_token_usage']=={'prompt_tokens':200,'completion_tokens':20}
    assert result['performance_comparison']['mixed_interfaces'] is True
    assert 'cannot isolate' in result['performance_comparison']['interpretation']


def test_report_does_not_describe_prepared_subscription_adapter_as_executed():
    report=script('make_report')
    pending=report.interface_description(0)
    switched=report.interface_description(1)
    assert 'no subscription inference is recorded yet' in pending
    assert 'GPT-6 Luna' in switched and 'original prompt text and memory logic' in switched
    assert 'without an equivalence experiment' in switched
