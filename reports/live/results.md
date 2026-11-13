# IE498 实验结果

数据库包含 97 个计划 run，已完成 61 个；费用账本为 $32.199045，预算 无上限（用户授权）。

真实实验、mock、smoke、pilot 分别标记；只有 completed 的 formation run 纳入主矩阵统计。每个完整双企业 run 是独立统计单位，单个 run 的轮次不是独立样本。

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

完整状态见 runs.csv；调用与资源见 resources.csv；数值基准见 benchmarks.json；成功率区间采用 Wilson，连续指标按 run bootstrap（n<2 不给区间）。

已分析 0 个完成的子分支；配对分析见 paired.csv。
