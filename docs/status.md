# 当前阶段

- 离线实现：完成。
- 关键测试：16项通过。
- Mock：15个记忆条件与paper_reference各8轮，共16个run；已完成导出、绘图、一致性快照与恢复检查。
- 真实smoke：GPT‑6 Luna完成bullet/compressor两轮和paper_reference一轮；8个调用有效，费用$0.001045。
- 完整pilot：6个300轮run运行中；与正式样本分开保存。
- Formation：待完整pilot成本与行为检查后冻结重复数。
- Maintenance/shock：实现完成；主矩阵之后按剩余预算和合格parent执行。

实时状态以 `ie498 --data data/runs/live status` 和SQLite为准。此文件在阶段完成后更新。
