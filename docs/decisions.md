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
