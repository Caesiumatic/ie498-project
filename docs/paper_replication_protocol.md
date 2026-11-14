# Original-paper replication: protocol audit

**Status: PREPARATION. No empirical runs have been generated for this new replication.**

This document records a fresh reading of the source paper in response to the user's request to reproduce its method with GPT-6 Luna and a single repetition instead of the original repeated sample. The user has selected the six-condition main experiment and the Pro subscription route with reasoning `none`, explicitly accepting and recording that temperature and top_p cannot be set on that route. This is an audit and preparation document, not a claim that a strict replication has already been implemented.

The new request supersedes the previous project's five-repeat design for this separate experiment. Existing experiments, reports, configurations, accepted responses, and checkpoints remain historical evidence. They must not be relabeled as the new replication or silently modified to satisfy its protocol.

## Source and evidence

The source reviewed is Fish, Gonczarowski, and Shorrer, *Algorithmic Collusion by Large Language Models*, arXiv:2404.00806v6: cover dated August 20, 2026; arXiv revision dated August 31, 2026. The pinned [PDF](sources/paper-v6.pdf), [text extraction](sources/paper-v6.txt), and [source manifest](sources/manifest.json) are already retained in the repository. All line numbers below refer to that fixed text extraction, not to an independently reflowed copy. The PDF SHA-256 is `ca3b9ca28ccaa40e550d848cfe4d641a470b073b22adc34c584f9b19a6228482`.

The main experiment is the original GPT-4-0613 duopoly experiment in Section 3. Appendix A.5 is a later GPT-5.2/high-reasoning experiment with different message roles. These are distinct source protocols; they must not be combined without disclosure.

## Confirmed scope: six main-experiment conditions

The paper conducts **21 runs per prompt prefix**, comprising **seven runs at each of three currency scales**, not 21 repetitions of one fixed-scale condition. With P1 and P2, the original main experiment contains 42 runs. This is explicit in Section 3, lines 520–529, and Figure 2's notes, lines 583–592.

The user selected **one run per main-experiment condition**: P1/P1 and P2/P2, each at alpha 1, 3.2, and 10, for six independent 300-period runs. This is **1,800 market periods and 3,600 successful seller calls**, excluding failed attempts. Each trajectory starts with empty history and empty private files. No mechanism-call experiments or appendix market experiments are included.

The following alternatives were distinguished when clarifying the request; they are retained here to make the selected scope explicit:

| Scope option | New experimental sample | What it preserves or changes |
| --- | --- | --- |
| One run per prompt prefix | Two 300-period runs, one P1/P1 and one P2/P2 | A currency-scale selection rule must also be specified. This does not retain the original balanced coverage of all three scales. |
| **Selected: one run per original main-experiment condition** | Six 300-period runs: P1/P1 and P2/P2, each at alpha 1, 3.2, and 10 | Preserves all six main-experiment conditions while reducing within-condition repetitions from seven to one. |
| Full-paper replication with reduced repetitions | Main experiment plus separately specified mechanism experiments and appendix treatments | Requires an explicit reduction rule for experiments whose original repetition counts are 3, 4, 7, 12, or 20, and decisions about additional analysis models. |

A literal single trajectory would additionally require selecting one prompt prefix and one currency scale, omitting the paper's main P1/P2 comparison. It should not be described as the complete main experiment.

The scope and service are now confirmed. The mechanism and appendix sections below are an exclusion inventory and source audit, not authorization to add those experiments. Execution follows completion of the offline implementation and recovery checks; no additional sampling-equivalence experiment is part of this scope.

## Core experimental contract

