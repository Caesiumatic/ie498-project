# IE498 project rules

- Communicate with the user in Chinese; write repository documentation, code, seller/compressor prompts, and chart labels in English. Preserve the original supplied specification and historical quotations as source evidence.
- The user removed the API spending cap; the formal matrix is fixed at 3 repeats per condition. Continue accounting for every call. API keys belong only in environment variables or an ignored `.env`.
- Never rewrite historical bullets. Route all feedback through `visible_history`; H=0 must be empty.
- Fix both seller inputs before concurrent calls in a round; commit settlement and both memory entries in one transaction.
- Resume by logical call ID. Sample again in a new round even for identical prompts; never reuse outputs across runs.
- Do not silently change the model, prompts, thresholds, or formal repeat count. Record protocol changes in docs/decisions.md.
- A complete run is the statistical unit; group branches by parent. Mock outputs are not empirical evidence.
- Common commands: `uv sync --extra dev`, `uv run pytest -q`, `uv run ie498 --help`.
- Keep raw data and credentials out of Git. Back up with the SQLite backup API and restore into a new directory.
