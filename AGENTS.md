# IE498 项目规则

- 中文解释；英文代码、seller/compressor prompts 与图表标签。
- 真实请求总预算 $15；API key 仅用环境变量或被忽略的 `.env`。
- 不改写历史 bullets；所有反馈经 `visible_history`；H=0 必须为空。
- 同轮两家 seller 输入先固定再并发；结算与两条记忆在同一事务中提交。
- 恢复使用逻辑调用 ID；新轮次相同 prompt 仍然采样；不能跨 run 复用输出。
- 不静默修改模型、prompt、阈值或正式重复数；协议变化写入 docs/decisions.md。
- 完整 run 是统计单位，分支按 parent 分组；mock 不能作为实证结果。
- 常用：`uv sync --extra dev`、`uv run pytest -q`、`uv run ie498 --help`。
- 原始数据与密钥不进 Git；备份用 SQLite backup API；恢复到新目录。