| Component | Source specification | Evidence |
| --- | --- | --- |
| Horizon and interaction | Two independently acting sellers set prices simultaneously for 300 periods. Current-period actions depend on the state preceding that period. | Section 2, lines 322–329; Figure 1, lines 483–489 |
| Currency scales | alpha in {1, 3.2, 10}, equally represented in the main sample | Section 2.1, lines 350–354; Figure 2, lines 583–584 |
| Demand | `q_i = beta * exp((a_i - p_i / alpha) / mu) / (exp(a_0 / mu) + sum_j exp((a_j - p_j / alpha) / mu))` | Section 2.1, lines 331–347 |
| Main-market parameters | beta=100, a_1=a_2=2, a_0=0, mu=0.25, c_1=c_2=1 | Section 2.1, lines 350–367 |
| Profit | `profit_i = (p_i - alpha * c_i) * q_i`; the actual marginal cost is alpha | Section 2.1, lines 361–367 |
| Agent information | Product marginal cost, a textual willingness-to-pay ceiling, recent market history, its own carried plans and insights, and output instructions; no demand formula or solution benchmarks are provided to the seller | Section 2.2, lines 408–425; G.2.1, lines 2089–2144 |
| Market history | Most recent min(100, t-1) periods: both prices, own quantity, own profit, rounded to two decimal digits | Section 2.2, lines 416–418 |
| History order | Most recent period first in the supplied worked example | G.2.3, lines 2273–2321 |
| Private state | Only the seller's preceding PLANS.txt and INSIGHTS.txt contents are carried forward. The next response replaces both contents; old information survives only if retained in the new state. | Section 2.2, lines 419–425; G.2.1, lines 2100–2144 |
| Output task | Observations and thoughts, new PLANS, new INSIGHTS, then chosen price; no one-sentence bullet requirement, 60-word limit, or separate compressor | G.2.1, lines 2100–2108 and 2130–2144 |
| Prompt treatments | Exact named P1 and P2 prefixes from G.1, with the G.2.1 body | G.1, lines 2031–2062; G.2.1, lines 2089–2144 |
| Core message format | Prefix prepended to the rest of the prompt in a single user message; independent calls, without transcript carryover | Section 2.2, lines 419–425; Appendix B, lines 1864–1867 |
| Original model | GPT-4-0613 | Appendix B, lines 1844–1845 |
| Original sampling | Temperature 1 | Appendix B, lines 1847–1849 |
| Output parsing | Follow the requested sections; extract the price using string parsing even when the final field contains sentence text | Appendix B, lines 1851–1855 |
| Malformed-output stopping | Stop the experimental run after 10 consecutive malformed-output failures | Appendix B, lines 1857–1862 |

There is no stated terminal-period announcement in the general prompt. Implementing a 300-period horizon does not authorize adding a countdown, an announced final period, or instructions about end-game behavior.

Simultaneous pricing requires both sellers' period-t inputs to be fixed before either period-t action can affect state. Independent network requests may overlap without changing that information structure. Recovery must preserve accepted logical-call responses and the original state from which a partially completed period began.

## Sampling and source ambiguities that prevent an unqualified identity claim

The user authorizes a model substitution and a smaller sample. That does not establish that all other properties of the available implementation or service match the original experiment.

1. **Price-ceiling inconsistency and selected interpretation.** Footnote 18, lines 438–444, defines the textual ceiling as `2.34 * pM`, where pM is the common price maximizing the total profit of a monopolist controlling both products. The multiplier 2.34 was drawn from Uniform[1.5, 2.5]. G.2.2's alpha=1 example instead displays $4.51 (lines 2160–2164). Computing the formula precisely produces approximately $4.50446. This replication takes the explicitly stated methodological formula in Footnote 18 as primary: compute `2.34 * pM` at each alpha, retaining the fixed multiplier 2.34 rather than drawing a new one. The exact value and the text-rendered value must both be recorded in the frozen configuration. The worked-example discrepancy remains a disclosed source ambiguity.
2. **A textual ceiling is not a documented action clamp.** The source calls it text intended to deter high prices (lines 413–415). It does not prescribe silently replacing a model's chosen price with a bounded value. A hard price clamp, rejection rule for negative or excessive prices, or maximum price different from the stated prompt cannot be attributed to the paper without further evidence.
3. **Displayed numbers versus numerical state.** The source requires two-decimal rounding for feedback, but its worked example includes `1.8`, `2.0`, and `9.0` rather than uniformly fixed-width decimals (lines 2273–2321). It does not specify the exact serialization implementation, whether an action with additional decimal places is rounded before settlement, or how decimal ties are resolved. Display rounding must not silently become settlement rounding.
4. **Named prefixes versus worked examples.** The exploratory prefix in G.2.2/G.2.3 differs from the explicitly named P1/P2 in G.1. The named treatments should follow G.1, with this source discrepancy retained in the record; a convenient example should not silently replace the treatment text.
5. **Parser and retry details.** The paper allows prices embedded in sentence text but does not publish an exact regular expression in Appendix B. It says both “retried up to 10 times” and “10 consecutive failures” cause stopping. The latter is a clear stopping condition; treating this as eleven allowed malformed outputs would need justification. Network failures, interrupted streams, and malformed model outputs should be distinguished rather than assuming the same original retry policy covers all three.
6. **Unspecified original controls.** The paper does not state an output-token cap, random seed, top-p value, frequency or presence penalties, or exact API timeout policy. Absence from the manuscript is not evidence of an arbitrary value or of an unlimited original output budget.
7. **Reasoning and interface differences; subscription route selected.** GPT-4-0613 has no documented low-reasoning setting in this protocol. The retrieved official [model parameter guidance](sources/latest-model.html) requires reasoning `none` to set temperature for the relevant model family. The standard API can be configured with reasoning `none`, temperature=1, and top_p=1; the manuscript explicitly specifies only temperature, so top_p=1 would be a declared default-selection choice rather than a directly documented paper parameter. The user selected the **Pro subscription route with reasoning `none`** and explicitly accepted its prohibition on setting temperature and top_p. Those fields are therefore omitted from the subscription request, and any returned server values are retained as observations, not assumed matches to the source study. Prior project subscription responses report temperature=1.0 and top_p=0.98 alongside low reasoning; this does not prove what defaults a new reasoning-`none` request will use or that sampling matches GPT-4-0613. This is a disclosed limitation in addition to the model and sample-size changes. No prior low-reasoning choice is inherited, and no API-key billing fallback is authorized by this service selection.
8. **Message-role omissions in Appendix B.** Appendix B explicitly identifies Section 3, A.1–A.3, and C as single-user-message experiments, and A.5, A.6, and E as system-prefix plus user-body experiments. It does not explicitly list A.4 or D. If those experiments are included, the omission must be resolved or recorded rather than extending one rule by assumption.

