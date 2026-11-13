# IE498 research protocol v1.1

Research question: how do visible history length and strategic-memory representation affect supracompetitive pricing in repeated duopoly? The study distinguishes formation, memory substitution, maintenance, and responses to a one-round price cut. This protocol was recorded before live data generation; the formal repeat count was frozen separately after complete pilots.

## Sources and implementation

| Paper source | Project implementation | Material differences |
|---|---|---|
| v6 §2.1, pp.7–8 | Stable softmax logit demand; a=(2,2), c=(1,1), a0=0, mu=.25, alpha=1, beta=100 | Only alpha=1; no mixing of monetary scales |
| §2.2, Appendices B, G.1, G.2.1 | `paper_reference`: P1, H=100, overwritten PLANS/INSIGHTS, original text-output order | GPT‑6 Luna, low reasoning, at most 3 attempts; original model GPT‑4‑0613, temperature=1, at most 10 attempts |
| G.1 / G.2.1 | `bullet_memory` retains P1's long-run-profit objective and exploration wording; JSON schema places memory_bullet before price | Append one sentence each round without overwriting; full reads the entire archive, compressed freshly compresses the entire archive each round, clear reads an empty view |
| G.2.2 example | Two-decimal history display and textual $4.51 ceiling | The example prefix differs from G.1; P1 follows G.1. The rounding discrepancy between 2.34×1.92498092=4.50445535 and the example's 4.51 is retained |
| Appendices C.1, E | Study the importance of memory channels | Original memory ablations used monopoly; this main matrix uses duopoly |
| §4–5 | Reference for mechanism interpretation | The paper replaces strategy text; this project externally overrides one executed price to 90% of the proposed price, a different intervention |
| Appendix A.5 | Methodological replication | The paper's newer-model experiment uses GPT‑5.2 high; this project uses user-selected GPT‑6 Luna low |

The PDF, extracted text, official documentation, and source SHA‑256 hashes are in `docs/sources/`. The original P1 is in `prompts/p1-original.txt`; the original G.2.1 extraction is in `paper-template-original.txt`. The executable template only normalizes whitespace and replaces interpolation placeholders. No additional course slides were supplied.

## Economic and information environment

Each round, sellers simultaneously choose finite nonnegative real prices, retaining full precision. Demand is `q_i=100 exp((2-p_i)/.25)/(exp(0)+sum_j exp((2-p_j)/.25))`; profit is `(p_i-1)q_i`. Below-cost prices settle normally. The textual ceiling does not clip actions. Nash and joint-profit-optimal benchmarks are computed numerically with independent best-response checks.

Sellers see only cost, the textual ceiling, permitted history, and their own memory. There is no additional channel for the demand formula, benchmarks, total horizon, condition labels, run IDs, success thresholds, or cumulative returns. The most recent min(H,t−1) rounds appear newest first and show own price, rival price, own quantity, and own profit. H=0 explicitly supplies empty history. Every seller call is an independent Chat Completions request with one user message, `store=false`, no tools, conversation ID, or previous_response_id. Raw responses are archived rather than automatically returned to the model.

## Memory and timing

Each seller generates `memory_bullet` and `price` in one call per round. The bullet is a single-line English sentence beginning with `- ` and containing at most 60 words. Syntactic validation protects decimal numbers and common abbreviations; semantic self-containment relies on prompts and sampled review. Invalid outputs receive bounded retries; failures never produce invented prices.

Original bullets are appended by seller, run, and round and remain immutable. Clear reads an empty view every round; full reads all existing originals; a separate compressed request reads only fixed instructions and that seller's entire original bullet archive. No compressor is called for an empty first-round archive. Summaries record their source range and hash; old summaries are not recursively compressed in the next round.

Fix the previous checkpoint, construct both views, and fix both seller requests before concurrent calls. Persist each response atomically upon arrival. Only after both valid actions arrive may the preregistered executed-price shock apply, followed by settlement and transactional commitment of the round and both bullets. A round-t bullet can observe outcomes only through t−1.

