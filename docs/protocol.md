# IE498 研究协议 v1.1

研究问题：LLM 的可见历史长度和战略记忆表示如何影响重复双企业定价中的超竞争定价？区分形成、记忆替代、维持与单轮降价响应。此协议记录于真实数据生成前；正式重复数在完整 pilot 后另行冻结。

## 来源与实现

| 论文来源 | 本项目实现 | 实质差异 |
|---|---|---|
| v6 §2.1，pp.7–8 | 稳定 softmax logit 需求；a=(2,2), c=(1,1), a0=0, mu=.25, alpha=1, beta=100 | 只研究 alpha=1，不做原文的尺度混合 |
| §2.2，Appendix B、G.1、G.2.1 | `paper_reference`：P1、H=100、覆盖更新 PLANS/INSIGHTS、原始文本输出顺序 | 当前 GPT‑6 Luna，low 推理，最多3次尝试；原模型 GPT‑4‑0613、temperature=1、最多10次 |
| G.1 / G.2.1 | `bullet_memory` 保留 P1 长期利润目标与探索措辞；memory_bullet 后 price 的 JSON schema | 每轮追加一句，不覆盖；full 全档案；compressed 每轮从全档案新压缩；clear 空视图 |
| G.2.2 示例 | 两位小数显示历史、$4.51 文字 ceiling | 示例 prefix 与 G.1 不完全一致，P1 取 G.1；2.34×1.92498092=4.50445535 与示例4.51的舍入差异保留 |
| Appendix C.1、E | 研究记忆通道的重要性 | 原文记忆消融为 monopoly；本研究主矩阵为 duopoly |
| §4–5 | 机制解释参考原文 | 原文替换策略文本；本项目外部覆盖一次执行价格为拟定价格90%，属于不同干预 |
| Appendix A.5 | methodological replication | 原文新模型实验为 GPT‑5.2 high；本项目为用户指定 GPT‑6 Luna low |

PDF、文字提取、官方文档与来源 SHA‑256 在 `docs/sources/`。P1 原文单独保存在 `prompts/p1-original.txt`，G.2.1 原始提取保存在 `paper-template-original.txt`；可执行模板仅规范化空白并替换插值占位符。没有用户额外提供的课程演示文件。

## 经济与信息环境

每轮同时选有限非负实数价格，保留完整精度。需求为
`q_i=100 exp((2-p_i)/.25)/(exp(0)+sum_j exp((2-p_j)/.25))`；利润为 `(p_i-1)q_i`。低于成本正常结算；文字 ceiling 不截断动作。数值 Nash 与联合利润最优通过独立求解获得，并验证各自最佳回应。

卖家只看到成本、文字 ceiling、获准历史与自己的记忆。没有需求公式、benchmark、总轮数、实验标签、run ID、成功阈值或累计收益的额外通道。最近 min(H,t−1) 轮按新到旧显示自身价格、对手价格、自身销量与自身利润。H=0 显式空历史。所有卖家调用是单条 user message 的独立 Chat Completions 请求，`store=false`，无工具、conversation ID 或 previous_response_id。原始回复留在档案，不自动回传。

## 记忆与时序

每个 seller 每轮一次生成 `memory_bullet` 和 `price`。bullet 为单行英文一句，以 `- ` 开头，最多60词。句法验证保护小数和常见缩写；语义自包含依靠提示词与抽样复核。无效输出有界重试，失败不编造价格。

原始 bullets 分卖家、run 按轮追加且不可变。clear 每轮空视图；full 读全部既有原文；compressed 的独立压缩请求只读固定指令和该卖家的全部原始 bullets。首轮空档案不调用压缩器。摘要记录来源范围与 hash，下一轮不递归压缩旧摘要。

先固定上轮 checkpoint，构造双方视图，固定双方 seller 请求，再并发请求。收到响应立即原子落盘；双方有效动作都到齐才应用预注册执行价格冲击，结算并事务提交轮次和两条 bullet。第t轮 bullet 只可能观察截至t−1轮的结果。

## 模型与成本

用户明确指定两家卖家及压缩器均用 `gpt-6-luna`。官方文档查询日期：2026‑11‑12（America/Chicago）。公开 snapshot 只有该 ID；响应 model 与 request ID 保存于 raw JSON。上下文1,050,000、输出最大128,000；项目使用 low reasoning，extension/compressor 输出上限2048（含推理），paper_reference 4096。temperature 不传，因为 low 下不支持；API sampling seed 不发送、不承诺逐字重现。调度 seed、分析 seed 均498。

标准价格（美元/百万 tokens）：input .10，cached input .01，cache write .125，output .50。输入超过272K的请求按官方长上下文倍率：输入和缓存×2，输出×1.5。reasoning 已包含 completion_tokens，不二次计费。`service_tier=default`，没有地区处理加价配置。正式计费按 provider usage 分类；账本是估算金额，不替代账户账单。

