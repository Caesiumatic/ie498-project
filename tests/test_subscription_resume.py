import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from ie498 import subscription_transport as subscription
from ie498.agents import Caller, PermanentAPIError, request_body
from ie498.cli import load_config
from ie498.memory import digest
from ie498.runner import create_run
from ie498.storage import Store, atomic_json


def saved_attempt(store, config, status):
    body = request_body(config, 'Original prompt', 'seller')
    row = dict(id='resume_1_0_seller_a1', call_id='resume:1:0:seller', attempt=1,
               run_id='resume', t=1, agent=0, purpose='seller',
               request_hash=digest(body), request_json=json.dumps(body), reserved=0)
    store.reserve(row)
    atomic_json(store.root/'requests'/f"{row['id']}.json", body)
    if status == 'accepted':
        action = {'price': 1.7, 'memory_bullet': '- I will test a price of 1.7.'}
        raw = {'model': config['model'], 'choices': [{'message': {'content': json.dumps(action)}, 'finish_reason': 'stop'}]}
        atomic_json(store.root/'raw'/f"{row['id']}.json", raw)
        store.finish_attempt(row['id'], 'accepted', 0, {}, action, f"raw/{row['id']}.json")
        return action
    store.finish_attempt(row['id'], 'failed', 0, error='Prior API credit exhaustion')


def completed_response():
    text = json.dumps({'price': 1.8, 'memory_bullet': '- I will test a price of 1.8.'})
    return {'transport': subscription.TRANSPORT, 'http_status': 200,
            'terminal_event': 'response.completed', 'events': [],
            'response': {'status': 'completed', 'model': 'gpt-6-luna',
                         'output': [{'type': 'message', 'role': 'assistant',
                                     'content': [{'type': 'output_text', 'text': text}]}],
                         'usage': {'input_tokens': 100, 'output_tokens': 25}}}


def test_reuse_accepted_partial_round_without_auth_or_resampling(tmp_path, monkeypatch):
    async def scenario():
        store=Store(tmp_path,budget=None); config=load_config(); create_run(store,'resume',config)
        expected=saved_attempt(store,config,'accepted')
        before=store.rows('SELECT * FROM api_attempts')
        auth=AsyncMock(); caller=Caller(store,transport=subscription.TRANSPORT,subscription_auth=auth)
        send=AsyncMock(); monkeypatch.setattr(subscription,'send',send)
        try:
            assert await caller.call('resume',1,0,'seller','Original prompt',config)==expected
            auth.access_token.assert_not_awaited(); send.assert_not_awaited()
            assert store.rows('SELECT * FROM api_attempts')==before
        finally: await caller.close(); store.close()
    asyncio.run(scenario())


def test_continue_failed_api_call_with_separate_wire_and_zero_cash_charge(tmp_path, monkeypatch):
    async def scenario():
        store=Store(tmp_path,budget=None); config=load_config(); create_run(store,'resume',config)
        saved_attempt(store,config,'failed'); prior=store.rows('SELECT * FROM api_attempts')[0]
        auth=AsyncMock(); auth.access_token.return_value='fake-subscription-token'
        caller=Caller(store,transport=subscription.TRANSPORT,subscription_auth=auth)
        send=AsyncMock(return_value=completed_response()); monkeypatch.setattr(subscription,'send',send)
        post=AsyncMock(side_effect=AssertionError('Paid API fallback')); monkeypatch.setattr(caller.client,'post',post)
        try:
            result=await caller.call('resume',1,0,'seller','Original prompt',config)
            assert result['price']==1.8
            rows=store.rows('SELECT * FROM api_attempts ORDER BY attempt')
            assert rows[0]==prior and rows[1]['attempt']==2
            assert rows[1]['request_hash']==prior['request_hash']
            assert rows[1]['cost']==rows[1]['reserved']==0
            wire=json.loads((store.root/'wire_requests/resume_1_0_seller_a2.json').read_text())
            assert wire['input']==[{'role':'user','content':'Original prompt'}]
            assert 'max_output_tokens' not in wire
            assert json.loads(rows[1]['usage'])['billing_path']=='chatgpt_subscription'
            post.assert_not_awaited()
        finally: await caller.close(); store.close()
    asyncio.run(scenario())


def test_auth_failure_preserves_attempt_allowance_and_never_falls_back(tmp_path, monkeypatch):
    async def scenario():
        store=Store(tmp_path,budget=None); config=load_config(); create_run(store,'resume',config)
        auth=AsyncMock(); auth.access_token.side_effect=RuntimeError('No authorization')
        caller=Caller(store,transport=subscription.TRANSPORT,subscription_auth=auth)
        post=AsyncMock(); monkeypatch.setattr(caller.client,'post',post)
        try:
            with pytest.raises(PermanentAPIError,match='official sign-in'):
                await caller.call('resume',1,0,'seller','Original prompt',config)
            assert store.rows('SELECT * FROM api_attempts')==[]
            post.assert_not_awaited()
        finally: await caller.close(); store.close()
    asyncio.run(scenario())
