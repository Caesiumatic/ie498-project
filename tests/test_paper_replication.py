"""Offline behavioral checks for the independent paper protocol reconstruction."""

from dataclasses import replace
import math

import pytest

from ie498.paper_replication import (
    MalformedOutputStreak, PaperCondition, PaperDecision, api_request,
    build_round_prompts, history_text, normalized_final_metrics, parse_decision,
    prompt_hashes, settle_round,
)


def condition(alpha=1, prefix="P1"):
    return PaperCondition(prefix=prefix, alpha=alpha, ceiling_policy="footnote_18")


def decision(price, plans="", insights="", observations="PRIVATE_THOUGHT"):
    return PaperDecision(observations, plans, insights, price)


def output(price="I choose a price of $1.75 per unit.", plans="A plan.", insights="An insight."):
    return ("My observations and thoughts:\nThink.\nNew content for PLANS.txt:\n"
            f"{plans}\nNew content for INSIGHTS.txt:\n{insights}\nMy chosen price:\n{price}")


def test_published_market_examples_and_currency_scaling():
    # Appendix G.2.3, period 9: two prices of 1.8, quantity 40.83, profit 32.66.
    base = settle_round(condition(), 1, [decision(1.8), decision(1.8)])
    assert round(base["quantities"][0], 2) == 40.83
    assert round(base["profits"][0], 2) == 32.66
    # Same appendix, period 1: own 1.5, competitor 3.75, quantity 88.07.
    asymmetric = settle_round(condition(), 1, [decision(1.5), decision(3.75)])
    assert round(asymmetric["quantities"][0], 2) == 88.07
    assert round(asymmetric["profits"][0], 2) == 44.04
    for alpha in (3.2, 10):
        scaled = settle_round(condition(alpha), 1, [decision(1.5 * alpha), decision(3.75 * alpha)])
        assert scaled["quantities"] == pytest.approx(asymmetric["quantities"])
        assert [p / alpha for p in scaled["profits"]] == pytest.approx(asymmetric["profits"])


def test_private_overwrite_history_window_and_no_thought_carryover():
    history = []
    for t in range(1, 102):
        actions = [decision(1.8, f"OLD_{i}_{t}", f"INSIGHT_{i}_{t}") for i in (0, 1)]
        if t == 101:
            actions = [decision(1.8, "", f"LATEST_ONLY_{i}") for i in (0, 1)]
        history.append(settle_round(condition(), t, actions))
    prompts = build_round_prompts(condition(), history)
    for seller, prompt in enumerate(prompts):
        assert prompt.count("Round ") == 100
        assert "Round 1:" not in prompt and "Round 2:" in prompt
        assert prompt.index("Round 101:") < prompt.index("Round 2:")
        assert f"LATEST_ONLY_{seller}" in prompt
        assert f"LATEST_ONLY_{1-seller}" not in prompt
        assert "OLD_" not in prompt and "PRIVATE_THOUGHT" not in prompt
        assert "My price: 1.8\n" in prompt
    # Immutable input snapshots remain unchanged after another action is produced.
    history.append(settle_round(condition(), 102, [decision(2), decision(2)]))
    assert "Round 102:" not in prompts[0]


def test_carried_placeholders_and_long_multiline_files_are_literal():
    plans = "[INSIGHTS] [HISTORY] [Prompt Prefix]\n" + "word " * 120
    insights = "[PLANS] [Maximum Willingness To Pay]"
    history = [settle_round(condition(), 1, [decision(1.8, plans, insights), decision(1.9)])]
    own, other = build_round_prompts(condition(), history)
    assert plans in own and insights in own
    assert plans not in other and insights not in other


def test_published_prefixes_and_currency_information():
    p1, p1_other = build_round_prompts(condition(3.2), [])
    p2, _ = build_round_prompts(condition(3.2, "P2"), [])
    assert p1 == p1_other
    assert "cost I pay to produce each unit is $3.2." in p1
    assert "you should not take actions which undermine\nprofitability." in p1
    assert "including possibly\nrisky or aggressive options for data-gathering purposes" in p2
    assert "lower than your competitor will typically lead to more product sold." in p2
    assert "will overwrite any existing\ncontent" in p2
    assert set(prompt_hashes()) == {"p0.txt", "p1.txt", "p2.txt", "template.txt"}


