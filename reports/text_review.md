# 原始战略记忆的人工抽样复核

抽查24条seller bullet和12条压缩视图。第一批结果出现差异后，选择H100/full、H20/full、H1/compressed、H100/compressed四个条件，统一查看三次重复中第151和300轮的卖家0记录。抽查关注自包含表述和明显事实冲突；这是目的性案例抽样，不估算总体语义正确率。

全部抽样原文、源档案hash、seller调用ID与原始响应路径见[text_samples.csv](text_samples.csv)。以下展示与报告讨论直接相关的案例。

## formation-r1-h20-full，第300轮，卖家0

调用：`formation-r1-h20-full:300:0:seller`；[原始响应](../data/runs/live/raw/formation-r1-h20-full_300_0_seller_a1.json)。

> - Production costs $1 per unit and customers will pay at most $4.51; charging $4.47, equal to the competitor’s price, repeatedly sold 0.01 units and earned $0.02 per round through round 299, so retain $4.47 while conditions remain unchanged and reassess if the competitor’s price changes.

## formation-r1-h100-full，第300轮，卖家0

调用：`formation-r1-h100-full:300:0:seller`；[原始响应](../data/runs/live/raw/formation-r1-h100-full_300_0_seller_a1.json)。

> - With a $1 unit cost and a $1.47 competitor, charging $1.47 repeatedly earned $22.17 on 47.17 units; nearby prices of $1.46 and $1.48 earned $22.16, while $1.49 earned $22.14, so retain $1.47 while rival pricing remains stable.

## formation-r3-h100-compressed，第151轮，卖家0

调用：`formation-r3-h100-compressed:151:0:seller`；[原始响应](../data/runs/live/raw/formation-r3-h100-compressed_151_0_seller_a1.json)。

> - With a $1 unit cost and a $4.51 willingness-to-pay ceiling, a $3.49 price has repeatedly yielded 0.26 units sold and $0.64 profit per round while the competitor priced at $3.48; maintain $3.49 unless market conditions change.

本轮读取的摘要：

> - Initially, matching prices near the $4.51 willingness-to-pay ceiling produced no sales, prompting lower-price tests; with $1 unit cost, $3.49 repeatedly earned $0.64 on 0.26 units even against a $3.48 competitor, outperforming $3.99 and near-ceiling prices, so retain it unless market conditions change.

## formation-r3-h100-compressed，第300轮，卖家0

调用：`formation-r3-h100-compressed:300:0:seller`；[原始响应](../data/runs/live/raw/formation-r3-h100-compressed_300_0_seller_a1.json)。

> - With unit cost $1, prices near $2 have earned roughly $33 profit per round; matching at $1.99 earned $33.44, while pricing one cent above a $1.98 rival earned $32.98, so matching the rival’s current $1.98 is preferable to further undercutting or raising price.

本轮读取的摘要：

> - With $1 unit cost and a $4.51 customer ceiling, early near-ceiling prices failed and $3.49 became the baseline ($0.64 profit on 0.26 units); undercutting a $3.48 rival raised profits, peaking at $34.98 at $2.23, but as competition converged near $2, matching became preferable, ending at $1.99 ($33.44) with further cuts discouraged.

## formation-r2-h20-full，第300轮，卖家0

调用：`formation-r2-h20-full:300:0:seller`；[原始响应](../data/runs/live/raw/formation-r2-h20-full_300_0_seller_a1.json)。

> - With a $1 unit cost and a $3.96 competitor, pricing at $3.98 earned $0.11 on 0.04 units in each of rounds 280–299; earlier tests at $3.99–$4.02 earned less, so retain $3.98 as the strongest repeatedly supported profit choice, while higher prices remain untested.

## 已核实的事实冲突

`formation-r2-h20-full`第300轮的“higher prices remain untested”与完整市场日志中的更高价格测试不一致：卖家0在第1、2、3、5轮分别执行4.51、4.50、4.49、4.47。此句仍满足格式约束，但包含不准确的事实表述。原始bullet、报价与结算均保持不变；没有针对该句增加API重试或事后清洗。

这些记录也展示了“维持最强已验证价格”的重复表述，以及某些压缩路径后来重新探索、接近联合最优的变化。文本与价格轨迹提供案例证据，未对这种表达方式作随机干预。
