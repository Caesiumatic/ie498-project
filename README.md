# IE498: Memory and Supracompetitive Pricing

This experiment tests how visible market history and strategic memory shape pricing in repeated Bertrand duopoly. **GPT‑6 Luna** sellers compete across 15 conditions: history windows `H={0,1,5,20,100}` crossed with `clear/full/compressed` memory. A separate `paper_reference` condition implements the source paper's P1 architecture.

The runner records each decision, memory view, settlement, and API cost, and resumes interrupted runs by logical call ID. Start with the [results](reports/research_report.md), [research protocol](docs/protocol.md), or [current status](docs/status.md); the [decision log](docs/decisions.md) records protocol choices.

## Independent core-paper reconstruction (in progress)

A new, separate experiment follows the source paper's Section 3 design: **P1/P2 × alpha 1, 3.2, 10, one 300-period run per condition** (six runs, 1,800 planned periods). It uses GPT-6 Luna with reasoning `none`, the original free-form output task, overwritten private PLANS/INSIGHTS, H100, and the paper's final-50 normalized prices and profits. The user selected Pro subscription inference and accepted that temperature/top_p cannot be explicitly fixed; actual response settings are archived. Original implementation details not specified by the paper are documented as reconstruction choices.

See the [source-based protocol](docs/paper_replication_protocol.md), [independent execution commands](experiments/paper_replication/README.md), and [author-code search receipt](docs/paper_replication_source_search.md). All 156 offline tests passed before delivery preparation. Execution data live separately under `data/runs/paper_replication/`; a completed report and raw-data archive will be generated after the fixed runs finish. This experiment does not relabel or pool any of the completed results below.

## Completed five-repeat experiment

The frozen extension is complete: **75 bullet-memory runs plus 5 formal H100 paper-reference runs**, each lasting 300 rounds, for **24,000 formal rounds**. The original 45 runs remain unchanged. The new paper condition supplies five fresh independent runs, including labels r1–r3; it does not modify historical trajectories or relabel pilots.

| Measure | Recorded result |
| --- | --- |
| Bullet-memory effective success | 9 of 75 runs (original 8/45; added 1/30) |
| Bullet-memory price-criterion success | 69 of 75 runs |
| Paper-reference effective success | 0 of 5 runs; mean CI −0.348 |
| Minimum tested effective H | Not identified for any mode; no cell reaches 4/5 successes |
| Maintenance/shock eligibility | 0 of 5 H100/full bullet parents; zero branches |
| API cash ledger | $42.15208822; excludes subscription usage valuation |
| Verification | 75 offline tests and the full 68,150-attempt data audit passed |

The extension followed inspection of the original results. Five repeats narrow the observed Wilson intervals in all 15 cells, but outcomes still vary substantially and no condition reaches the predefined 80% sample success threshold. High prices frequently coincide with low profits. Complete run points and uncertainty intervals are in the [research report](reports/research_report.md) and [extension comparison](reports/extension_interpretation.md).

After API credit exhaustion, the remaining **3,422 rounds completed through official ChatGPT subscription Responses**, including a later continuation of the final 39 rounds. GPT‑6 Luna, low reasoning, original prompt text, and memory rules were retained. The subscription interface omits the original output-token caps and transport controls; no equivalence experiment was performed. This within-run interface change limits causal comparisons. See [subscription continuation](docs/subscription_continuation.md) for exact provenance and commands.