Author code or original request artifacts, if available, may resolve some of these details. Until such evidence and the selected interface are audited, the justified description is a source-based replication under preparation with a disclosed model substitution and unresolved implementation details. It is not yet established that there will be exactly two differences from the source study.

## Original main-experiment analysis

The primary results use the average prices of each firm and the average total and difference in profits over periods 251–300 (Section 3, lines 530–535). Prices and profits are divided by alpha for comparison across currency scales. Figure 2 compares them to the static Bertrand–Nash equilibrium and the jointly optimal two-product monopoly solution (lines 583–592). The joint-monopoly benchmark differs from the single-product monopoly benchmark used in Appendix C.

The prior project's price-success thresholds, profit/CI threshold, minimum-effective-H search, and eligibility screening at periods 151–200 are not these source analyses. They must not determine whether the new experiment is run or whether an observation is included.

With one run per condition, descriptive trajectories and final-window outcomes remain meaningful, but the original between-run uncertainty and significance results cannot simply be reproduced. Repeated periods are not independent experimental replications.

Section 4.2 adds a realized-path regression of own price on own and competitor previous-period prices with firm–run fixed effects. It excludes the first 100 periods, uses disjoint consecutive-period pairs, and alternates the dependent-variable firm between pairs; the original table reports robust standard errors (lines 779–788 and 833–837). Exact regression inference and sufficient sample support require separate treatment if this analysis is selected.

## Excluded mechanism experiments: source-method inventory

### Price-war analysis and implantation, Section 4.1

The paper splits PLANS into sentences; a bulleted or numbered list item is treated as one sentence, with its list marker removed (lines 665–690). It filters sentences containing “price war” or “pricing war,” embeds them with `text-embedding-3-large` into 3,072 dimensions, and compares cosine similarities to the mean embeddings of four avoid-war and four start-war reference sentences (lines 694–732). Appendix F supplies a 14-sentence semantic-classifier validation set (lines 1985–1998 and 2006–2026).

It then selects three semantically self-contained P1-generated sentences closest to the avoid-war reference. For each selected sentence, every original run, both agents, and every period 2–13, it resets to the saved state preceding that period, replaces the target agent's PLANS with the sentence, clears its INSIGHTS, and obtains one counterfactual price. That price is compared with the price in the original trajectory at the same period (lines 706–740).

There is no successful-run eligibility filter, no forced 10% price reduction, and no multi-period continuation in this implantation protocol. The original 42-parent sample yields `3 * 42 * 2 * 12 = 3,024` observations.

### Broad text analysis and undercutting implantation, Section 5

All PLANS sentences are embedded with the same embedding model; PCA reduces them to 20 dimensions, followed by k-means with 20 clusters. For each cluster, the 10 closest sentences are given to GPT-4o-2024-08-06 to generate a four-word description. The summarizer's exact system instruction is printed in footnote 29 (lines 842–865). Cluster frequencies are normalized by each prompt's baseline sentence frequency (lines 903–907).

