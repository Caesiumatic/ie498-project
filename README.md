# IE498: Memory and Supracompetitive Pricing

A resumable repeated Bertrand duopoly experiment using **GPT‑6 Luna** for all live agents. The study crosses market-history windows `H={0,1,5,20,100}` with `clear/full/compressed` strategic memory and separately implements the paper's P1 architecture as `paper_reference`.

Start with the [research protocol](docs/protocol.md), [decision log](docs/decisions.md), [experiment status](docs/status.md), and [final research report](reports/research_report.md). Results distinguish mock, smoke, pilot, and formation runs. The user removed the API spending cap and selected 3 independent repeats per condition; all costs remain recorded.

## Completed results

All 45 formal runs (3 per condition, 300 rounds each) and 6 complete pilots are finished. In the formal sample, 8/45 runs met the effective supracompetitive criterion. No minimum tested H met the 80% sample success threshold. None of the three formal H100/full parents qualified for maintenance/shock experiments, so no empirical intervention branches were run; the implementation and offline tests are included. The final cost ledger is $32.19904462. All 22 tests and the complete data audit passed.

Use the analysis commands to recompute results from the delivered data. The smoke/pilot commands below are for new, separately documented experiment versions. The program rejects reuse of a historical run ID with a mismatched configuration. The full delivery archive includes `reports/restore_verification.json`.

## Installation and credentials

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
uv run ie498 --data data/runs/live plan --repeats 3

# 3. Freeze configs/formation-freeze.json after complete pilots
#    Include the complete base.json config, prompt_hash, repeats, and cost basis
uv run ie498 --data data/runs/live formation --repeats 3 --batch 1
# The user removed the spending cap and selected 3 repeats per condition.
# The stage runner also resumes the unfinished paper pilot:
uv run python scripts/run_formation.py

# 4. Reanalyze saved data without API calls
uv run ie498 --data data/runs/live analyze --out reports/live
uv run ie498 --data data/runs/live status
```

Do not switch databases to bypass a project's budget accounting. The formal repeat count must match the frozen plan; each complete batch covers all 15 conditions. Repeating a stage or using `resume` reuses responses only for the same logical call.

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

SQLite snapshots use its consistent backup API. Verified, unchanged request/response files may be shared with older backups; live files and databases are never hard-linked to backups. Restoration verifies every file hash and database integrity, then copies into a new directory. Use restored copies for modifications. Raw-data snapshots currently exist locally only. Complete raw data, virtual environments, and credentials are Git-ignored; the delivery archive includes data and reports but excludes credentials.

## Interpreting the metrics

The Nash price is approximately 1.47293; the symmetric joint-profit optimum is approximately 1.92498. CI=0 corresponds to Nash joint profit and CI=1 to the joint optimum; negative values are retained. Effective success requires both sellers' prices to exceed Nash+.02 in at least 80% of the final 50 rounds and CI≥.5. Complete runs are independent units; branches are grouped by parent.

`compressed` measures decision-context compression: the system still stores and rereads the complete external raw archive and makes additional compressor calls. API tokens in resource CSVs are actual usage; history/memory `*_upper_bound` components are conservative UTF‑8 byte bounds. See the protocol for details.

## Delivery archive and source history

The GitHub repository contains source, documentation, figures, and summary tables. The 343 MB raw-data archive could not be uploaded because GitHub's attachment endpoint rejected the available credentials; it remains at `/workspace/IE498_project.zip`. That original delivery archive predates the English documentation update.

The archive contains source, a consistent raw-data snapshot, analysis outputs, and `reports/repository.bundle`; it excludes credentials and the virtual environment. Its `DELIVERY_MANIFEST.json` lists per-file SHA‑256 hashes. An API key is not needed to analyze existing data.

The archived data directory includes its own snapshot manifest. From the extracted `ie498/` directory, restore the original Git history and continue in a separate directory with:

```bash
git clone reports/repository.bundle ../ie498-restored
cd ../ie498-restored
uv sync --extra dev
uv run ie498 restore ../ie498/data/runs/live data/runs/live
uv run python scripts/make_report.py
```

Final audit and repackaging require stopped experiments:

```bash
uv run python scripts/audit_data.py
uv run python scripts/package_project.py
```

The [original supplied specification](docs/project_specification.md) is preserved in its original Chinese as source evidence. Historical user quotations in frozen plans are also preserved. Current documentation and generated reports are in English.
