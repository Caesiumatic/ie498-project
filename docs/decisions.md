# 决策记录

日期按用户时区 America/Chicago，2026‑11‑12。

- D01：新工作区无现有代码或额外课程资料；在 `/workspace/ie498` 初始化独立 Git 仓库，避免修改宿主只读 `.git`。
- D02：下载并核实 arXiv:2404.00806v6，封面2026‑08‑20，修订2026‑08‑31；以G.1 P1与G.2.1为准，不采用G.2.2的不同prefix。
- D03：用户已给API key与明确项目完成请求；预算沿用附件$15，不重复索取密钥。密钥仅在本地被忽略的 `.env`，权限0600。
- D04：最初只查阅 GPT‑4.1 nano/mini、GPT‑4o mini、GPT‑5 nano 文档，未对这些模型调用或筛选。nano已停用。随后用户明确指定所有实验代理均用GPT‑6 Luna；仅使用该模型。
- D05：GPT‑6 Luna low reasoning、无temperature、2048/4096输出上限、独立Chat Completions、固定英文输出格式；与原论文不同之处明确记为methodological replication。
- D06：本地tokenizer词表下载被网络代理403拒绝。离线模块不依赖外部词表；拆分上下文资源用字节上界并明确标注，真实计费严格用API usage。上下文容量检查保守，不截断档案。
- D07：先实现完整离线流程和关键测试，再做smoke、完整pilot、正式冻结。最终规模由完整pilot账本决定，不把mock或失败请求当作研究发现。
