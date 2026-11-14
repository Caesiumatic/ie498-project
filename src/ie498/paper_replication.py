"""Offline reconstruction of the paper's core duopoly protocol.

This module has no inference, authentication, persistence, or suite-selection side
effects. It deliberately does not change the completed IE498 experiment. Source:
Fish et al., arXiv:2404.00806v6, sections 2/3, Appendix B and G.1/G.2.1.

The published text is not executable source code. RECONSTRUCTION_POLICIES records
choices where the paper does not completely specify implementation details. In
particular a caller must explicitly choose between the numerical ceiling rule in
footnote 18 and the scaled worked-example ceiling; neither is a hard price cap.
"""

from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re
from typing import Literal, Mapping, Sequence

import numpy as np

from .environment import Market


PROMPT_DIRECTORY = Path(__file__).resolve().parents[2] / "experiments/paper_replication/prompts"
PERIODS = 300
HISTORY_WINDOW = 100
MAX_CONSECUTIVE_MALFORMED = 10
MODEL = "gpt-6-luna"
RECONSTRUCTION_POLICIES = {
    "source": "arxiv:2404.00806v6 sections 2/3, Appendix B, G.1/G.2.1",
    "prompt_text": "PDF page furniture/indentation removed; original wording retained",
    "history_numbers": "str(round(float(value), 2)), as suggested by worked examples",
    "currency_numbers": "cost uses general decimal format; ceiling uses str(round(value, 2))",
    "state": "latest own PLANS/INSIGHTS only; parsed outer whitespace stripped",
    "parser": "four ordered literal headings; exactly one number in final price field; prose allowed",
    "price_domain": "finite nonnegative real; no rounding or ceiling clamp",
    "retry": "stop after ten consecutive malformed completed outputs; transport failures are separate",
    "sampling": "temperature 1; Luna reasoning none to retain temperature compatibility",
    "output_limit": "no added token cap; paper does not specify one",
    "scope": "no suite or number of repetitions selected by this module",
}


@dataclass(frozen=True)
class PaperCondition:
    prefix: Literal["P1", "P2"]
    alpha: float
    ceiling_policy: Literal["footnote_18", "worked_example_scaled"]

    def __post_init__(self):
        if self.prefix not in ("P1", "P2"):
            raise ValueError("Core duopoly conditions use P1 or P2")
        if isinstance(self.alpha, bool) or self.alpha not in (1, 3.2, 10):
            raise ValueError("Paper currency scale must be 1, 3.2, or 10")
        if self.ceiling_policy not in ("footnote_18", "worked_example_scaled"):
            raise ValueError("Choose and record an explicit ceiling reconstruction policy")

    @property
    def market(self):
        return Market(alpha=float(self.alpha))

    @property
    def ceiling(self):
        if self.ceiling_policy == "worked_example_scaled":
            return 4.51 * self.alpha
        return 2.34 * _joint_price(float(self.alpha))


@lru_cache(maxsize=3)
def _joint_price(alpha):
    return float(Market(alpha=alpha).benchmarks()["joint_price"][0])


def _validate_price(price):
    if isinstance(price, bool) or not isinstance(price, (float, int)):
        raise ValueError("Price must be a finite nonnegative real number")
    price = float(price)
    if not math.isfinite(price) or price < 0:
        raise ValueError("Price must be a finite nonnegative real number")
    return price


@dataclass(frozen=True)
class PaperDecision:
    observations: str
    plans: str
    insights: str
    price: float

    def __post_init__(self):
        if not all(isinstance(x, str) for x in (self.observations, self.plans, self.insights)):
            raise ValueError("Output text fields must be strings")
        _validate_price(self.price)


_HEADINGS = (
    "My observations and thoughts:",
    "New content for PLANS.txt:",
    "New content for INSIGHTS.txt:",
    "My chosen price:",
)
_HEADING_PATTERN = re.compile(
    r"^[ \t]*(" + "|".join(re.escape(x) for x in _HEADINGS) + r")[ \t]*", re.M
)
_NUMBER_PATTERN = re.compile(
    r"(?<![\w.])[-+−]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?(?!\w|\.\d)"
)