@pytest.mark.parametrize("price,expected", [("$1.75", 1.75), ("The price is 1.75 dollars.", 1.75),
                                              ("My chosen price is $1.75.", 1.75),
                                              ("+2e-1", .2), ("$1,234.567", 1234.567)])
def test_parser_accepts_unambiguous_price_in_prose(price, expected):
    parsed = parse_decision(output(price))
    assert parsed.price == expected
    assert parsed.plans == "A plan." and parsed.insights == "An insight."


@pytest.mark.parametrize("price", ["$1.75 or $2.00", "-0.5", "−0.5", "1.2.3", "NaN", "inf", "1e999", "no price"])
def test_parser_rejects_ambiguous_or_invalid_prices(price):
    with pytest.raises(ValueError):
        parse_decision(output(price))


def test_parser_preserves_empty_files_and_rejects_missing_headers():
    parsed = parse_decision(output(plans="", insights=""))
    assert parsed.plans == parsed.insights == ""
    with pytest.raises(ValueError):
        parse_decision(output().replace("New content for INSIGHTS.txt:", "Insight:"))
    with pytest.raises(ValueError):
        parse_decision("")


def test_no_price_clamp_or_action_rounding_and_explicit_ceiling_policy():
    c = condition()
    row = settle_round(c, 1, [decision(10.123456789), decision(1.777777)])
    assert row["prices"] == [10.123456789, 1.777777]
    assert row["ceiling_exceeded"] == [True, False]
    example = replace(c, ceiling_policy="worked_example_scaled")
    assert example.ceiling == 4.51
    assert not math.isclose(c.ceiling, example.ceiling, abs_tol=.001)
    with pytest.raises(ValueError):
        PaperCondition("P1", 1, "unknown")


def test_ten_consecutive_malformed_outputs_stop_without_hidden_transport_counter():
    streak = MalformedOutputStreak()
    for _ in range(9):
        assert not streak.note_malformed()
    streak.note_valid()
    assert streak.consecutive == 0
    for _ in range(9):
        assert not streak.note_malformed()
    assert streak.note_malformed()
    assert streak.stopped
    with pytest.raises(RuntimeError):
        streak.note_valid()
    with pytest.raises(RuntimeError):
        streak.note_malformed()


def test_final_50_statistics_use_only_last_window_and_normalize_currency():
    c = condition(10)
    history = [settle_round(c, t, [decision(15 if t <= 250 else 18), decision(15 if t <= 250 else 19)])
               for t in range(1, 301)]
    result = normalized_final_metrics(c, history)
    assert result["evaluation_periods"] == [251, 300]
    assert result["mean_normalized_prices"] == pytest.approx([1.8, 1.9])
    final = history[-1]["profits"]
    assert result["mean_normalized_total_profit"] == pytest.approx(sum(final) / 10)
    assert result["mean_normalized_profit_difference"] == pytest.approx((final[0] - final[1]) / 10)
    assert not {"effective_success", "price_success", "CI"} & result.keys()
    with pytest.raises(ValueError):
        normalized_final_metrics(c, history[:-1])
    with pytest.raises(ValueError):
        build_round_prompts(c, history)


def test_requests_retain_original_temperature_and_stateless_user_prompt():
    prompt = "The exact prompt."
    chat = api_request(prompt, interface="chat_completions")
    responses = api_request(prompt, interface="responses")
    assert chat["messages"] == responses["input"] == [{"role": "user", "content": prompt}]
    assert chat["temperature"] == responses["temperature"] == 1
    assert chat["reasoning_effort"] == responses["reasoning"]["effort"] == "none"
    forbidden = {"tools", "response_format", "previous_response_id", "max_completion_tokens", "max_output_tokens"}
    assert not forbidden & chat.keys() and not forbidden & responses.keys()
    with pytest.raises(ValueError):
        api_request(prompt, interface="subscription")


def test_incomplete_or_invalid_history_cannot_silently_change_round_identity():
    row = settle_round(condition(), 2, [decision(1.8), decision(1.8)])
    with pytest.raises(ValueError):
        history_text([row], 0)
    with pytest.raises(ValueError):
        build_round_prompts(condition(), [row])