The paper-reference condition overwrites PLANS/INSIGHTS each round. See the [paper-method audit](docs/paper_reference_method.md), [descriptive text review](reports/reference_text_review.md), [frozen design](configs/extension-freeze.json), and [performance measurements](docs/performance.md). The [original three-repeat report at its historical commit](https://github.com/Caesiumatic/ie498-project/blob/9dbee68a8d851890bbb0e8c4967b014db98ce30e/reports/three_repeat_report.md) preserves its original figures and wording.

Saved-data analysis needs no credentials. Smoke, pilot, and collection commands below are for new, separately documented experiments. Historical run IDs reject mismatched scientific configurations. The full delivery archive includes raw data and restoration verification.

## Installation and credentials

For new API-key runs, configure `.env` as below. Subscription continuation uses the separate [official authorization workflow](docs/subscription_continuation.md).

```bash
cd /workspace/ie498
uv sync --extra dev
cp .env.example .env  # First-time setup only; do not overwrite existing credentials
chmod 600 .env
# Edit .env locally or set OPENAI_API_KEY; never commit credentials
uv run pytest -q
uv run ie498 benchmarks
```

In restricted environments, set `UV_CACHE_DIR=/tmp/ie498-uv` and `XDG_CACHE_HOME=/tmp/ie498-cache` if needed. An existing `.venv` supports `.venv/bin/ie498` and `.venv/bin/pytest`. Dependencies are locked in `uv.lock`; no separate database service or web application is required.

## Execution sequence

```bash
# 1. Offline pipeline; keep mock data in a separate database
uv run ie498 --data data/runs/mock mock --rounds 8
uv run ie498 --data data/runs/mock analyze --out reports/mock

# 2. Paid calls; retain the same live database for cumulative accounting
uv run ie498 --data data/runs/live smoke --concurrency 1
uv run ie498 --data data/runs/live pilot --concurrency 6
uv run ie498 --data data/runs/live plan --repeats 5

# 3. Freeze configs/formation-freeze.json after complete pilots
#    Include the complete base.json config, prompt_hash, repeats, and cost basis
uv run ie498 --data data/runs/live formation --repeats 5 --batch 1
# The user removed the spending cap and selected 5 repeats per condition.
# The stage runner also resumes the unfinished paper pilot:
uv run python scripts/run_formation.py

# 4. Reanalyze saved data without API calls
uv run ie498 --data data/runs/live analyze --out reports/live
uv run python scripts/compare_extension.py
uv run python scripts/make_report.py
uv run ie498 --data data/runs/live status
```

Keep live stages in the same database so the cost ledger covers the full experiment. The formal repeat count must match the frozen plan; each complete batch covers all 15 conditions. Repeating a stage or using `resume` reuses responses only for the same logical call.

To pause an active run after its current round commits, create `data/runs/live/RUN_ID.pause`; remove it before resuming. Ctrl+C also interrupts execution, but requests processed by the server without a locally saved response are marked uncertain and conservatively charged at the reserved amount.

```bash
uv run ie498 --data data/runs/live resume pilot-full-1
# Resume all unfinished runs after resolving specific status errors
uv run ie498 --data data/runs/live resume
# Start an independent paper pilot using the same cost ledger
uv run ie498 --data data/runs/live --config configs/paper_reference.json run paper-additional
```

Each logical call permits at most 3 attempts. Exhausted retries do not trigger unlimited paid retries; raw outputs remain available for review. Use a new run ID for each independent repeat. Resume is blocked when prompt files change; restore the version used for that run. Record model, prompt, or scientific parameter changes and create a new experiment version.

## Branches and one-round shocks

Check each parent's rounds 151–200 against the protocol, record all parents and eligibility counts, and freeze branch selection before execution. The main matrix takes priority.

```bash
# Replace with an existing, eligible, complete parent ID
uv run ie498 --data data/runs/live fork formation-r1-h100-full maint-r1-clear \
  --checkpoint 200 --H 1 --mode clear --run
uv run ie498 --data data/runs/live fork formation-r1-h100-full shock-r1 \
  --checkpoint 200 --H 100 --mode full --shock-agent 0 --share-actions --run
```

Branches continue for 100 rounds by default and inherit market history and the complete private archive. The shock multiplies one seller's executed price by 0.9 in round 201 only; the proposed price and bullet remain intact, and the next round reports realized outcomes. `--share-actions` requires the first-round request hash to match the parent's exactly and reuses that proposed action; later rounds are independently sampled. The complete parent's natural continuation provides a paired control without altering its data.

## Data and recovery

- `data/runs/live/experiments.sqlite`: runs, rounds, api_attempts, memory_entries, memory_views, and interventions.
- `data/runs/live/requests/` and `raw/`: stable call-ID/attempt files without authentication headers.
- `data/manifests/`: small, versioned execution plans.
- `reports/live/`: run results, complete trajectory CSVs, resources and costs, condition summaries, threshold sensitivity, and figures.
- `docs/sources/`: pinned paper and official model/pricing documentation, retrieval dates, and SHA‑256 hashes.

```bash
uv run ie498 --data data/runs/live snapshot --out data/backups/live
# Use the timestamp directory printed above; the destination must not exist
uv run ie498 restore data/backups/live/TIMESTAMP data/restored/live-copy
uv run ie498 --data data/restored/live-copy status
```

SQLite snapshots use its consistent backup API. Verified, unchanged request/response files may be shared with older backups; live files and databases are never hard-linked to backups. Restoration verifies every file hash and database integrity, then copies into a new directory. Use restored copies for modifications. Earlier snapshots can be retained losslessly under `data/backups/archives/TIMESTAMP.zip`, with per-archive verification receipts. Extract the timestamp directory before passing it to `ie498 restore`; the original snapshot manifest remains inside. Raw-data snapshots currently exist locally only. Complete raw data, virtual environments, and credentials are Git-ignored; the delivery archive includes data and reports but excludes credentials.

## Interpreting the metrics

The Nash price is approximately 1.47293; the symmetric joint-profit optimum is approximately 1.92498. CI=0 corresponds to Nash joint profit and CI=1 to the joint optimum; negative values are retained. Effective success requires both sellers' prices to exceed Nash+.02 in at least 80% of the final 50 rounds and CI≥.5. Complete runs are independent units; branches are grouped by parent.

`compressed` measures decision-context compression: the system still stores and rereads the complete external raw archive and makes additional compressor calls. API tokens in resource CSVs are actual usage; history/memory `*_upper_bound` components are conservative UTF‑8 byte bounds. See the protocol for details.

## Delivery archive and source history

The GitHub repository contains source, English documentation, figures, and summary tables. Complete raw-data recomputation requires the separate expanded delivery archive at `/workspace/IE498_project.zip`. The full archive is a local deliverable and is not hosted on GitHub; no independent remote raw-data backup is claimed.

The archive contains source, a consistent raw-data snapshot, analysis outputs, and `reports/repository.bundle`; it excludes credentials and the virtual environment. Its `DELIVERY_MANIFEST.json` lists per-file SHA‑256 hashes. An API key is not needed to analyze existing data.

The archived data directory includes its own snapshot manifest. From the extracted `ie498/` directory, restore the original Git history and continue in a separate directory with:

```bash
git clone reports/repository.bundle ../ie498-restored
cd ../ie498-restored
uv sync --extra dev
uv run ie498 restore ../ie498/data/runs/live data/runs/live
uv run ie498 --data data/runs/live analyze --out reports/live
uv run python scripts/compare_extension.py
uv run python scripts/make_report.py
```

Final audit and repackaging require stopped experiments:

```bash
uv run python scripts/audit_data.py
uv run python scripts/package_project.py
```

The [original supplied specification](docs/project_specification.md) is preserved in its original Chinese as source evidence. Historical user quotations in frozen plans are also preserved. Current documentation and generated reports are in English.