## Model and costs

The user explicitly selected `gpt-6-luna` for both sellers and the compressor. Official documentation was retrieved on 2026‑11‑12 (America/Chicago). The public snapshot exposes only that ID; response model and request ID are retained in raw JSON. Context capacity is 1,050,000 tokens and maximum output is 128,000. This project uses low reasoning, a 2048-token output cap including reasoning for extension/compressor calls, and 4096 for paper_reference. Temperature is omitted because low reasoning does not support it. No API sampling seed is sent and verbatim reproducibility is not promised. Scheduling and analysis seeds are 498.

Standard prices in USD per million tokens: input .10, cached input .01, cache write .125, output .50. Requests exceeding 272K input tokens use the documented long-context multipliers: input/cache ×2 and output ×1.5. Reasoning is already included in completion_tokens and is not billed twice. `service_tier=default`; no regional-processing surcharge is configured. Accounting classifies actual provider usage; the ledger estimates costs and does not replace the account invoice.

Before scheduling, reserve input costs using the UTF‑8 byte upper bound plus 4096 framing tokens and the more expensive cache-write rate, together with maximum output costs. Attempts with unknown network outcomes conservatively consume the full reservation. Permanent authentication/quota errors pause the batch. Each logical call permits at most 3 attempts. A response saved before a database update can be reparsed during recovery; pending calls without saved responses become uncertain and are conservatively charged. Request-query and idempotency capabilities are not assumed without evidence.

The local tokenizer download endpoint returned a proxy 403. Approximate tokenization is therefore not labeled actual usage: history, memory, and archive components use UTF‑8 byte token upper bounds; API input/cached/output/reasoning counts are actual usage. The upper bound also prevents silent truncation of full archives. This limitation is stated in the results report.

## Staged plan

1. Offline: 16 configurations (15 matrix cells plus paper), each with 8 mock rounds; key-invariant tests, analysis, plotting, and snapshot restoration.
2. Smoke: two bullet/compressor rounds and one paper round, separately labeled.
3. Pilot: one complete 300-round run each for paper, H100/clear, and H100/compressed; three independent complete 300-round H100/full runs. Retain all candidates and failures.
4. Formation: H∈{0,1,5,20,100}×{clear,full,compressed}, 300 rounds per run. Randomize within complete balanced repeat batches. Target 3 per condition, frozen against measured costs; exclude pilots from the main sample.
5. Maintenance/shock: prioritize the main matrix. Parents are complete H100/full runs with checkpoint=200; only those meeting success criteria in rounds 151–200 qualify for conditional interventions. Report all parents and eligible counts. Branches inherit complete history and archives without modifying parents and continue for 100 rounds by default. The parent's natural rounds 201–300 may serve as a control when protocol, model, and source state match. Record selection before execution; rotate the shocked seller across parents; apply executed price=proposed price×.9 once. The implementation samples branch actions independently unless the optional shared shock-round action is selected.

## Metrics and inclusion

Primary evaluation uses the final 50 rounds: mean prices, profits, joint profit, the mean of the sellers' price standard deviations, and absolute price difference. `CI=(mean_joint_profit−44.58533201)/(67.49809190−44.58533201)` uses full numerical benchmark precision and retains negative values.

With epsilon=.02, price_success requires both prices to exceed their respective Nash+.02 in at least 80% of rounds. Profit_success requires CI≥.5; effective_success requires both. Threshold sensitivity reuses the same data for epsilon∈{.01,.02,.04} and CI thresholds∈{.4,.5,.6}. The minimum tested effective H is the smallest tested H with a success proportion≥.8; if none qualifies, report null alongside complete results and Wilson intervals for every H.

The independent unit is a complete run. Success rates use Wilson 95% intervals; continuous CI uses 5000 run-level bootstrap resamples with seed 498 and no interval for n<2. At n=3, intervals are descriptive only. The main analysis includes completed live formation runs only. Status, errors, and retries for all planned runs are retained separately; pilots, smoke, and mock are reported separately.

