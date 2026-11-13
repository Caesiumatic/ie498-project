# IE498：记忆与超竞争定价

可恢复的重复 Bertrand 双企业实验。真实模型统一为 **GPT‑6 Luna**，研究 `H={0,1,5,20,100}` 与 `clear/full/compressed` 三种战略记忆；独立实现论文 P1 的 `paper_reference`。

入口：[研究协议](docs/protocol.md)、[决策记录](docs/decisions.md)、[实验状态](docs/status.md)、[最终研究报告](reports/research_report.md)。所有数值结果均注明 mock、smoke、pilot 或 formation。总API预算$25。

## 安装与密钥

```bash
cd /workspace/ie498
uv sync --extra dev
cp .env.example .env  # 仅首次配置时执行；不要覆盖已有密钥
chmod 600 .env
# 在本地编辑 .env 或设置环境变量 OPENAI_API_KEY；不要提交密钥
uv run pytest -q
uv run ie498 benchmarks
```

受限环境可以设置 `UV_CACHE_DIR=/tmp/ie498-uv`、`XDG_CACHE_HOME=/tmp/ie498-cache`。项目已创建 `.venv`，也可直接用 `.venv/bin/ie498` 与 `.venv/bin/pytest`。使用已锁定的 `uv.lock`。没有额外数据库服务或网页依赖。

## 运行顺序

```bash
# 1. 离线管线；mock数据另库保存
uv run ie498 --data data/runs/mock mock --rounds 8
uv run ie498 --data data/runs/mock analyze --out reports/mock

# 2. 付费调用，沿用同一个live数据库保证累计预算连续
uv run ie498 --data data/runs/live smoke --concurrency 1
uv run ie498 --data data/runs/live pilot --concurrency 6
uv run ie498 --data data/runs/live plan --repeats 3

# 3. 完整pilot后按实际成本冻结 configs/formation-freeze.json
#    包含 config=base.json的完整对象、prompt_hash、repeats、成本依据
uv run ie498 --data data/runs/live formation --repeats 2 --batch 1
# 用户把总预算提高到$25后，计划扩展为每格2次；目标3次的成本规则见freeze与决策记录。
# 同时接续未完成paper pilot的完整阶段运行器：
uv run python scripts/run_formation.py

# 4. 仅从已保存数据重新分析，不调用API
uv run ie498 --data data/runs/live analyze --out reports/live
uv run ie498 --data data/runs/live status
```

不要为同一付费项目换数据库绕过预算。正式重复数必须与freeze一致；每个完整批次覆盖15格。再次执行同一阶段或 `resume` 会复用相同逻辑调用的响应。

对运行中的单个run，可创建 `data/runs/live/RUN_ID.pause` 标记，在当前轮提交后暂停；恢复前删除该标记。Ctrl+C也能中断，但服务端已处理、尚未落盘的请求会标为uncertain并按预留保守计费。

```bash
uv run ie498 --data data/runs/live resume pilot-full-1
# 全部未完成run（先处理status中的具体错误）
uv run ie498 --data data/runs/live resume
# 按单个配置启动一个独立paper pilot（会继续使用同一个预算账本）
uv run ie498 --data data/runs/live --config configs/paper_reference.json run paper-additional
```

每个逻辑调用最多3次尝试，重试耗尽不会无限重新付费；保留raw输出供研究复核。新独立重复应使用新run ID。prompt文件改变时恢复会被阻止；请恢复生成该run的版本。模型、prompt或科学参数变动先记录决策并建立新实验版本。

## 分叉与单轮冲击

先按协议检查parent的151–200轮，记录全部parent与符合成功条件的数量，并冻结分支选择；主矩阵优先。

```bash
# 替换为真实存在且合格的完整parent ID
uv run ie498 --data data/runs/live fork formation-r1-h100-full maint-r1-clear \
  --checkpoint 200 --H 1 --mode clear --run
uv run ie498 --data data/runs/live fork formation-r1-h100-full shock-r1 \
  --checkpoint 200 --H 100 --mode full --shock-agent 0 --share-actions --run
```

分支默认继续100轮，继承市场历史和完整私人档案。shock只在201轮把指定卖家的执行价乘0.9，模型原报价与bullet不变；下一轮反馈实际成交结果。`--share-actions`要求首轮请求hash与parent完全一致并复用该轮拟定动作，后续轮次重新采样。完整parent自然延续可作配对对照，原数据不修改。

## 数据与恢复

- `data/runs/live/experiments.sqlite`：runs、rounds、api_attempts、memory_entries、memory_views、interventions。
- `data/runs/live/requests/`、`raw/`：稳定调用ID/attempt文件；不含认证头。
- `data/manifests/`：小型版本化计划清单。
- `reports/live/`：run级结果、全轨迹CSV、资源成本表、条件汇总、阈值敏感性、图表。
- `docs/sources/`：固定论文、官方模型/计费文档、检索日期与SHA‑256。

```bash
uv run ie498 --data data/runs/live snapshot --out data/backups/live
# source换成上一条命令输出的时间戳目录；destination必须不存在
uv run ie498 restore data/backups/live/TIMESTAMP data/restored/live-copy
uv run ie498 --data data/restored/live-copy status
```

SQLite备份使用一致性API，恢复验证全部文件hash和数据库完整性。目前只有本地快照，尚无独立远端备份。完整数据、虚拟环境和密钥被Git忽略；交付归档会包含数据和报告，但排除密钥。

## 指标解释

Nash价格约1.47293，联合最优对称价格约1.92498。CI=0对应Nash联合利润，CI=1对应联合最优；保留负值。有效成功要求最后50轮中至少80%轮次双方价格均>Nash+.02，且CI≥.5。完整run为独立单位；分支按parent聚合。

`compressed`度量的是定价上下文压缩：它仍保存并读取完整外部原始档案，并产生额外压缩调用。资源CSV中API tokens为真实usage；history/memory拆分的`*_upper_bound`是UTF‑8字节保守上界。详见协议。
