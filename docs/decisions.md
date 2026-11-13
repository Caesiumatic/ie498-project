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