def parse_decision(text: str) -> PaperDecision:
    """Parse the published template, including a price written in a sentence.

    An ambiguous final field containing multiple numbers is rejected rather than
    guessing. No correction prompt or modified sampling request is introduced.
    Original raw output should be retained by the caller before parsing.
    """
    if not isinstance(text, str):
        raise ValueError("Output must be text")
    headings = list(_HEADING_PATTERN.finditer(text))
    if tuple(m[1] for m in headings) != _HEADINGS or text[:headings[0].start()].strip():
        raise ValueError("Output lacks the four ordered template headings")
    contents = [
        text[match.end():headings[i + 1].start() if i + 1 < len(headings) else len(text)].strip()
        for i, match in enumerate(headings)
    ]
    numbers = list(_NUMBER_PATTERN.finditer(contents[3]))
    if len(numbers) != 1:
        raise ValueError("Final price field must contain exactly one unambiguous number")
    price = _validate_price(float(numbers[0][0].replace(",", "").replace("−", "-")))
    return PaperDecision(*contents[:3], price)


@dataclass
class MalformedOutputStreak:
    """Track completed malformed responses, independently of transport errors."""

    consecutive: int = 0

    def __post_init__(self):
        if type(self.consecutive) is not int or not 0 <= self.consecutive <= MAX_CONSECUTIVE_MALFORMED:
            raise ValueError("Invalid restored malformed-output streak")

    @property
    def stopped(self):
        return self.consecutive >= MAX_CONSECUTIVE_MALFORMED

    def note_malformed(self):
        if self.stopped:
            raise RuntimeError("Run already stopped after ten consecutive malformed outputs")
        self.consecutive += 1
        return self.stopped

    def note_valid(self):
        if self.stopped:
            raise RuntimeError("A stopped run cannot silently resume")
        self.consecutive = 0


def _validate_history(history):
    if any(row.get("t") != t for t, row in enumerate(history, 1)):
        raise ValueError("History must contain consecutive completed periods from period 1")


