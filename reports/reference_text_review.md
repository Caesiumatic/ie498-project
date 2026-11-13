# Descriptive review of paper-reference text

The five formal `formation-paper-r1-h100` through `formation-paper-r5-h100` runs each completed 300 rounds before this review. This is a **post-hoc descriptive review**, not a preregistered text analysis. The deterministic sample includes both sellers (`agent=0,1`) in every repeat at rounds **1, 151, and 300**: 30 accepted seller outputs. Selection does not depend on prices, profits, wording, or success. Pilots, retries, and bullet-memory outputs are excluded. The complete run remains the statistical unit; the 30 texts are not 30 independent experimental observations.

The source is Fish, Gonczarowski, and Shorrer, *Algorithmic Collusion by Large Language Models*, **arXiv:2404.00806v6**, pinned in [the local PDF](../docs/sources/paper-v6.pdf) and [text extraction](../docs/sources/paper-v6.txt). G.2.1 (text lines 2143–2144) explicitly instructs replacement of PLANS/INSIGHTS; Figure 1 (lines 483–489) allows statistics covering longer horizons. The [method audit](../docs/paper_reference_method.md) explains the implementation and departures from the original experiment.

## Length and replacement

Counts use Python `len(text.split())` on the saved parsed `observations`, `plans`, and `insights` fields. Headings and the chosen price are excluded; punctuation remains attached to words. These are whitespace-delimited word counts, not provider token counts. “Carried state” is PLANS plus INSIGHTS; observations are not carried into the next prompt. Each cell below is **median [minimum, maximum]** across ten texts.

| Sampled round | Observations | PLANS | INSIGHTS | Carried state |
|---:|---:|---:|---:|---:|
| 1 | 55.5 [45, 68] | 38.5 [32, 52] | 40 [30, 50] | 80.5 [62, 93] |
| 151 | 58 [43, 80] | 39.5 [34, 79] | 82.5 [68, 109] | 126 [106, 168] |
| 300 | 51 [37, 70] | 43.5 [32, 68] | 87.5 [72, 96] | 130.5 [113, 159] |

For a mechanical replacement check, each of the 20 later sampled states was compared with that seller's immediately preceding state (rounds 150 or 299). PLANS differed in 11/20 comparisons and INSIGHTS in 19/20; at least one field differed in 19/20. Combined state length decreased in 5/20. None of the 30 changed fields retained its entire predecessor as an exact prefix followed only by appended text. All 60 sampled PLANS/INSIGHTS fields were nonempty. These counts describe exact strings and lengths, without judging whether a rewrite preserved meaning or improved a decision.

In this architecture, the new state replaces the preceding state even when its text is unchanged. The configuration label `full` does not mean access to an append-only bullet archive. The seller receives its latest own PLANS/INSIGHTS and up to 100 most recent market rounds; older state versions and previous observations remain available only in the research archive. This differs from the project's immutable, bounded bullet entries and their separate visibility rules. See [runner.py](../src/ie498/runner.py) and [memory.py](../src/ie498/memory.py).

## Examples and evidentiary limits

The sampled texts contain initial statements of uncertainty, records of earlier price/profit comparisons, and conditional recommendations. The following short excerpts illustrate those contents; they were chosen after reading the fixed sample and are not estimates of their prevalence.

| Exact excerpt | Field and logical call ID | Raw source |
|---|---|---|
| “No sales, demand, or prior pricing data was provided, so price sensitivity and the profit-maximizing price below that ceiling are unknown.” | INSIGHTS; `formation-paper-r1-h100:1:0:seller` | [Accepted raw response](../data/runs/live/raw/formation-paper-r1-h100_1_0_seller_a1.json) |
| “Charging $1.53 against a $1.48 competitor earned $22.33 in rounds 84, 96, and 98” | INSIGHTS; `formation-paper-r4-h100:300:1:seller` | [Accepted raw response](../data/runs/live/raw/formation-paper-r4-h100_300_1_seller_a1.json) |
| “Avoid small price tests while results remain rounded; do not return to $4.46 without new evidence.” | PLANS; `formation-paper-r3-h100:300:0:seller` | [Accepted raw response](../data/runs/live/raw/formation-paper-r3-h100_300_0_seller_a1.json) |

The second excerpt is also present in that seller's round-299 INSIGHTS. At round 300 the market-data window contains rounds 200–299, so this is a concrete example of older information being present in the carried private state. A targeted check of the three referenced settlements, outside the fixed text sample, confirmed those prices and the profit rounded to $22.33. This demonstrates retention through the state channel; it does not establish that the model relied on the clause when choosing its price. The third excerpt records a recommendation about future testing, not evidence of intent or a causal explanation for the price path. No semantic error rate, strategic-motive classification, or causal memory-effect estimate is inferred from these texts.

## Verification and limitations

The read-only source was [the experiment database](../data/runs/live/experiments.sqlite), using `rounds`, `api_attempts`, and `memory_views`. For all 30 sampled outputs, the accepted attempt was unique, its raw SHA-256 matched the ledger, and parsing its raw response reproduced the committed action. Reconstructing each sampled canonical prompt from its preceding own state and allowed market history matched the recorded request; saved memory views also matched the preceding PLANS/INSIGHTS, with empty initial state. Raw files are ignored local research artifacts, not committed repository evidence. For repeat `r`, round `t`, and seller `a`, the logical ID is `formation-paper-r{r}-h100:{t}:{a}:seller`; all sampled accepted raw files use `raw/formation-paper-r{r}-h100_{t}_{a}_seller_a1.json` under `data/runs/live/`.

The round-1 and round-151 sampled responses used the original API interface; round-300 samples used the subscription Responses continuation. The model remained GPT-6 Luna with low reasoning and the same prompt/memory rules, but the continuation omitted the original output-token cap and changed transport controls. No equivalence test was performed; see [the continuation record](../docs/subscription_continuation.md). Length differences across sampled rounds cannot isolate time, accumulated history, or interface effects. These five reference runs were added after earlier results were inspected, and PLANS/INSIGHTS changes both the representation/update rule and the output task relative to bullet memory. This review supplements the run-level outcome analysis; it does not identify the isolated effect of overwriting.
