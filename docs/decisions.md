# 决策记录

日期按用户时区 America/Chicago，2026‑11‑12。

- D01：新工作区无现有代码或额外课程资料；在 `/workspace/ie498` 初始化独立 Git 仓库，避免修改宿主只读 `.git`。
- D02：下载并核实 arXiv:2404.00806v6，封面2026‑08‑20，修订2026‑08‑31；以G.1 P1与G.2.1为准，不采用G.2.2的不同prefix。
- D03：用户已给API key与明确项目完成请求；预算沿用附件$15，不重复索取密钥。密钥仅在本地被忽略的 `.env`，权限0600。
- D04：最初只查阅 GPT‑4.1 nano/mini、GPT‑4o mini、GPT‑5 nano 文档，未对这些模型调用或筛选。nano已停用。随后用户明确指定所有实验代理均用GPT‑6 Luna；仅使用该模型。
- D05：GPT‑6 Luna low reasoning、无temperature、2048/4096输出上限、独立Chat Completions、固定英文输出格式；与原论文不同之处明确记为methodological replication。
- D06：本地tokenizer词表下载被网络代理403拒绝。离线模块不依赖外部词表；拆分上下文资源用字节上界并明确标注，真实计费严格用API usage。上下文容量检查保守，不截断档案。
- D07：先实现完整离线流程和关键测试，再做smoke、完整pilot、正式冻结。最终规模由完整pilot账本决定，不把mock或失败请求当作研究发现。
- D08：v1.0 pilot 的 compressed 在第17轮压缩连续三次超过60词；seller亦出现两句输出。保留全部失败与已有轮次，停止其余v1.0 runs于checkpoint。预算账本含中断未知尝试的保守预留，至此$0.432514305。v1.1加入JSON schema正则约束（最多60个空格分词、仅句末句号与数值小数点），prompts推荐25–45词并使用分号连接，避免带点缩写。重新从空档案运行独立v1.1 pilot；不截短、不重写、不删除原始输出。原版本prompt和config保存在docs/pilot-v1，完整原代码在d1f6141。
- D09：恢复未知请求保守计费；明确HTTP 4xx且无usage的拒绝记$0。分析/status改为SQLite只读连接。新增memory字数审计与maintenance窗口持续时间，均在正式数据生成前完成。
- D10：后续调用器保存不含认证信息的限流响应头，429尊重Retry-After并共享退避；每轮重验prompt hash，防止长任务中途编辑prompt造成未记录的混合协议。分析补齐各连续指标bootstrap区间和价格/利润成功率的独立Wilson区间。这些工程与报告变更不改变已启动v1.1 pilot的输入内容、市场或采样参数。
- D11：在v1.1 pilot中段发现全档案请求普遍为cache write且无cache hit，不能用短smoke线性估计费用。为优先完整15格coverage，按预先run编号保留full-1，停止两个可选额外full pilot（full-2、full-3），不依据结果优劣选择；两者状态为paused_budget_plan，已付费原始数据全部保留。继续300轮full-1/compressed/clear/paper。重启协调器时未知在途尝试保守计入预算；新增逐run的`.pause`标记使以后可在轮次边界暂停，避免新的在途中断。
- D12：真实响应头确认5000 RPM、2,000,000 TPM。正式批次调用器加入共享token节流（目标30k tokens/s，200k突发，按输入字节×.35+最大输出保守估计调度），并遵循429退避；该调度估计不参与计费或研究资源的精确token统计。
- D13：核对新模型prompt-caching文档后确认默认implicit只在消息末尾写缓存；单条重建消息的末尾每轮变化，解释了零命中。增加可选`explicit_prefix`传输模式：同一user message按原文顺序分text块，仅给完整原始archive最后两个bullet末尾标记缓存边界；拼接文本与原prompt严格相同。clear、compressed seller和paper不写无复用价值的缓存。缓存只复用前缀计算，不添加会话、市场反馈、先前响应或隐藏推理。先用保存的连续prompt作6次独立成本校准，输出不作为行为样本；校准成功后才考虑正式阶段使用。现有pilot继续原API表示，保持其config不变。
- D14：保存的成本校准显示，预热prefix可命中，但新增长seller archive连续调用仍无命中，不能按理想缓存折扣冻结规模。显式分块选项保留为可审计工程能力，正式默认不采用该表示。正式阶段拟采用`cache_mode=off`（explicit模式且不设置breakpoint），保持原来单条user字符串逐字一致，避免无收益的1.25倍cache-write加价；计费将按实际usage继续核验。正式重复数按完整pilot成本与该保守费率冻结，优先15格完整覆盖，不根据行为结果决定是否增加样本。
- D15：shock增加可选`share_parent_first_actions`：仅当子分支首轮的完整请求hash与parent该轮accepted动作严格相同才复用，记录源call ID；随后各轮独立采样。这样冲击轮与自然对照的差别精确为一家的90%执行价，减少同时重新采样引入的差异。该选项不用于formation，也不用于改变H/mode的maintenance分支。
- D16：完整300轮v1.1 pilot：full-1 final50 CI=0.9963，有效成功；clear CI=0.8701，有效成功；compressed CI=-1.2647，未成功。保留这些差异，固定GPT‑6 Luna low与v1.1 prompts，不以正向结果为目标改写策略指令。
- D17：无缓存写入smoke通过，usage确认cache_write_tokens=0。预算冻结时累计$4.82975667；基于完整pilot实际usage、低H只扣除保守估计的history成本、其余archive/output长度仍按H100，15格一批预测$9.47058769。每格3次不可负担，冻结每格1次、T=300，另留4%批次余量、paper每剩余轮$0.003与$0.10缓冲。费用护栏仍为$15硬上限。连续指标n=1不生成虚假的bootstrap精度，成功率保留Wilson宽区间。预算决定重复数不使用行为结果。
- D18：第一批formation仍在运行时，用户明确把总预算从$15提高到$25。全球账本上限已更新，历史run的原config预算字段保持不变；只忽略预算字段进行后续相同科学配置匹配。当前计划扩展为每格2个独立300轮run，第二批保持相同模型、prompt、阈值和随机化规则。原$15冻结快照保存在docs/formation-freeze-budget15.json。若第一批完整实测费用显示剩余预算能以20%余量支付另外两批，可在第二批开始前仅据成本扩展到原目标3次；该规则不读取formation价格、利润或成功结果来决定样本量。
- D19：第一批安全停在轮次边界，所有在途费用已结算、reserved=0，没有新增未知请求。调度以同一run/agent/purpose上一次实际prompt usage为基准，新增字节按每字节最多1 token加256余量，输出按近期usage的1.5倍且至少256估计（不超过输出上限），目标仍30k tokens/s；第一次调用保留保守字节估计。该估计只用于限流，费用预留仍按原严格上界。新加execution_epochs记录后续恢复时的checkpoint和代码commit，原始run/请求/输出不改写。第二批之前按D18的纯成本规则检查是否能达到原目标3次。

