# IE498 project rules

- Communicate with the user in Chinese; write repository documentation, code, seller/compressor prompts, and chart labels in English. Preserve the original supplied specification and historical quotations as source evidence.
- The completed memory experiment has 5 repeats per condition plus 5 H100 paper-reference runs. Preserve that frozen matrix and its historical data. The separately authorized paper reconstruction has P1/P2 × alpha 1, 3.2, 10, one 300-period run per cell; see docs/paper_replication_protocol.md. Continue accounting for every call. API keys belong only in environment variables or an ignored `.env`.
- Never rewrite historical bullets. Route all feedback through `visible_history`; H=0 must be empty.
- Fix both seller inputs before concurrent calls in a round; commit settlement and both memory entries in one transaction.
- Resume by logical call ID. Sample again in a new round even for identical prompts; never reuse outputs across runs.
- Do not silently change the model, prompts, thresholds, or formal repeat count. Record protocol changes in docs/decisions.md.
- A complete run is the statistical unit; group branches by parent. Mock outputs are not empirical evidence.
- Common commands: `uv sync --extra dev`, `uv run pytest -q`, `uv run ie498 --help`.
- Keep raw data and credentials out of Git. Back up with the SQLite backup API and restore into a new directory.
- The independent paper reconstruction uses only experiments/paper_replication/prompts and data/runs/paper_replication. The user selected GPT-6 Luna with reasoning none via the existing Pro subscription authorization, accepting that this interface cannot explicitly set temperature/top_p. Record that limitation; never silently fall back to API billing or change the completed memory experiment's prompts.
