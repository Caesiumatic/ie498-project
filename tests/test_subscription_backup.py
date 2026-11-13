"""Subscription requests must survive backup without copying authorization."""
import json

import pytest

from ie498.agents import request_body
from ie498.backup import file_hash, restore, snapshot
from ie498.cli import load_config
from ie498.memory import digest
from ie498.runner import create_run
from ie498.storage import Store, atomic_json
from ie498.subscription_transport import subscription_request


def make_live_store(tmp_path):
    store=Store(tmp_path/'live',budget=None)
    config=load_config()
    create_run(store,'subscription-backup',config)
    canonical=request_body(config,'Private seller prompt.','seller')
    wire=subscription_request(canonical)
    raw={'transport':'chatgpt_subscription_responses','terminal_event':'response.completed',
         'response':{'model':config['model'],'status':'completed','output':[]}}
    row={'id':'subscription-backup_1_0_seller_a1','call_id':'subscription-backup:1:0:seller',
         'attempt':1,'run_id':'subscription-backup','t':1,'agent':0,'purpose':'seller',
         'request_hash':digest(canonical),'request_json':json.dumps(canonical),'reserved':0}
    store.reserve(row)
    for prefix,payload in [('requests',canonical),('wire_requests',wire),('raw',raw)]:
        atomic_json(store.root/f"{prefix}/{row['id']}.json",payload)
    store.finish_attempt(row['id'],'invalid',0,{},raw_path=f"raw/{row['id']}.json",error='Fixture only')
    # Neither a sibling auth directory nor an accidental auth directory inside
    # the live root is part of the per-attempt backup allowlist.
    atomic_json(tmp_path/'auth/chatgpt-plan.json',{'access_token':'test-only-secret'})
    atomic_json(store.root/'auth/chatgpt-plan.json',{'access_token':'test-only-secret'})
    return store,row


def test_snapshot_restore_keeps_wire_records_and_excludes_auth(tmp_path):
    store,row=make_live_store(tmp_path)
    try:
        before=store.rows('SELECT * FROM api_attempts')
        db_hash=file_hash(store.root/'experiments.sqlite')
        changes=store.db.total_changes
        paths=[f"{prefix}/{row['id']}.json" for prefix in ('requests','wire_requests','raw')]
        original_hashes={rel:file_hash(store.root/rel) for rel in paths}
        saved=snapshot(store,tmp_path/'backups')
        manifest=json.loads((saved/'manifest.json').read_text())
        assert set(manifest['files'])=={'experiments.sqlite',*paths}
        assert all(manifest['files'][rel]==sha for rel,sha in original_hashes.items())
        restored=restore(saved,tmp_path/'restored')
        assert all(file_hash(restored/rel)==sha for rel,sha in original_hashes.items())
        recovered=Store(restored,readonly=True)
        try:
            assert recovered.rows('SELECT * FROM api_attempts')==before
        finally:
            recovered.close()
        assert not (saved/'auth').exists() and not (restored/'auth').exists()
        assert store.rows('SELECT * FROM api_attempts')==before
        assert file_hash(store.root/'experiments.sqlite')==db_hash
        assert store.db.total_changes==changes
        assert all(file_hash(store.root/rel)==sha for rel,sha in original_hashes.items())
    finally:
        store.close()


def test_restore_rejects_corrupted_subscription_wire_record(tmp_path):
    store,row=make_live_store(tmp_path)
    try:
        saved=snapshot(store,tmp_path/'backups')
        wire_path=saved/f"wire_requests/{row['id']}.json"
        wire_path.write_text('{}')
        with pytest.raises(ValueError,match='Backup integrity failure: wire_requests/'):
            restore(saved,tmp_path/'restored')
        assert not (tmp_path/'restored').exists()
        assert json.loads((store.root/f"wire_requests/{row['id']}.json").read_text())['model']=='gpt-6-luna'
    finally:
        store.close()