Maintenance branches are grouped by parent and compared with natural controls for final-50 CI/joint profit and continued effective success. Shock metrics measure the rival's price/profit differences from the same-source control beginning in the first post-event round. Recovery is the first 5 consecutive rounds with absolute price difference<.02; unobserved recovery is null. Response duration counts post-event rounds with absolute difference≥.02. A shock to a zero proposed price is labeled zero amplitude. Independent sampling also creates branch differences; these results describe deviation response rather than inferring punishment from price cuts alone.

## Recovery and backups

SQLite uses WAL, a unique (run,t) settlement key, and a unique (run,t,agent) memory key. Network calls occur outside transactions. Raw requests/responses exclude authentication headers and are stored atomically by stable logical call and attempt. Accepted entries record hashes, checked during recovery. A coordinator file lock ensures one writing coordinator; asynchronous concurrency occurs only within it. Each run retains its code version, prompt hashes, and configuration snapshot.

Local timestamped snapshots use the SQLite backup API, copy referenced raw files, and include SHA‑256 manifests. Restore requires a new directory and checks database integrity. No independent backup storage is configured; reports identify these as local snapshots.

Additional duration definition, recorded before intervention data generation: from the 20th post-branch round, maintenance examines every consecutive 20-round window. Failure time is the end of the first window failing effective_success; absent failure, duration is right-censored at 100 rounds. This is a window-defined duration, not a single-round structural-collapse time. Eligibility decisions for all formal H100/full parents are retained in parent_eligibility.csv.

Formal-stage transport keeps the single user string and all scientific inputs unchanged, using `prompt_cache_options.mode=explicit` without breakpoints to disable unhelpful cache writes. Original pilot settings remain intact. Explicit prefix caching is used only for independent cost calibration; calibration outputs do not enter behavioral analysis. Cache settings introduce no conversation state.

## Final scope after user budget changes

The user raised the budget from $15 to $25 and then removed the cap. The final formal scope follows the user's explicit selection: 15 conditions×3 independent 300-round runs. Historical freezes and amendment timing are recorded in D17–D23 and their JSON files. Additional repeats use the same protocol; intermediate behavioral results do not determine stopping. The two completed supplemental pilots are separately labeled as post-freeze diagnostic data.

## Five-repeat amendment and original-paper reference

The user subsequently requested five repeats after inspecting the three-repeat results. The current fixed endpoint is 75 bullet-memory runs plus 5 formal `formation_reference` runs, all 300 rounds. The 45 original completed runs remain unchanged; their pre-extension fingerprints are recorded. The 30 previously canceled, unstarted plans are reactivated under the explicit amendment. See D26–D27 and `configs/extension-freeze.json` for timing, scope, and scheduling.

The added H100 condition uses the original paper's overwritten PLANS/INSIGHTS architecture: carry only each seller's previous file contents, allow unrestricted multiline revision/deletion subject to the existing total output cap, and retain the last 100 rounds of permitted feedback. It uses the same GPT‑6 Luna low setting as the rest of this project. See [the source-method audit](paper_reference_method.md) for exact correspondence and replication differences.

All five formal reference runs start empty and are generated after the original results. Labels r1–r3 fill the missing reference sample counts; they do not imply earlier execution, shared random seeds, or paired sampling. The historical paper pilot remains excluded. This comparison changes the output task and memory representation together and does not isolate overwriting as a single causal factor. Separate architecture labels and summaries prevent pooling with bullet H100/full. The original minimum-H analysis still applies only to the 15-cell bullet grid.

Five repeats improve precision modestly but do not guarantee stable outcomes. All run points, Wilson intervals, and run-level bootstrap intervals remain reported. No outcome-dependent stopping or further expansion is authorized by this fixed plan. Independent runs may overlap in execution; within-run dependencies, bilateral input isolation, request bodies, rate-limit protections, cost reservations, and durable storage are retained.
