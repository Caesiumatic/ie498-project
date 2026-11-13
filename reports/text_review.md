# Manual sample review of original strategic memory

The review samples 24 seller bullets and 12 compressed views. After differences appeared in the first batch, four conditions were selected: H100/full, H20/full, H1/compressed, and H100/compressed. Seller 0 records from rounds 151 and 300 were examined consistently across all three repeats. The review focuses on self-contained wording and obvious factual inconsistencies. This is purposive case sampling, not an estimate of overall semantic accuracy.

See [text_samples.csv](text_samples.csv) for all sampled originals, source archive hashes, seller call IDs, and raw-response paths. The cases below directly support the report discussion. Raw-response files are available in the full data archive.

## formation-r1-h20-full, round 300, seller 0

Call: `formation-r1-h20-full:300:0:seller`; [raw response](../data/runs/live/raw/formation-r1-h20-full_300_0_seller_a1.json).

> - Production costs $1 per unit and customers will pay at most $4.51; charging $4.47, equal to the competitor’s price, repeatedly sold 0.01 units and earned $0.02 per round through round 299, so retain $4.47 while conditions remain unchanged and reassess if the competitor’s price changes.

## formation-r1-h100-full, round 300, seller 0

Call: `formation-r1-h100-full:300:0:seller`; [raw response](../data/runs/live/raw/formation-r1-h100-full_300_0_seller_a1.json).

> - With a $1 unit cost and a $1.47 competitor, charging $1.47 repeatedly earned $22.17 on 47.17 units; nearby prices of $1.46 and $1.48 earned $22.16, while $1.49 earned $22.14, so retain $1.47 while rival pricing remains stable.

## formation-r3-h100-compressed, round 151, seller 0

Call: `formation-r3-h100-compressed:151:0:seller`; [raw response](../data/runs/live/raw/formation-r3-h100-compressed_151_0_seller_a1.json).

> - With a $1 unit cost and a $4.51 willingness-to-pay ceiling, a $3.49 price has repeatedly yielded 0.26 units sold and $0.64 profit per round while the competitor priced at $3.48; maintain $3.49 unless market conditions change.

Summary read in this round:

> - Initially, matching prices near the $4.51 willingness-to-pay ceiling produced no sales, prompting lower-price tests; with $1 unit cost, $3.49 repeatedly earned $0.64 on 0.26 units even against a $3.48 competitor, outperforming $3.99 and near-ceiling prices, so retain it unless market conditions change.

## formation-r3-h100-compressed, round 300, seller 0

Call: `formation-r3-h100-compressed:300:0:seller`; [raw response](../data/runs/live/raw/formation-r3-h100-compressed_300_0_seller_a1.json).

> - With unit cost $1, prices near $2 have earned roughly $33 profit per round; matching at $1.99 earned $33.44, while pricing one cent above a $1.98 rival earned $32.98, so matching the rival’s current $1.98 is preferable to further undercutting or raising price.

Summary read in this round:

> - With $1 unit cost and a $4.51 customer ceiling, early near-ceiling prices failed and $3.49 became the baseline ($0.64 profit on 0.26 units); undercutting a $3.48 rival raised profits, peaking at $34.98 at $2.23, but as competition converged near $2, matching became preferable, ending at $1.99 ($33.44) with further cuts discouraged.

## formation-r2-h20-full, round 300, seller 0

Call: `formation-r2-h20-full:300:0:seller`; [raw response](../data/runs/live/raw/formation-r2-h20-full_300_0_seller_a1.json).

> - With a $1 unit cost and a $3.96 competitor, pricing at $3.98 earned $0.11 on 0.04 units in each of rounds 280–299; earlier tests at $3.99–$4.02 earned less, so retain $3.98 as the strongest repeatedly supported profit choice, while higher prices remain untested.

## Verified factual inconsistency

The round-300 claim in `formation-r2-h20-full` that “higher prices remain untested” conflicts with the complete market log: seller 0 executed 4.51, 4.50, 4.49, and 4.47 in rounds 1, 2, 3, and 5, respectively. The sentence satisfies format constraints but contains an inaccurate factual statement. The original bullet, price, and settlement remain unchanged; it triggered neither additional API retries nor post hoc cleaning.

These records also show repeated language about retaining the strongest tested price, as well as later renewed exploration toward the joint optimum in some compressed paths. Text and price trajectories provide case evidence; this wording was not randomly manipulated.
