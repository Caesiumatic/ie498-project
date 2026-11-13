"""Behavioral contracts for the original paper's overwritten private files."""
import asyncio
import json

from ie498.agents import Caller, request_body
from ie498.cli import load_config
from ie498.memory import build_seller, parse_output, visible_history
from ie498.runner import create_run, run_batch
from ie498.storage import Store


def test_paper_overwrites_and_deletes_private_state(tmp_path, monkeypatch):
    config = load_config()
    config.update(architecture='paper_reference', H=100, mode='full',
                  provider='mock', stage='mock', T=3)
    original_mock = Caller.mock

    def changing_files(call_id, body, config, purpose):
        _, round_number, agent, _ = call_id.split(':')
        t = int(round_number)
        result = original_mock(call_id, body, config, purpose)
        if t == 1:
            plans = f'PRIVATE_{agent}_OLD_PLAN ' + ' '.join(f'word{i}' for i in range(75)) + '.\nSecond sentence.'
            insights = f'PRIVATE_{agent}_OLD_INSIGHT.'
        elif t == 2:
            plans = ''  # Deleting a file must not reveal its old contents next round.
            insights = f'PRIVATE_{agent}_REVISED_INSIGHT.'
        else:
            plans = 'A fresh plan.'
            insights = ''
        result['choices'][0]['message']['content'] = (
            f'My observations and thoughts:\nTHOUGHT_{agent}_{t}.\n'
            f'New content for PLANS.txt:\n{plans}\n'
            f'New content for INSIGHTS.txt:\n{insights}\nMy chosen price:\n1.75')
        return result

    monkeypatch.setattr(Caller, 'mock', staticmethod(changing_files))
    store = Store(tmp_path / 'paper')
    try:
        create_run(store, 'paper', config)
        asyncio.run(run_batch(store, ['paper']))
        assert store.rows("SELECT status FROM runs WHERE id='paper'")[0]['status'] == 'completed'
        history = store.history('paper')
        assert len(history[0]['actions'][0]['plans'].split()) > 60
        assert history[1]['actions'][0]['plans'] == ''
        assert history[2]['actions'][0]['insights'] == ''
        assert store.archive('paper', 0) == []
        requests = store.rows('SELECT t,agent,purpose,request_json FROM api_attempts ORDER BY t,agent')
        assert len(requests) == 6
        for row in requests:
            assert row['purpose'] == 'seller'
            t, agent = row['t'], row['agent']
            body = json.loads(row['request_json'])
            text = body['messages'][0]['content']
            assert f'PRIVATE_{1-agent}_' not in text
            assert 'THOUGHT_' not in text
            if t == 1:
                assert 'PRIVATE_' not in text
            elif t == 2:
                assert f'PRIVATE_{agent}_OLD_PLAN' in text
                assert f'PRIVATE_{agent}_OLD_INSIGHT' in text
            else:
                assert 'OLD_PLAN' not in text and 'OLD_INSIGHT' not in text
                assert f'PRIVATE_{agent}_REVISED_INSIGHT' in text
        # The research archive still preserves overwritten content for audit.
        assert 'OLD_PLAN' in history[0]['actions'][0]['plans']
    finally:
        store.close()


def test_paper_history_window_and_stateless_request():
    config = load_config()
    config.update(architecture='paper_reference', H=100, mode='full')
    history = [dict(t=t, prices=[1.75, 1.80], quantities=[30, 40], profits=[22.5, 32])
               for t in range(1, 151)]
    visible = visible_history(history, config['H'], 0)
    assert visible.count('Round ') == 100
    assert 'Round 50:' not in visible and 'Round 51:' in visible
    assert visible.index('Round 150:') < visible.index('Round 51:')
    assert 'My quantity sold: 30.00' in visible
    assert 'My quantity sold: 40.00' not in visible
    prompt = build_seller(config, visible, '', {'plans': '', 'insights': ''})
    body = request_body(config, prompt, 'seller')
    assert body['messages'] == [{'role': 'user', 'content': prompt}]
    assert body['store'] is False
    assert body['max_completion_tokens'] == config['paper_output_limit']
    assert not {'response_format', 'tools', 'conversation', 'conversation_id',
                'previous_response_id'} & body.keys()
    assert 'will overwrite any existing' in prompt
    # Empty files are valid rather than silently restored from older versions.
    output = ('My observations and thoughts:\nReconsider the strategy.\n'
              'New content for PLANS.txt:\n\nNew content for INSIGHTS.txt:\n\n'
              'My chosen price:\n1.75')
    parsed = parse_output(output, 'seller', 'paper_reference')
    assert parsed['plans'] == parsed['insights'] == ''