From the cluster most overrepresented under P2, the paper selects four semantically self-contained sentences closest to its center: two from P1 and two from P2. It repeats the same one-step PLANS-replacement/INSIGHTS-clearing intervention over all parents, both agents, and periods 2–13 (lines 910–938). The original sample yields `4 * 42 * 2 * 12 = 4,032` observations.

Together, the two implantation exercises require 168 counterfactual calls per parent trajectory: 1,008 calls for a six-parent reduced main sample. This is in addition to the main trajectories, embeddings, and cluster summarization, and excludes failed attempts.

The original seven implantation sentences were selected from the original GPT-4 data. Selecting from new Luna data can produce different sentences or too few qualifying price-war sentences. Using the paper's seven fixed sentences is a different, separately describable test; it must not be presented as reproducing the original data-dependent selection procedure. Likewise, replacing an embedding model or the cluster-description model is an additional methodological decision, not automatically covered by a seller-model substitution.

## Excluded appendix experiments: source-method inventory

| Experiment | Original design beyond the main market | Evidence |
| --- | --- | --- |
| A.1 Stochastic demand | Each period a_0 is uniformly sampled from {-0.05, 0, 0.05}; append the exact C sentence to P1/P2. Seven runs per scale and prefix. | Lines 1382–1401 and 1467–1468 |
| A.2 Asymmetric product qualities | a_1=2, a_2=2.75; P1/P1 and P2/P2; four runs per scale and prefix. Recompute asymmetric benchmarks. | Lines 1404–1410 and 1522–1534 |
| A.3 Heterogeneous prompt prefixes | Firm 1 uses P1, firm 2 uses P2; seven runs per scale. | Lines 1537–1542 and 1597–1599 |
| A.4 Discounting wording | P3/P3; four runs per scale. P3 is printed in the body of the appendix rather than G.1. | Lines 1621–1637 and 1691–1694 |
| A.5 Later-generation model | GPT-5.2 with high reasoning, P1/P1, seven runs per scale; system-prefix/user-body roles. Replacing this with Luna would require retaining a distinct treatment rather than silently merging it with the Section 3 replication. | Lines 1697–1714 and 1864–1868 |
| A.6 First-price auction | Two bidders, equal valuations v in {1, 3.2, 10}; A1/A1 and A2/A2; four runs per cell; random winner on tied bids; distinct auction feedback and Appendix H prompts. | Lines 1724–1797; Appendix H starts at 2343 |
| C Monopoly model comparison | One P0 monopoly run per scale for each of five original LLMs. A Luna-only version is a new-model diagnostic, not a replication of the original model ranking. | Lines 1880–1904 |
| D Prior demand knowledge | Fresh empty-history agents with P1/P2 answer a fixed yes/no question, 20 samples per prefix at temperature 1. | Lines 1930–1948 |
| E Memory ablations | Twelve monopoly runs per treatment: Control, No Plans, No Insights, No Memory. Erase the appropriate carried state while retaining identical output instructions. System-prefix/user-body roles. | Lines 1951–1981 and 1864–1868 |

Appendix C's convergence definition is specific: in periods 201–300, the 10th- and 90th-percentile prices must both lie within 5% of target price p; the target monopoly price maximizes one product's profit (lines 1896–1901). Appendix E uses that definition. Its text states 12 runs per treatment but does not explicitly enumerate the per-alpha allocation in the cited description; a reduced design must record that choice.

Appendix C.1 summarizes the memory experiment detailed in E; it should not be counted as a second independent copy of the same control/no-memory data (lines 1908–1917). F is classifier validation and G/H are prompt specifications, not further market treatment matrices.

## Preparation and execution boundary

Before creating a new empirical sample, the concrete protocol must freeze the confirmed six-condition scope, currency-scale coverage, exact named prefixes, numeric display and settlement rules, parsing/stopping behavior, Footnote 18 price-ceiling interpretation, supported model controls, and actual transport. Any source detail that cannot be established must remain an explicit limitation.

New experiment identifiers, output paths, and frozen configuration hashes must keep this replication separate from the completed memory-ablation project. Offline implementation checks may validate market calculations, information boundaries, prompt construction, and durable recovery without creating experimental outcomes. The user has resolved the scope and service choices; empirical work can begin after the relevant offline checks and configuration freeze. Completed historical runs are not restarted or repurposed.
