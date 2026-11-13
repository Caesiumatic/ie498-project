# Original-paper memory condition: method audit and expansion

## Target and source evidence

The added condition uses `architecture=paper_reference`, `H=100`, `mode=full`, and stage `formation_reference`. Here, `full` is a legacy configuration field: the seller reads the latest complete PLANS/INSIGHTS state, **not** the full append-only bullet archive. Reports identify the architecture separately to avoid pooling it with `bullet_memory / H=100 / full`.

The source is Fish, Gonczarowski, and Shorrer, *Algorithmic Collusion by Large Language Models*, arXiv:2404.00806v6. The pinned [PDF](sources/paper-v6.pdf) and [text extraction](sources/paper-v6.txt) are recorded with hashes in [the source manifest](sources/manifest.json). Line references below refer to that fixed text extraction.

| Contract | Original source | Implementation |
| --- | --- | --- |
| 300 simultaneous-pricing periods | §2, pp.7–8, text lines 323–329 | Each independent run begins with empty history and completes 300 rounds; both seller inputs are fixed before either action is sampled |
| Recent market history | §2.2, p.9, lines 408–425; Figure 1, p.10, lines 483–489 | Most recent min(100,t−1) rounds: both prices, own quantity, own profit; values displayed to two decimals |
| History order | G.2.3, pp.A.9–A.11, lines 2274–2316 | Newest first, matching the worked period-10 example |
| Private carried state | §2.2, lines 419–425; Appendix E, lines 1951–1957 | Each seller receives only its own PLANS and INSIGHTS from the preceding round |
| Overwrite semantics | G.2.1, pp.A.6–A.7, lines 2089–2144, especially 2143–2144 | New PLANS and INSIGHTS replace their respective prior contents; the agent can rewrite, summarize, or delete them |
| No bullet restriction | G.2.1, lines 2101–2108 and 2134–2144 | Free-form text, asked to be detailed and precise but succinct; no one-sentence or 60-word validation |
| Response order | G.2.1, lines 2134–2141 | Observations/thoughts, new PLANS, new INSIGHTS, then chosen price |
| Stateless API calls | §2.2, lines 419–425; Appendix B, lines 1864–1867 | Independent single-user-message requests for the original core duopoly architecture; no conversation ID, prior response link, tools, or automatic transcript carryover |
| P1 objective | G.1, pp.A.5–A.6, lines 2038–2047 | Original P1 prefix, emphasizing long-run profit and exploration without undermining profitability |

The current files can retain information older than the 100-round market window. Figure 1 explicitly permits statistics over longer horizons in plans and insights. Overwriting therefore does not imply that all older information is forgotten; it means that older content survives only when the agent carries it forward.

The original Appendix E experiment is a **monopoly** ablation of plans, insights, or both. Its unchanged output instructions give treatments equal space to think (lines 1974–1978). This new condition uses the original **duopoly** architecture; it does not reproduce the monopoly ablation.

Appendix A.5 is a different, later-model experiment using GPT‑5.2 with high reasoning. Appendix B assigns its prefix to a system message. The requested original PLANS/INSIGHTS baseline instead follows the core §3 single-user-message format; these two implementations should not be conflated.

## Verified implementation behavior

`src/ie498/runner.py` selects `history[-1]['actions'][seller]` for the carried paper state. `src/ie498/memory.py` fills the G.2.1 template with its `plans` and `insights` fields. Previous observations/thoughts, the other seller's private files, and older overwritten file versions are excluded from the next request. An empty string deletes a file's carried content. Complete old responses remain in the research archive for audit but are not exposed to the seller.

The paper-output parser accepts multi-sentence and multiline PLANS/INSIGHTS with no 60-word limit. `request_body` omits the bullet JSON schema for this architecture. There is no external compressor. Exactly two successful seller calls per round are required, excluding retries. The existing `paper_reference` pilot implementation already satisfies this memory contract, so the formal extension requires no changes to the experimental prompts.

The focused offline tests in `tests/test_paper_memory.py` exercise deletion and rewriting across rounds, content exceeding 60 words, private-state isolation, exclusion of old thoughts and overwritten content, the 100-round boundary, and stateless request construction. Existing full-data auditing reconstructs seller requests from preceding stored states and checks their hashes against accepted calls.

## Documented differences from the paper

This is a methodological replication of the memory architecture, not an exact recreation of every original experiment:

- The user selected GPT‑6 Luna with low reasoning. The original core experiment used GPT‑4‑0613 and temperature 1 (Appendix B, lines 1844–1849). Temperature is omitted for the current model configuration.
- The project fixes alpha=1. The original study varied alpha across 1, 3.2, and 10 (§2.1, lines 350–354).
- Initial API-key calls used a 4096-token paper output cap, including reasoning; the later subscription continuation omits that cap because the interface does not support it. The project retains at most 3 attempts per logical call. Appendix B describes up to 10 retries and does not specify this output cap. The interface change is documented in D30–D32 and [subscription continuation](subscription_continuation.md).
- The parser enforces the four requested headings and a numeric price. The paper describes extracting prices even when outputs contain additional sentence text, so malformed-output tolerance may differ.
- The executable prompt normalizes PDF whitespace and substitutes values. The textual ceiling remains $4.51 from G.2.2. Footnote 18's 2.34 times the numerical joint-optimal price is approximately 4.50446; that small discrepancy was documented in the original project protocol.
- G.2.2/G.2.3 worked examples contain a different exploratory prefix from the separately listed G.1 P1. The project deliberately uses G.1 P1 consistently rather than silently replacing it with the example prefix.
- The project uses its declared price/profit success thresholds and uncertainty estimates; they are not claimed to reproduce every original paper analysis.

PLANS/INSIGHTS versus bullet memory changes both the representation/update rule and the output task: paper agents write free-form observations and two files, while bullet agents write one bounded sentence. The comparison therefore estimates an **architecture-level** difference, not the isolated causal effect of overwriting at a fixed output budget.

## Five repeats and retrospective additions

The expansion creates five new independent formal reference runs from empty history and empty private files. Repetition indices 1–3 fill previously missing reference cells alongside the already completed three-repeat matrix; indices 4–5 complete the expanded five-repeat design. All five reference runs are generated after the original results were inspected. Their indices do not imply contemporaneous execution with the older batches or paired random seeds.

The original 45 bullet-memory runs are retained unchanged. Previously canceled, unstarted bullet runs in repetitions 4–5 can be reactivated after confirming that they have no rounds or paid attempts. The completed paper pilot remains labeled pilot and is not relabeled or pooled into the five formal reference runs. The final design contains 75 bullet-memory formation runs plus 5 separately identified reference runs.

This amendment follows the user's concern about variability after reviewing the three-repeat results. It must be reported as a post-result expansion, not as the original preregistered sample size. Five repeats improve precision only modestly and do not guarantee stable outcomes. Neither stopping early on favorable results nor adding more repeats based on the expanded outcomes is part of this plan. Period/cohort differences may confound comparisons with the earlier runs and must remain visible in reporting.

All five formal reference runs later switch from Chat Completions to subscription Responses at their saved checkpoints, as do the added bullet-memory repeats. Prompt text, model, reasoning level, and memory updates remain the same, but output-token caps and transport controls differ. No interface-equivalence experiment is performed. This additional limitation accompanies the architecture-level comparison.
