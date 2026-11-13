# Execution performance audit

Audit date: 2026-11-13. Baseline measurements below use the completed original three-repeat database and local raw-response file metadata. No model calls were made for this audit.

## Observed bottleneck

| Formal batch | Attempts | Actual input + output tokens | First-to-last request-start span | Mean token throughput | Median observed request duration | 90th percentile duration | Largest UTC-minute token total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 11,990 | 76,920,689 | 3,647.90 s | 21,086 tokens/s | 2.53 s | 4.27 s | 1,747,708 |
| 2 | 11,990 | 76,957,548 | 3,461.11 s | 22,235 tokens/s | 2.67 s | 4.31 s | 1,782,370 |
| 3 | 11,991 | 76,563,019 | 2,950.75 s | 25,947 tokens/s | 2.57 s | 4.38 s | 1,736,726 |

Spans include any pauses between request starts and exclude the final response tail; they are descriptive execution measurements, not controlled speed comparisons. Request duration is approximated by raw-response file modification time minus the attempt's creation timestamp. It includes request persistence and local response processing, excludes admission waiting, and is not provider-reported inference latency. Minute totals assign actual usage to request-start time, so they do not reproduce the provider's rolling rate-limit accounting. Batch 3 includes one invalid output and its successful retry.

Saved response headers report 5,000 requests/minute and 2,000,000 tokens/minute. Current admission pacing remains 30,000 estimated tokens/second with a 200,000-token burst. At the configured pacing rate, 76.56 million actual tokens alone imply approximately 42.5 minutes of work before estimation overhead, dependency stalls, and response latency. The observed batch-3 span is approximately 49.2 minutes. Increasing request concurrency cannot remove token-volume constraints.

## Local-query measurements

One hundred read-only repetitions against the existing 40,917-attempt database gave:

| Operation | Median | 95th percentile | Query plan |
| --- | ---: | ---: | --- |
| Global spent/reserved totals | 1.625 ms | 1.802 ms | Covering index `budget_totals` |
| Seller archive for `formation-r3-h100-full` | 0.132 ms | 0.344 ms | Existing run/round primary-key index |
| Most recent accepted usage for that seller | 0.023 ms | 0.039 ms | `recent_call` index |

These are warm read-only microbenchmarks on this workspace. They do not measure write/fsync latency, and no throughput claim is inferred for another machine. Current query costs are too small to justify changing accounting transactions or archive integrity for this extension.

## Changes for the extension

The extension coordinator overlaps independent unfinished runs, including repeats 4/5 and newly added paper-reference controls, using a shared caller with at most 48 in-flight requests. This removes the previous scheduling barrier between complete repeat batches and can fill periods when a few slow runs remain. Each run retains its own sequential round dependencies; both seller inputs are fixed before either seller call starts. Scheduling across independent runs changes, so an identical realization of stochastic model outputs is neither expected nor promised.

The HTTP client's maximum total and idle connection counts now equal the caller's concurrency. At 48 concurrent calls, this allows up to 48 reusable connections instead of the previous default cap of 20 idle connections. It avoids unnecessary connection disposal when more independent work is available; it does not promise a measured speedup by itself.

These scheduling changes preserve request bodies, prompts, model/reasoning/output settings, memory visibility, economic settlement, retry policy, timeout values, cost reservations, response persistence, and run-level statistical units. The shared token limiter stays at 30,000 tokens/second with the same burst and provider-backoff behavior. Existing completed runs are not rerun or rewritten. Disk durability and raw-file integrity checks remain enabled.

Compare extension wall-clock timings with these baseline measurements after completion. A precise causal speedup would require a separate controlled benchmark; do not attribute differences in model latency or output lengths solely to the scheduler.

## Observed extension API phase

The following measurements use only the 35 additional run IDs and API attempt rows through 57,680, before any subscription request. Reported tokens include input and output.

| Window | Attempts | Reported tokens | Request-start span | Tokens/s | Relative to batch 3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before first credit rejection | 16,665 | 84,213,623 | 3,118.65 s | 27,003 | +4.1% |
| Entire extension API phase | 16,763 | 84,336,140 | 3,240.68 s | 26,024 | +0.3% |

The final 121.84-second incident window contains 85 zero-usage credit rejections and 13 accepted calls using 122,517 tokens. Before that incident, accepted-call median/p90 observed durations were 2.67/5.01 seconds, compared with 2.57/4.38 seconds in batch 3. These observational measurements are consistent with modest throughput improvement, but do not isolate a scheduling effect: workload composition, trajectory lengths, output lengths, and service latency differ. The subscription continuation is excluded from this comparison.

## Later subscription-interface continuation

After 7,078 extension rounds, API credit exhaustion interrupted execution. The remaining 3,422 rounds resumed through the separately authorized ChatGPT subscription Responses interface. That later change preserves model, reasoning level, original prompt text, and memory rules, but omits the unsupported output-token caps and Chat Completions transport controls. It is distinct from the scheduling changes above. The combined extension duration includes the access pause and two interfaces; its throughput ratio cannot estimate the scheduling speedup. Subscription rate-limit responses use the same bounded retry policy and server-directed backoff. See `reports/extension_execution.json` for recorded resources and [subscription_continuation.md](subscription_continuation.md) for the interface details.
