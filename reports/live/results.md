# IE498 experiment results

The database contains 102 planned runs, of which 96 are completed. The API cash ledger is $42.152088; budget: uncapped (user-authorized). This ledger includes conservative estimates for uncertain API-key requests and is not an invoice.

There are 10470 recorded ChatGPT subscription attempts. Their observed tokens are reported separately in resources.csv; they add no API cash charge to this ledger. The retained cost_usd column is an alias for api_cash_ledger_usd, not total resource cost. Mixed billing paths prevent interpreting pooled dollar differences as memory-efficiency effects.

Live experiments, mock, smoke, and pilot runs are labeled separately. Only completed formation runs enter the main matrix. Each complete duopoly run is an independent statistical unit; rounds within a run are not independent observations.

| Mode | H | n | Success | Mean CI |
|---|---:|---:|---:|---:|
| clear | 0 | 5 | 0/5 | -1.934 |
| clear | 1 | 5 | 0/5 | -1.814 |
| clear | 5 | 5 | 2/5 | -0.142 |
| clear | 20 | 5 | 0/5 | -1.538 |
| clear | 100 | 5 | 2/5 | -0.452 |
| compressed | 0 | 5 | 0/5 | -1.945 |
| compressed | 1 | 5 | 1/5 | -0.969 |
| compressed | 5 | 5 | 1/5 | -0.977 |
| compressed | 20 | 5 | 1/5 | -0.911 |
| compressed | 100 | 5 | 1/5 | -1.194 |
| full | 0 | 5 | 0/5 | -1.875 |
| full | 1 | 5 | 1/5 | -1.376 |
| full | 5 | 5 | 0/5 | -1.919 |
| full | 20 | 5 | 0/5 | -1.761 |
| full | 100 | 5 | 0/5 | -1.155 |

## Added paper-reference comparison (H=100)

This condition overwrites PLANS/INSIGHTS each round. It was added after inspecting the original three-repeat results; its five new formal runs are separate from pilots and from the 15-cell bullet-memory matrix. Repeat labels do not imply contemporaneous or paired sampling.

| Architecture | Memory | H | n | Success | Mean CI |
|---|---|---:|---:|---:|---:|
| bullet_memory | clear | 100 | 5 | 2/5 | -0.452 |
| bullet_memory | compressed | 100 | 5 | 1/5 | -1.194 |
| bullet_memory | full | 100 | 5 | 0/5 | -1.155 |
| paper_reference | overwritten_plans_insights | 100 | 5 | 0/5 | -0.348 |

See paper_reference_conditions.csv and paper_reference_comparison.csv for separate condition estimates and uncertainty intervals.

See runs.csv for complete status, resources.csv for calls and resources, and benchmarks.json for numerical benchmarks. Success proportions use Wilson intervals; continuous metrics use run-level bootstrap intervals (none for n<2).

Analyzed 0 completed child branches; see paired.csv for paired analysis.
