# 当前阶段

- 代码、协议、恢复、分析与备份流程完成；20项关键测试通过。
- 原始mock：16个配置各8轮，快照恢复验证通过。
- v1.0 pilot：格式筛选后停止，数据与失败全部保留。
- v1.1 full-1：300轮完成，final50 CI≈0.996，有效成功。
- v1.1 clear、compressed、paper：继续运行；两个可选full pilot因预算优先级停止，未作为完成样本。
- 所有真实卖家与压缩器均为GPT‑6 Luna low。
- Formation：等待完整clear/compressed成本；用scripts/freeze_plan.py按成本冻结均衡重复数，再运行scripts/run_formation.py。
- 主矩阵优先；maintenance/shock只对合格parent用剩余预算执行。

实时状态以SQLite与CLI status为准。密钥不进入Git、报告或交付包。