- D20：第一批15个条件均完成300轮，在读取其行为结果前依D18仅核算费用：第一批$8.59881490，累计$13.52639979，余额$11.47360021；扩至3次须再预留2×$8.59881490×1.20+$0.10=$20.73715576，不满足。最终固定每格2次。后续批次护栏校准为第一批实际成本加20%余量，原pilot预测保存在original_estimated_batch_cost_usd；paper pilot已完成，无剩余预留。

- D21：第二批进行中，用户明确指示“不设上限，继续”。在轮次边界暂停，累计费用$20.882156395、reserved=0后，将全局预算设为无上限（JSON null），保留实际费用与在途预留，不使用任意巨大数值伪装上限。依据原说明“预算充足时提高到5个或更多”，正式矩阵一次性固定为每格5次（75个300轮run），不按后续结果增加样本。该变更发生在第一批及第二批已完成的10个clear/full结果被查看之后，触发原因是外部预算指令，并非显著性或成功率。原$25冻结快照保存在docs/formation-freeze-budget25.json，D20的2次决定成为历史记录。GPT‑6 Luna low、prompt、阈值、H网格和既有run配置不变。主矩阵完成后补完原已规划的pilot-v11-full-2/3，不混入正式样本，不重做模型选择；随后按第200轮标准对全部5个正式H100/full parent筛选maintenance/shock。
