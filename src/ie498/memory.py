"""Construct seller-visible feedback and memory views from immutable archives."""
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKEN_MEASURE = "utf8_byte_upper_bound"


def tokens(text):
    # UTF-8 byte length is the offline token-count upper bound.
    # Keep this estimate separate from provider-reported usage in the cost ledger.
    return len(text.encode('utf-8'))


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def visible_history(history, h, agent):
    if h < 0:
        raise ValueError("Negative history window")
    selected = [] if h == 0 else history[-h:]
    return "\n".join(
        f"Round {r['t']}:\n    - My price: {r['prices'][agent]:.2f}\n"
        f"    - Competitor's price: {r['prices'][1-agent]:.2f}\n"
        f"    - My quantity sold: {r['quantities'][agent]:.2f}\n"
        f"    - My profit earned: {r['profits'][agent]:.2f}"
        for r in reversed(selected))


def validate_bullet(text):
    if not isinstance(text, str) or not text.startswith("- ") or "\n" in text or "\r" in text:
        raise ValueError("Expected one single-line '- ' bullet")
    body = text[2:]
    if not body.strip() or len(body.split()) > 60:
        raise ValueError("Bullet must contain 1–60 words")
    # Protect decimals and common abbreviations before counting sentence endings.
    protected = re.sub(r"(?<=\d)\.(?=\d)", "¤", body)
    protected = re.sub(r"\b(?:e\.g\.|i\.e\.|Mr\.|Ms\.|Dr\.|vs\.|etc\.|U\.S\.)",
                       lambda m: m[0].replace(".", "¤"), protected, flags=re.I)
    ends = list(re.finditer(r"[.!?]+(?=\s|$)", protected))
    if len(ends) != 1 or protected[ends[0].end():].strip():
        raise ValueError("Bullet must contain exactly one complete sentence")
    return text


def validate_price(price):
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
        raise ValueError("Price must be a finite nonnegative number")
    return float(price)


def parse_output(text, purpose, architecture):
    if architecture == "paper_reference" and purpose == "seller":
        match = re.fullmatch(
            r"\s*My observations and thoughts:\s*(.*?)\s*New content for PLANS\.txt:\s*(.*?)"
            r"\s*New content for INSIGHTS\.txt:\s*(.*?)\s*My chosen price:\s*"
            r"([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*", text, re.S)
        if not match:
            raise ValueError("Paper output does not match G.2.1 template")
        return dict(observations=match[1], plans=match[2], insights=match[3], price=validate_price(float(match[4])))
    result = json.loads(text)
    expected = {"memory_bullet"} if purpose == "compressor" else {"memory_bullet", "price"}
    if not isinstance(result, dict) or set(result) != expected:
        raise ValueError("Unexpected output fields")
    validate_bullet(result["memory_bullet"])
    if purpose == "seller":
        validate_price(result["price"])
    return result


def build_seller(config, history_text, memory_view, paper_state=None):
    prefix = (ROOT / "prompts/p1-original.txt").read_text().strip()
    if config["architecture"] == "paper_reference":
        state = paper_state or {"plans": "", "insights": ""}
        template = (ROOT / "prompts/paper-template.txt").read_text()
        for key, value in {"[Prompt Prefix]": prefix, "[Marginal Cost]": "$1", "[Maximum Willingness To Pay]": "$4.51",
                           "[PLANS]": state["plans"], "[INSIGHTS]": state["insights"], "[HISTORY]": history_text}.items():
            template = template.replace(key, value)
        return template
    prefix = prefix.replace("files\n(written by a previous copy of yourself)",
                            "strategic memory\n(written by previous copies of yourself)")
    return (prefix + "\n\n" + (ROOT / "prompts/bullet-seller.txt").read_text()
            .replace("[MEMORY]", memory_view).replace("[HISTORY]", history_text))


def build_compressor(archive):
    return (ROOT / "prompts/compressor.txt").read_text() + "\n\n" + "\n".join(archive)


def prompt_hash():
    return digest({p.name: p.read_text() for p in sorted((ROOT / "prompts").glob("*.txt"))})
