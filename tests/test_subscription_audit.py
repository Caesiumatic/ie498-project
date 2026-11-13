"""Transport migration must remain auditable without rewriting scientific calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ie498.agents import request_body
from ie498.cli import load_config
from ie498.memory import digest
from ie498.storage import atomic_json
from ie498 import subscription_transport as subscription


spec=importlib.util.spec_from_file_location('audit_subscription',Path(__file__).resolve().parents[1]/'scripts/audit_data.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def fixture_attempt(tmp_path):
    config=load_config()
    canonical=request_body(config,'Private seller prompt.','seller')
    wire=subscription.subscription_request(canonical)
    row={'id':'seller_a1','request_hash':digest(canonical),'reserved':0,'cost':0,'status':'failed'}
    raw={'transport':subscription.TRANSPORT,'http_status':400,
         'events':[],'error':{'code':'invalid_request_error'}}
    raw['transport_provenance']={
        'canonical_request_sha256':row['request_hash'],
        'wire_request_sha256':digest(wire),
        'wire_request_path':'wire_requests/seller_a1.json',
        'endpoint':'https://api.openai.com/v1/responses',
        'billing_path':'chatgpt_subscription',
        'interface_changes':subscription.transport_metadata(canonical),
    }
    row['usage']=json.dumps(subscription.normalized_usage(raw))
    atomic_json(tmp_path/'wire_requests/seller_a1.json',wire)
    return SimpleNamespace(root=tmp_path),row,canonical,raw,config


def test_subscription_audit_detects_wire_prompt_tampering(tmp_path):
    args=fixture_attempt(tmp_path)
    assert audit.verify_subscription_attempt(*args) is None
    path=tmp_path/'wire_requests/seller_a1.json'
    wire=json.loads(path.read_text())
    wire['input'][0]['content']='Extra rival memory was leaked.'
    atomic_json(path,wire)
    # Even a correspondingly updated wire hash cannot conceal a changed prompt.
    args[3]['transport_provenance']['wire_request_sha256']=digest(wire)
    with pytest.raises(AssertionError,match='Subscription request changed'):
        audit.verify_subscription_attempt(*args)


def test_subscription_audit_detects_usage_or_cash_contamination(tmp_path):
    args=fixture_attempt(tmp_path)
    args[1]['usage']=json.dumps({'prompt_tokens':999999})
    with pytest.raises(AssertionError,match='Subscription usage mismatch'):
        audit.verify_subscription_attempt(*args)
    args[1]['usage']=json.dumps(subscription.normalized_usage(args[3]))
    args[1]['cost']=0.01
    with pytest.raises(AssertionError,match='API cash ledger'):
        audit.verify_subscription_attempt(*args)


def test_subscription_audit_requires_original_request_provenance(tmp_path):
    args=fixture_attempt(tmp_path)
    args[3]['transport_provenance']['canonical_request_sha256']='unrelated-call'
    with pytest.raises(AssertionError,match='Subscription provenance mismatch'):
        audit.verify_subscription_attempt(*args)


def test_subscription_crash_cannot_be_recorded_as_completed(tmp_path):
    store,row,canonical,raw,config=fixture_attempt(tmp_path)
    row['status']='uncertain'
    assert audit.verify_subscription_attempt(store,row,canonical,None,config) is None
    row['status']='accepted'
    with pytest.raises(AssertionError,match='Missing subscription response'):
        audit.verify_subscription_attempt(store,row,canonical,None,config)
