# IE498 experiment results

The database contains 102 planned runs, of which 61 are completed. The cost ledger is $42.152088; budget: uncapped (user-authorized).

Live experiments, mock, smoke, and pilot runs are labeled separately. Only completed formation runs enter the main matrix. Each complete duopoly run is an independent statistical unit; rounds within a run are not independent observations.

| Mode | H | n | Success | Mean CI |
|---|---:|---:|---:|---:|
| clear | 0 | 3 | 0/3 | -1.932 |
| clear | 1 | 3 | 0/3 | -1.755 |
| clear | 5 | 3 | 1/3 | 0.109 |
| clear | 20 | 3 | 0/3 | -1.287 |
| clear | 100 | 3 | 2/3 | 0.010 |
| compressed | 0 | 3 | 0/3 | -1.945 |
| compressed | 1 | 3 | 1/3 | -0.765 |
| compressed | 5 | 3 | 1/3 | -0.459 |
| compressed | 20 | 3 | 1/3 | -0.983 |
| compressed | 100 | 3 | 1/3 | -0.722 |
| full | 0 | 3 | 0/3 | -1.828 |
| full | 1 | 3 | 1/3 | -1.004 |
| full | 5 | 3 | 0/3 | -1.908 |
| full | 20 | 3 | 0/3 | -1.896 |
| full | 100 | 3 | 0/3 | -1.276 |

## Added paper-reference comparison (H=100)

This condition overwrites PLANS/INSIGHTS each round. It was added after inspecting the original three-repeat results; its five new formal runs are separate from pilots and from the 15-cell bullet-memory matrix. Repeat labels do not imply contemporaneous or paired sampling.

No completed formal paper-reference runs are available yet; historical paper pilots are not substituted.

See paper_reference_conditions.csv and paper_reference_comparison.csv for separate condition estimates and uncertainty intervals.

See runs.csv for complete status, resources.csv for calls and resources, and benchmarks.json for numerical benchmarks. Success proportions use Wilson intervals; continuous metrics use run-level bootstrap intervals (none for n<2).

Analyzed 0 completed child branches; see paired.csv for paired analysis.
