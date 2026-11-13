"""Generate an English research report strictly from saved data; no API access."""
import json
from pathlib import Path
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.storage import Store,budget_label
from ie498.analysis import analyze


def table(frame,columns):
    if frame.empty:return 'No eligible data.\n'
    lines=['| '+' | '.join(columns)+' |','|'+'|'.join(['---']*len(columns))+'|']
    for _,row in frame.iterrows():
        values=[]
        for col in columns:
            value=row[col]
            if pd.isna(value):value='—'
            elif isinstance(value,float):value=f'{value:.4f}'
            values.append(str(value))
        lines.append('| '+' | '.join(values)+' |')
    return '\n'.join(lines)+'\n'


def read_csv(path):
    try:return pd.read_csv(path)
    except (pd.errors.EmptyDataError,FileNotFoundError):return pd.DataFrame()


def main():
    store=Store(ROOT/'data/runs/live',readonly=True)
    out=ROOT/'reports/live';analyze(store,out)
    runs=read_csv(out/'runs.csv');costs=read_csv(out/'resources.csv');conditions=read_csv(out/'conditions.csv')
    merged=runs.merge(costs[['run','cost_usd','calls']],left_on='id',right_on='run',how='left')
    primary=merged[merged.eligible_primary]
    reference=merged[merged.eligible_reference]
    reference_conditions=read_csv(out/'paper_reference_conditions.csv')
    reference_comparison=read_csv(out/'paper_reference_comparison.csv')
    extension_path=ROOT/'configs/extension-freeze.json'
    extension=json.loads(extension_path.read_text()) if extension_path.exists() else None
    planned=extension.get('runs',[]) if extension else []
    planned_primary=sum(r['config']['stage']=='formation' for r in planned)
    planned_reference=sum(r['config']['stage']=='formation_reference' for r in planned)
    progress=(f"The frozen extension targets {planned_primary} bullet-memory runs and {planned_reference} separate paper-reference runs ({len(planned)} total). Current completed counts are {len(primary)} and {len(reference)}, respectively. "
              + ('The planned formation sample is complete.' if len(primary)==planned_primary and len(reference)==planned_reference else 'The extension is not yet complete; the tables below are interim summaries of completed runs.')) if extension else 'No extension freeze is available; only the recorded completed sample is reported.'
    audit_path=ROOT/'reports/data_audit.json'
    audit=json.loads(audit_path.read_text()) if audit_path.exists() else {}
    audit_counts=audit.get('counts',{})
    audit_scope=(f"The saved audit records passed={audit.get('passed')} for {audit_counts.get('rounds','unknown')} rounds and {audit_counts.get('attempts','unknown')} attempts. This receipt certifies its recorded snapshot, not data added afterward." if audit else 'No saved full-data audit receipt is available.')
    pilots=merged[merged.stage=='pilot']
    spending=store.spending()
    allowance='The user removed the spending cap; actual costs and in-flight reservations remain recorded. ' if spending['budget'] is None else f"Remaining budget headroom is ${spending['budget']-spending['spent']:.6f} (not an account balance). "
    attempts=store.rows("SELECT status,COUNT(*) n,SUM(cost) cost FROM api_attempts GROUP BY status")
    uncertain=sum(r['cost'] for r in attempts if r['status']=='uncertain')
    successes=int(primary.effective_success.sum()) if len(primary) else 0
    reference_successes=int(reference.effective_success.sum()) if len(reference) else 0
    text=f'''# IE498: Strategic Memory and Supracompetitive Pricing in Repeated Duopoly

## Abstract

This project studies visible market-history windows H∈{{0,1,5,20,100}} and clear, full, and compressed strategic memory in a repeated Bertrand duopoly with logit demand. All live sellers and compressors use the user-selected GPT‑6 Luna with low reasoning. The independent unit in the main experiment is a complete 300-round duopoly run.

There are **{len(primary)} completed formal bullet-memory formation runs**, of which **{successes}** meet the predefined effective supracompetitive criterion, and **{len(reference)} completed formal paper-reference runs**, of which **{reference_successes}** meet the same criterion. The two architectures are summarized separately; their success counts are not pooled. There are {sum(pilots.status=='completed')} complete pilots; interrupted and failed pilots remain separately recorded. The cost ledger totals **${spending['spent']:.6f}**, including **${uncertain:.6f}** in conservative charges for requests with unknown processing status. The budget is {budget_label(spending)}. Conclusions below use saved data only.

{progress}

After reviewing the original three-repeat results, the user requested a fixed expansion to five repeats and a new H=100 condition using the paper's overwritten PLANS/INSIGHTS memory. The first 45 runs remain intact. Additional runs complete repeats 4–5 of the 15-cell matrix; five fresh paper-reference runs supply the new comparison, including labels 1–3. These labels do not imply that the added condition ran historically alongside the original repeats or used matched random draws. Historical paper pilots remain excluded.

## Research questions and game mechanics

Two firms set prices simultaneously, each seeking to maximize long-run profit. Products are differentiated, and demand depends on both prices and an outside option. Price responses therefore affect current market share and may influence future competitor behavior. The LLMs adapt through textual history and self-authored strategy records; their weights are not updated through training.

The four questions concern the formation of supracompetitive pricing, whether a one-sentence summary can substitute for longer raw history, how long established high-profit pricing persists after memory is reduced, and the dynamic response to a one-round reduction in a competitor's executed price.

## Paper replication and project extensions

The reference is Fish, Gonczarowski, and Shorrer, *Algorithmic Collusion by Large Language Models*, pinned to arXiv:2404.00806v6. Section 2.1 supplies the environment; Section 2.2 and Appendix B describe information and API architecture; G.1/G.2.1 provide P1 and the generic template. The original PDF and SHA‑256 are in docs/sources. The original memory ablation used monopoly, whereas this project varies memory in duopoly, so this is not a direct replication of that ablation.

`paper_reference` retains P1, 100 rounds of history, and overwritten PLANS/INSIGHTS. `bullet_memory` appends one original bullet of at most 60 words per round. Clear writes but does not read memory; full reads all original bullets; compressed uses a fresh independent request to compress all original bullets into one sentence for the seller. Summaries never recursively replace the external archive. H100/full is the extension baseline; paper_reference is a separate architectural control. The current model differs from the original GPT‑4‑0613 and the GPT‑5.2 high setting in A.5, so the study is a methodological replication.

## Experimental protocol and reliability

Demand per round is `qᵢ = 100 exp((2−pᵢ)/0.25) / [1 + exp((2−p₁)/0.25) + exp((2−p₂)/0.25)]`, and profit is `πᵢ = (pᵢ−1)qᵢ`; the denominator's 1 represents the outside option. Parameters are a1=a2=2, a0=0, mu=.25, c1=c2=1, alpha=1, and beta=100. Settlement uses stable softmax and full price precision; displayed history rounds to two decimal places. The computed Nash price is 1.47292666 with per-firm profit 22.29266600; the symmetric joint-profit-optimal price is 1.92498092 with per-firm profit 33.74904595. Numerical solutions also verify best responses. Single-product monopoly uses its own corresponding environment.

Sellers see only cost, the textual $4.51 ceiling, permitted feedback from the most recent H rounds, and their own memory. They do not see the demand formula, experimental condition, success thresholds, or remaining horizon. H=0 provides no market feedback; full/compressed then accumulate self-generated strategies rather than environmental observations. Both inputs are fixed before either response arrives. A round's bullet can reference outcomes only through the previous round. Executed-price shocks apply after both submissions.

Independent Chat Completions requests carry no conversation links and provide no tools. SQLite transactions ensure one settlement per round, with one immutable memory append per bullet-memory seller; paper-reference state is replaced by the latest PLANS/INSIGHTS output while original responses remain archived. Valid responses are cached by logical call solely for recovery of that call; new rounds are sampled again even with identical prompts. Costs are reserved before calls, retries are bounded, and every attempt retains its raw request, response, and cost. Validation covers mock end-to-end execution, recovery after partial responses, budgeting, branching, and backup restoration. {audit_scope} See [data_audit.json](data_audit.json) for audit scope and `reports/restore_verification.json` in the full archive for snapshot restoration verification. Test counts are recorded in the decision/status logs rather than asserted by this report generator. Current retry counts and failures are in `live/resources.csv` and `live/runs.csv`; all attempts, including truncated outputs, are retained.

The v1.0 pilots produced some outputs exceeding 60 words or containing multiple sentences; failed samples were not cleaned into successes. Before the formal stage, v1.1 added structured sentence/word-count constraints and restarted independent pilots. Original outputs and initial prompts remain preserved. See docs/decisions.md.

## Evaluation rules and amendment timing

Evaluation rules were fixed before the original formal experiment; the later sample expansion and new comparison were specified after the original results had been viewed. The primary evaluation uses the final 50 rounds. CI=(mean joint profit−Nash joint profit)/(joint-optimal profit−Nash joint profit), retaining negative values. Price success requires both prices to exceed Nash+.02 in at least 80% of rounds; profit success requires CI≥.5; effective success requires both. High-price paths with almost no sales do not count as effective successes.

Each complete run is one independent observation; neither the two firms nor the 300 rounds are treated as independent repeats. Success proportions use Wilson 95% intervals. Continuous metrics use 5000 run-level bootstrap resamples, with no interval for n<2. The minimum effective H refers only to the smallest tested H with a sample effective-success rate of at least 80%; it is not a universal minimum memory requirement. Small-sample intervals are reported alongside all run points. Threshold sensitivity reuses the same data.

## Pilots and the model freeze

'''
    text+=table(pilots,['id','status','rounds_completed','CI','effective_success','cost_usd'])
    text+='\nMetrics for incomplete pilots are diagnostic only and are not 300-round endpoint evaluations. Cost-calibration calls are not behavioral runs.\n'
    freeze=ROOT/'configs/formation-freeze.json'
    if freeze.exists():
        f=json.loads(freeze.read_text())
        text+=f"\nThe formal protocol is frozen at {f['repeats']} independent runs per condition; see configs/formation-freeze.json for cost estimates and reservations. All pilots are excluded from the main matrix. Full-2/full-3 were completed after the original three-repeat matrix and are post-freeze diagnostic data; they did not inform model or prompt selection.\n"
    else:text+='\nThe formal repeat count has not yet been frozen.\n'
    if extension:
        text+='\nThe amended sample and run-level frozen configurations are in configs/extension-freeze.json. This external scope amendment followed inspection of the original results; it was not an original preregistered five-repeat design. Further stopping does not depend on the observed success rate.\n'
    text+='\n## Bullet-memory formation results\n\n'
    if len(conditions):
        text+=table(conditions,['mode','H','n','successes','success_rate','wilson_low','wilson_high','mean_price','mean_joint_profit','mean_CI'])
        text+='\n![Formation mean CI](live/formation_heatmap.png)\n\n![Independent run points](live/run_points.png)\n'
        best=conditions.loc[conditions.mean_CI.idxmax()];worst=conditions.loc[conditions.mean_CI.idxmin()]
        text+=f"\nThe highest condition mean CI is {best['mode']} / H={int(best.H)} ({best.mean_CI:.3f}); the lowest is {worst['mode']} / H={int(worst.H)} ({worst.mean_CI:.3f}). These rankings describe this fixed model, prompt, and sample, and should not be generalized across models.\n"
        if successes==0:
            text+='\nNo completed formal run passed both price and profit criteria. The current grid therefore identifies no minimum tested effective H and provides no basis for claiming that one-sentence memory replaces long history in sustaining effective supracompetitive pricing. Negative results can still indicate learning or exploration limits under this model and protocol.\n'
        elif successes<len(primary):
            text+='\nEffective success did not occur in every run. Interpret complete price/profit trajectories, between-run variation, and all three success indicators together; a few successful paths do not establish a stable equilibrium.\n'
    else:text+='No completed formation runs are eligible for the primary analysis. Mock or short smoke runs do not substitute for empirical results.\n'
    text+='\nMinimum tested effective H and supporting evidence:\n\n'
    for row in json.loads((out/'minimum_tested_effective_H.json').read_text()):
        h=row['minimum_tested_effective_H'];e=row['evidence']
        if e:
            text+=f"- {row['mode']}: H={h}; {e['successes']}/{e['n']} successes, Wilson 95% interval [{e['wilson_low']:.3f}, {e['wilson_high']:.3f}].\n"
        else:text+=f"- {row['mode']}: not identified in the current grid and sample.\n"
    text+='\n## Added H100 paper-reference condition\n\n'
    text+='The seller receives its most recent PLANS and INSIGHTS, rewrites both in each response, and sees up to 100 market rounds. This permits revision, summarization, or deletion of older memory content. Full bullet memory instead appends immutable sentences. Both use the same market and evaluation rules, but output format and memory-update contracts differ. The comparison is a methodological replication using GPT‑6 Luna, not an exact rerun of the original model.\n\n'
    text+=table(reference_conditions,['architecture','condition','H','n','successes','success_rate','wilson_low','wilson_high','mean_price','mean_joint_profit','mean_CI','CI_bootstrap_low','CI_bootstrap_high'])
    text+='\nH100 comparison with the three bullet-memory modes; each row uses only completed formal runs of its own condition:\n\n'
    text+=table(reference_comparison,['architecture','condition','n','successes','success_rate','wilson_low','wilson_high','mean_price','mean_joint_profit','mean_CI'])
    text+='\nIndividual added reference runs (pilots excluded):\n\n'
    text+=table(reference,['id','repetition','status','rounds_completed','CI','effective_success','cost_usd'])
    text+='\nThe paper condition was added after viewing the original results. Its repeat labels 1–3 supply new independent observations, not retrospective changes to old trajectories. Comparisons are unpaired and potentially affected by execution-time or model-service differences. Five repeats still provide limited precision; neither a favorable example nor a condition ranking establishes stable behavior.\n'
    extension_interpretation=ROOT/'reports/extension_interpretation.md'
    if len(primary)==75 and len(references)==5 and extension_interpretation.exists():
        text+='\n'+extension_interpretation.read_text()+'\n'
    interpretation=ROOT/'reports/interpretation.md'
    if interpretation.exists():
        text+='\n## Historical interpretation of the original three-repeat sample\n\nThe following commentary is retained from the original 45-run analysis. Its numerical claims and text sampling refer only to that historical sample; they are not updated conclusions about the five-repeat extension or the newly added paper condition. Current aggregate results appear in the tables above.\n\n'
        text+=interpretation.read_text().replace('## Main findings and interpretation','### Original-sample findings and interpretation',1)+'\n'

    text+='\n## Maintenance and deviation response\n\n'
    eligible=read_csv(out/'parent_eligibility.csv');paired=read_csv(out/'paired.csv')
    if len(eligible):text+=f"There are {len(eligible)} bullet-memory formal H100/full parent candidates; {int(eligible.checkpoint_available.sum())} have round-200 checkpoints, and {int(eligible.eligible.sum())} meet effective-success criteria in rounds 151–200.\n\n"
    if len(paired):
        text+=table(paired,['parent','child','stage','H','mode','eligible_parent','delta_CI','delta_joint_profit','effective_success'])
        text+='\nBranches sharing a parent are grouped by parent. Natural continuation is the control; the executed-price shock multiplies one proposed price by .9 once. Response metrics begin in the following round. Dynamic differences from the control include later independent model-sampling noise; price reductions alone do not establish punitive intent.\n'
        maintenance=paired[paired.stage=='maintenance']
        if len(maintenance):
            text+='\nMaintenance duration is the end of the first failing 20-round rolling window, relative to the branch point; observations without failure are right-censored:\n\n'
            text+=table(maintenance,['child','first_failed_20_round_window_end','survival_censored','followup_rounds'])
        shock=paired[paired.stage=='shock']
        if len(shock):
            text+='\nResponse duration counts subsequent rounds with an absolute price difference from natural continuation of at least .02. Recovery time is the start of the first 5 consecutive rounds with a difference below .02:\n\n'
            text+=table(shock,['child','first_opponent_price_delta','response_rounds','recovery_time','zero_shock'])
        if (out/'shock_response.png').exists():text+='\n![Deviation response](live/shock_response.png)\n'
    else:
        intervention_plan=ROOT/'configs/interventions-freeze.json'
        if intervention_plan.exists():
            ip=json.loads(intervention_plan.read_text());n_eligible=sum(r['eligible'] for r in ip['candidates'])
            text+=f'The saved intervention freeze covered {len(ip["candidates"])} parents; {n_eligible} were eligible and {sum(r["selected"] for r in ip["candidates"])} were selected under the budget plan. There are no completed branches to report. Screening and budget reasons are saved in configs/interventions-freeze.json. This saved freeze may precede newly added parents; compare its candidate IDs with current parent_eligibility.csv before interpreting it as screening of the expanded sample.\n'
        else:text+='No completed, pairable maintenance/shock data are available. See the final status record for reasons these experiments were not executed.\n'
    text+='\n## Resources and recorded costs\n\n'
    bystage=costs.groupby('stage',as_index=False)[['calls','input_tokens','cached_input_tokens','output_tokens','reasoning_tokens','cost_usd']].sum()
    text+=table(bystage,list(bystage.columns))
    if len(primary):
        bymode=costs.merge(primary[['id','mode']],left_on='run',right_on='id').groupby('mode',as_index=False)[['calls','cost_usd','compressor_input_tokens','final_archive_bytes','max_visible_memory_words']].mean()
        text+='\nMean resources per formal run, grouped by memory mode across all H values:\n\n'
        text+=table(bymode,list(bymode.columns))
    if len(reference):
        ref_resources=costs[costs.run.isin(reference.id)]
        columns=['calls','cost_usd','input_tokens','output_tokens','max_visible_memory_words']
        text+='\nMean resources per completed formal paper-reference run (separate from bullet modes):\n\n'
        text+=table(ref_resources[columns].mean().to_frame().T,columns)
    text+=f'''\nThe total ledger is ${spending['spent']:.6f}. {allowance}Attempts with unknown server-processing status are charged at the reserved upper bound; these estimates are not invoices. Reasoning tokens are already included in output tokens and are not charged twice.

Compression reduces seller-visible memory but retains the complete original archive and pays to reread it every round. Conclusions therefore concern decision-context compression, not a system that needs only one sentence of memory. History/memory/archive components are recorded as conservative UTF‑8 byte bounds, while API tokens use actual usage. The tokenizer endpoint was inaccessible in this environment, so no fabricated exact token counts are reported.

## Game theory and AI interpretation

Static Nash is the intersection of one-shot best responses. Paths above Nash with higher profits are consistent with supracompetitive pricing, but similar prices in a finite simulation do not establish a sustainable dynamic collusive equilibrium. Long-run incentives, differentiated demand, beliefs about competitor responses, and memory representation jointly shape exploration. P1 emphasizes long-run profit and avoiding profit destruction; this may encourage caution but may also leave agents relying on local experience with high prices and low sales.

A long original archive can retain early numerical evidence as well as mistaken judgments. A one-sentence summary may omit conditions or turning points when selecting information. H=0 conditions cannot correct these judgments through market feedback. Price/profit trajectories, sampled text, and resource expenditure should be interpreted together; prompt length is not equivalent to strategic rationality.

## Scope of evidence and reproducibility

The model was user-selected rather than chosen for favorable outcomes. Prompt-format corrections occurred during the pilot stage and are versioned. Main results are limited to GPT‑6 Luna, low reasoning, alpha=1, P1, 300 rounds, and the current success criteria. The small sample, single model, post-result scope amendment, and later execution of the new architectural comparison limit generalization. Model-service randomness precludes a guarantee of verbatim reruns; saved data, configurations, and analysis can be recomputed.

See `live/runs.csv` for all runs, statuses, and failure reasons; `live/rounds.csv` and `live/trajectories/` for complete trajectories; `live/conditions.csv` for metric intervals; `live/resources.csv` for resources and retries; and `live/memory_audit.csv` for raw-memory auditing. Raw requests, responses, checkpoints, and the database are in `data/runs/live/`, without authentication headers. Consistent SQLite snapshots and SHA‑256 manifests are in `data/backups/`. Raw data and large CSVs are included in the local delivery archive, not in Git. Raw-data backups remain local; no independent remote backup is available.

See README for commands, recovery steps, and data structure. Recompute the analysis with:

```bash
uv run ie498 --data data/runs/live analyze --out reports/live
uv run python scripts/make_report.py
```

## References

1. Fish, Gonczarowski & Shorrer, *Algorithmic Collusion by Large Language Models*, arXiv:2404.00806v6, https://arxiv.org/pdf/2404.00806v6.
2. OpenAI GPT‑6 Luna model page, https://developers.openai.com/api/docs/models/gpt-6-luna.
3. OpenAI Conversation state, https://developers.openai.com/api/docs/guides/conversation-state.
4. OpenAI current model parameters and Chat Completions API documentation, retrieved 2026‑11‑12; source snapshots and hashes are in docs/sources/manifest.json.
'''
    (ROOT/'reports/research_report.md').write_text(text)
    store.close()
    print(ROOT/'reports/research_report.md')


if __name__=='__main__':main()
