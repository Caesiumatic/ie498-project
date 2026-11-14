# Core paper reconstruction

This is a new experiment, independent of the completed memory-window project.
The user selected all six Section 3 conditions: P1/P2 × alpha 1, 3.2, 10, with
one independent 300-period run in each cell (1,800 periods; 3,600 accepted seller
calls, plus any retries). It does not include the paper's mechanism interventions
or appendix experiments.

The experimental model is GPT-6 Luna with reasoning `none`. The user explicitly
selected the existing Pro subscription authorization and accepted the inability
to set temperature/top_p through that interface. The actual request and returned
sampling metadata are archived. This is not a claim that only the model and
number of repetitions differ from the authors' implementation.

See [the source-based protocol](../../docs/paper_replication_protocol.md) and
[the official-source search receipt](../../docs/paper_replication_source_search.md).
Unspecified implementation choices, including numeric formatting and parsing,
are disclosed. The primary price ceiling follows footnote 18's numerical rule;
it is a textual prompt value, not a hard limit on executed prices.

## Commands

From the repository root, using the existing Python environment:

```bash
.venv/bin/python scripts/run_paper_replication.py preview --transport chatgpt_subscription
.venv/bin/python scripts/run_paper_replication.py prepare --transport chatgpt_subscription
.venv/bin/python scripts/run_paper_replication.py run --transport chatgpt_subscription
.venv/bin/python scripts/run_paper_replication.py status
.venv/bin/python scripts/run_paper_replication.py audit
.venv/bin/python scripts/report_paper_replication.py
```

`prepare` freezes actual transport, source hashes, prompt hashes, and all six
conditions before any inference. Re-running `run` recovers accepted responses
only for their original logical calls. A changed protocol is rejected. Saved
market settlements and prior inputs are verified before continuation. Each round
settles only after both independent seller outputs have been durably accepted.

Ten malformed completed outputs stop the corresponding run. Infrastructure
failures have a separate three-failure pause limit because the paper does not
specify network failure handling. Access/model/protocol errors pause execution;
there is no model or billing fallback, and no quota-sufficiency query.

Raw requests, responses, per-round state, accounting and the SQLite database live
under ignored `data/runs/paper_replication/`. New reports go to
`reports/paper_replication/`; earlier reports remain historical artifacts.