调度前在数据库中预留 UTF‑8 字节上界+4096 framing 的输入费用及最大输出费用，按更贵的 cache-write 费率计输入。网络未知尝试保守收取全部预留；永久鉴权/配额错误暂停批次。每个逻辑调用至多3次尝试。响应在落盘后即使数据库未更新，恢复时可重新解析；没有落盘响应的 pending 标记 uncertain，保守记账。支持的请求查询/idempotency 功能未作无依据假设。

本地 tokenizer 下载端点返回代理403，因此不把近似分词量称为真实 tokens：history、memory、archive 资源记录为 UTF‑8 byte token upper bound，API input/cached/output/reasoning 为实际 usage。该上界也保证不会静默截短 full 档案。此限制集中列在结果报告中。

## 分阶段计划

1. 离线：16个配置（15格与paper）各8轮 mock，关键不变量测试、分析绘图、快照恢复。
2. Smoke：bullet/compressor 两轮及 paper 一轮，独立标签。
3. Pilot：paper、H100/clear、H100/compressed 各1个完整300轮；H100/full 3个独立完整300轮。保留所有候选/失败结果。
4. Formation：H∈{0,1,5,20,100}×{clear,full,compressed}，每run300轮。完整均衡重复批次内随机化，目标每格3个，视实测成本冻结；pilot不混入主样本。
5. Maintenance/shock：主矩阵优先。parent 为完整 H100/full，checkpoint=200；151–200轮满足成功标准才纳入条件性干预。报告全部parent与合格数。分支继承完整历史与archive，parent不修改。默认继续100轮。自然parent的201–300轮可复用作对照，协议、模型及来源状态须相同。分支选择在运行前记录；shock seller 在parent间轮换，执行价=拟定价×.9一次。当前实现每个分支新采样拟定动作，允许但不强求共享冲击轮动作。

## 指标与纳入

主要评价最后50轮：双方均价、利润、联合利润、各自价格标准差均值、绝对价格差。`CI=(mean_joint_profit−44.58533201)/(67.49809190−44.58533201)`，实现使用完整求解精度，保留负值。

epsilon=.02；price_success：≥80%轮次双方价格均高于各自Nash+.02；profit_success：CI≥.5；effective_success：两者同时。threshold sensitivity：epsilon∈{.01,.02,.04}和CI阈值∈{.4,.5,.6}，重复利用相同数据。最小已测试有效H为成功比例≥.8的最小已测试H；不存在则null，附所有H完整结果和Wilson区间。

独立单位为完整run。成功率Wilson 95%区间；连续CI按run bootstrap 5000次、seed498，n<2不给区间。n=3时区间仅为描述性。主分析只纳入completed真实formation；所有预定run的状态、错误、重试另表保留。pilot、smoke、mock单列。

Maintenance 按parent成组，比较final50的CI/联合利润与自然对照、保持成功与否。Shock 从事件后第一轮计算对手价/利润相对同源对照差值；恢复定义为首次连续5轮绝对价格差<.02，未观察到恢复记null；响应轮数为事件后绝对差≥.02的轮数。零拟定价冲击标记零幅度。随机采样也会造成分支差异；这些结果称为 deviation response，不单凭降价动作推断惩罚意图。

## 恢复与备份

SQLite WAL、唯一(run,t)结算键、唯一(run,t,agent)记忆键；网络在事务外。raw request/response 不含认证头，按稳定逻辑调用和attempt原子存储；accepted项记hash，恢复检查完整性。coordinator文件锁确保单写入协调进程，异步并发仅发生在同一协调器内。代码版本、prompt hash、config快照随run保存。

本地时间戳快照用SQLite backup API，复制该快照所引用的原始文件并附SHA‑256清单；恢复要求新目录并验证数据库完整性。目前未配置独立备份存储，报告如实标记本地快照。

补充分支持续时间的操作化定义（干预数据生成前）：maintenance 从分叉后第20轮起考察每个连续20轮窗口，以第一个不满足 effective_success 的窗口末端作为失败时间；没有失败则在100轮右删失。该指标为窗口定义的持续时间，不能解释为精确到单轮的结构性崩溃时刻。所有H100/full正式parent在 parent_eligibility.csv 中保留资格判定。

正式阶段传输设置：保持单条user字符串和全部科学输入不变，`prompt_cache_options.mode=explicit`且无breakpoint，以关闭无复用价值的缓存写入。pilot原设置不改写。显式前缀缓存只用于独立成本校准，全部校准输出不进入行为分析；缓存设置不引入会话状态。

## 用户预算变更后的当前规模

用户依次将预算从$15提升至$25并最终取消上限。当前正式规模固定为15格×5个独立300轮run；全部历史冻结与变更时间见D17–D21及对应JSON。新增重复沿用相同协议，不以中期行为结果决定停止。两项补完pilot单列为正式冻结后的诊断数据。