def history_text(history: Sequence[Mapping], seller: int) -> str:
    if seller not in (0, 1):
        raise ValueError("Duopoly seller must be 0 or 1")
    _validate_history(history)

    def number(value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("History values must be finite")
        return str(round(value, 2))

    return "\n".join(
        f"Round {row['t']}:\n"
        f"    - My price: {number(row['prices'][seller])}\n"
        f"    - Competitor's price: {number(row['prices'][1-seller])}\n"
        f"    - My quantity sold: {number(row['quantities'][seller])}\n"
        f"    - My profit earned: {number(row['profits'][seller])}"
        for row in reversed(history[-HISTORY_WINDOW:])
    )


_PLACEHOLDER_PATTERN = re.compile(
    r"\[Prompt Prefix\]|\[Marginal Cost\]|\[Maximum Willingness To Pay\]|\[PLANS\]|\[INSIGHTS\]|\[HISTORY\]"
)


def build_round_prompts(condition: PaperCondition, history: Sequence[Mapping]) -> tuple[str, str]:
    """Return both complete inputs before either agent's current action exists."""
    _validate_history(history)
    if len(history) >= PERIODS:
        raise ValueError("The 300-period run is already complete")
    prefix = (PROMPT_DIRECTORY / f"{condition.prefix.lower()}.txt").read_text().strip()
    template = (PROMPT_DIRECTORY / "template.txt").read_text()
    prompts = []
    for seller in (0, 1):
        state = history[-1]["actions"][seller] if history else {"plans": "", "insights": ""}
        if isinstance(state, PaperDecision):
            state = asdict(state)
        values = {
            "[Prompt Prefix]": prefix,
            "[Marginal Cost]": f"${condition.alpha:g}",
            "[Maximum Willingness To Pay]": f"${round(condition.ceiling, 2)}",
            "[PLANS]": state["plans"],
            "[INSIGHTS]": state["insights"],
            "[HISTORY]": history_text(history, seller),
        }
        if not all(isinstance(value, str) for value in values.values()):
            raise ValueError("Carried private files must be strings")
        # Substitution scans only the template, never inserted model text.
        prompts.append(_PLACEHOLDER_PATTERN.sub(lambda match: values[match[0]], template))
    return tuple(prompts)


def settle_round(condition: PaperCondition, t: int, decisions: Sequence[PaperDecision]) -> dict:
    if type(t) is not int or not 1 <= t <= PERIODS or len(decisions) != 2:
        raise ValueError("A core round needs two decisions and a period from 1 to 300")
    prices = [_validate_price(decision.price) for decision in decisions]
    quantities, profits = condition.market.settle(prices)
    return {
        "t": t,
        "prices": prices,
        "quantities": quantities.tolist(),
        "profits": profits.tolist(),
        "actions": [asdict(decision) for decision in decisions],
        "ceiling_exceeded": [price > condition.ceiling for price in prices],
    }


def normalized_final_metrics(condition: PaperCondition, history: Sequence[Mapping]) -> dict:
    """Paper Figure 2 quantities; no project-specific success classifications."""
    _validate_history(history)
    if len(history) != PERIODS:
        raise ValueError("Final paper summaries require a complete 300-period run")
    prices = np.asarray([row["prices"] for row in history[-50:]], dtype=float) / condition.alpha
    profits = np.asarray([row["profits"] for row in history[-50:]], dtype=float) / condition.alpha
    if prices.shape != (50, 2) or profits.shape != (50, 2) or not np.isfinite(prices).all() or not np.isfinite(profits).all():
        raise ValueError("Final history must contain finite two-firm prices/profits")
    benchmark = condition.market.benchmarks()
    return {
        "prefix": condition.prefix,
        "alpha": condition.alpha,
        "evaluation_periods": [251, 300],
        "mean_normalized_prices": prices.mean(axis=0).tolist(),
        "mean_normalized_profits": profits.mean(axis=0).tolist(),
        "mean_normalized_total_profit": float(profits.sum(axis=1).mean()),
        "mean_normalized_profit_difference": float((profits[:, 0] - profits[:, 1]).mean()),
        "normalized_nash_prices": (np.asarray(benchmark["nash_price"]) / condition.alpha).tolist(),
        "normalized_nash_profits": (np.asarray(benchmark["nash_profit"]) / condition.alpha).tolist(),
        "normalized_joint_monopoly_prices": (np.asarray(benchmark["joint_price"]) / condition.alpha).tolist(),
        "normalized_joint_monopoly_total_profit": float(sum(benchmark["joint_profit"]) / condition.alpha),
    }


def api_request(prompt: str, *, interface: Literal["chat_completions", "responses"]) -> dict:
    """Build a temperature-preserving API request, without selecting billing.

    This is NOT the existing subscription converter. A transport that cannot send
    temperature=1 must reject this contract, never remove the field silently.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("A nonempty single user prompt is required")
    common = {"model": MODEL, "temperature": 1, "store": False}
    if interface == "chat_completions":
        return {**common, "reasoning_effort": "none", "messages": [{"role": "user", "content": prompt}]}
    if interface == "responses":
        return {**common, "reasoning": {"effort": "none"}, "input": [{"role": "user", "content": prompt}]}
    raise ValueError("Unknown API interface; no automatic substitution is permitted")


def prompt_hashes() -> dict[str, str]:
    """Hash only this independent protocol's four prompt source files."""
    return {
        name: hashlib.sha256((PROMPT_DIRECTORY / name).read_bytes()).hexdigest()
        for name in ("p0.txt", "p1.txt", "p2.txt", "template.txt")
    }
