import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from ie498.agents import Caller, PermanentAPIError
from ie498.cli import load_config
from ie498.runner import create_run
from ie498.storage import Store


def test_exhausted_credit_429_stops_without_retry(tmp_path,monkeypatch):
    async def scenario():
        store=Store(tmp_path,budget=None)
        config=load_config();create_run(store,'quota-test',config)
        caller=Caller(store)
        response=httpx.Response(429,json={'error':{'type':'insufficient_quota','code':'credit_balance_exhausted','message':'No credits remaining'}})
        post=AsyncMock(return_value=response)
        monkeypatch.setattr(caller.client,'post',post)
        monkeypatch.setenv('OPENAI_API_KEY','test-only-not-a-real-key')
        try:
            with pytest.raises(PermanentAPIError,match='credit_balance_exhausted'):
                await caller.call('quota-test',1,0,'seller','Test prompt',config)
            assert post.await_count==1
            assert store.spending()=={'spent':0.0,'reserved':0,'budget':None}
            assert store.rows('SELECT status FROM api_attempts')==[{'status':'failed'}]
        finally:
            await caller.close();store.close()
    asyncio.run(scenario())
