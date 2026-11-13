# Final status

- Model: GPT‑6 Luna with low reasoning for every live seller and compressor.
- Formal experiment: 15 conditions×3 independent repeats×300 rounds; all 45 runs and 13,500 rounds completed.
- Complete v1.1 pilots: 6 (paper_reference, clear, compressed, and 3 full). The later-completed full-2/full-3 are excluded from the formal sample.
- Formal results: 42/45 passed the price criterion; 8/45 also passed the profit criterion. No condition reached an 80% sample success rate; no minimum tested effective H was identified.
- Maintenance/shock: all 3 planned parents failed eligibility in rounds 151–200, so 0 branches were executed. Implementation and offline tests are complete; empirical intervention effects could not be estimated without eligible starting states.
- After the user selected 3 repeats per condition, the 30 unstarted plans in batches 4/5 were marked cancelled_user with zero API costs. All historical records remain preserved.
- v1.0 screening: 5 runs paused under the protocol and 1 exhausted compressor-format retries. Raw responses and failure reasons are retained; these are not complete empirical samples.
- Cost ledger: $32.19904462; the user removed the budget cap; no requests remain in flight. Conservative charges for unknown processing status total $0.103625.
- Validation: 22 tests passed, along with the complete data audit covering 40,917 attempts and 15,634 saved rounds; see reports/data_audit.json.
- Delivery: research report, condition/run metrics, trajectories, resource costs, raw requests/responses, SQLite snapshot, and Git bundle. The packaging script verifies complete restoration before archiving; its receipt is reports/restore_verification.json in the full delivery. The archive's DELIVERY_MANIFEST.json records per-file checksums; its own hash is stored separately in local reports/delivery_manifest.json.
- Source, reports, plots, and summary tables are published on GitHub. Raw-data backups remain local versioned snapshots; the full archive upload failed authentication at GitHub's attachment endpoint. Credentials are excluded from Git, reports, and the archive.

Main report: [research_report.md](../reports/research_report.md). See README for recomputation and recovery commands. Current repository documentation is in English; the original delivery ZIP predates this language update.
