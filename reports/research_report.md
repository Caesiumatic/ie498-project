# IE498：战略记忆与重复双企业博弈中的超竞争定价

## 摘要

本项目在 logit 需求的重复 Bertrand 双企业博弈中，研究可见市场历史 H∈{0,1,5,20,100} 与 clear、full、compressed 战略记忆的影响。所有真实卖家和压缩器使用用户指定的 GPT‑6 Luna，low 推理设置。主实验独立单位为300轮的完整双企业run。

当前已完成 **45 个正式formation run**，其中 **8 个**满足预先定义的有效超竞争标准。完成的pilot有 6 个；中断/失败pilot保留在独立记录中。费用账本共 **$32.199045**，其中未知处理状态的保守计费 **$0.103625**，预算状态为无上限（用户授权）。下文仅依据已保存数据陈述结论。第4、5批的30个未开始计划按用户指令取消，未产生API费用。

## 研究问题与博弈机制

两家企业同时设价，各自最大化长期利润。产品有差异化，需求取决于双方价格和外部选项；因此价格反应既有当期市场份额效应，也可能影响未来竞争对手的行为。LLM通过文字历史和自身写下的策略记录适应市场，不通过训练更新权重。

四个问题分别是：超竞争定价如何形成；一句摘要能否替代较长原始历史；减少记忆后已形成的高利润定价能维持多久；竞争对手单轮执行价格下降后出现何种动态响应。

## 论文复现与本项目扩展

基础论文为 Fish、Gonczarowski、Shorrer 的 *Algorithmic Collusion by Large Language Models*，固定 arXiv:2404.00806v6。论文§2.1提供环境，§2.2与Appendix B提供信息与API架构，G.1/G.2.1提供P1和通用模板。原始PDF及SHA‑256保存在 docs/sources。原文memory消融在monopoly中完成；本项目在duopoly中改变记忆机制，因此不是原消融的直接复制。

`paper_reference`保留P1、100轮历史以及覆盖更新的PLANS/INSIGHTS；`bullet_memory`每轮追加一句最多60词的原始bullet。clear仍写入但不读取；full读取全部原文；compressed每次用新的独立请求压缩全部原始bullet，给seller一句摘要。摘要不递归替代外部档案。H100/full是扩展基线，paper_reference是单独架构对照。当前模型与原GPT‑4‑0613及A.5的GPT‑5.2 high不同，故称为methodological replication。

## 实验协议与可靠性

本项目参数下，每轮需求为 `qᵢ = 100 exp((2−pᵢ)/0.25) / [1 + exp((2−p₁)/0.25) + exp((2−p₂)/0.25)]`，利润为 `πᵢ = (pᵢ−1)qᵢ`；分母中的1代表外部选项。市场参数 a1=a2=2、a0=0、mu=.25、c1=c2=1、alpha=1、beta=100。稳定softmax结算，保留完整价格精度，展示历史时四舍五入两位小数。计算所得Nash价格1.47292666、每家利润22.29266600；联合最优对称价格1.92498092、每家利润33.74904595。数值求解同时验证最佳回应；单产品monopoly使用独立的对应环境。

卖家只读成本、$4.51文字ceiling、最近H轮允许的反馈和自身记忆，不读需求公式、研究条件、成功阈值或剩余轮数。H=0无市场反馈；此时full/compressed积累的是自生成策略，而不是环境观测。双方输入在本轮任一响应返回前固定；本轮bullet只能引用截至上一轮的结果。执行价冲击在双方提交后应用。

独立Chat Completions请求不携带会话链接，不给工具访问。SQLite事务保证一次结算与一次追加；有效响应按逻辑调用缓存，仅用于同一调用恢复。新轮次即使prompt相同仍重新采样。调用前预留在途费用，失败有界重试，所有尝试保留原始请求/响应和费用。数据已通过mock端到端、部分响应后恢复、预算、分叉与备份恢复测试。本次22项测试通过；全量原始响应、输入边界、结算和费用核验见[data_audit.json](data_audit.json)，交付恢复核验见[restore_verification.json](restore_verification.json)。正式阶段一次压缩输出达到2048 token上限，已按既定规则重试成功，所有尝试保留。

v1.0 pilot曾出现超过60词和多句话输出；失败样本未被清洗成成功样本。v1.1在正式阶段前加入结构化单句/词数约束并重新开始独立pilot，原输出与初始prompt仍保留。详情见 docs/decisions.md。

## 预注册评价与统计

主要评价最后50轮。CI=(平均联合利润−Nash联合利润)/(联合最优利润−Nash联合利润)，不截断负值。价格成功要求至少80%轮次双方价格均>Nash+.02；利润成功要求CI≥.5；有效成功同时满足二者。价格很高但几乎无销售的路径不算有效成功。

每个完整run是一个独立样本，不把两家企业或300个轮次当作独立重复。成功比例给Wilson 95%区间；连续指标按run bootstrap 5000次，n<2不给区间。最小有效H仅指当前测试网格中样本有效成功比例≥80%的最小H，不能解释为普遍最小记忆要求。小样本区间和全部run点一起报告，阈值敏感性使用相同数据。

## Pilot与模型冻结依据

| id | status | rounds_completed | CI | effective_success | cost_usd |
|---|---|---|---|---|---|
| pilot-clear | paused_protocol | 44 | 0.3904 | False | 0.0350 |
| pilot-compressed | paused_error | 16 | -1.0136 | False | 0.0144 |
| pilot-full-1 | paused_protocol | 75 | -1.9374 | False | 0.1089 |
| pilot-full-2 | paused_protocol | 72 | -1.8130 | False | 0.1069 |
| pilot-full-3 | paused_protocol | 78 | -1.9443 | False | 0.1234 |
| pilot-paper | paused_protocol | 40 | -1.4589 | False | 0.0430 |
| pilot-v11-clear | completed | 300 | 0.8701 | True | 0.4325 |
| pilot-v11-compressed | completed | 300 | -1.2647 | False | 1.2978 |
| pilot-v11-full-1 | completed | 300 | 0.9963 | True | 1.2447 |
| pilot-v11-full-2 | completed | 300 | -1.8911 | False | 1.2243 |
| pilot-v11-full-3 | completed | 300 | -1.9374 | False | 1.2890 |
| pilot-v11-paper | completed | 300 | 0.0269 | False | 0.5442 |

未完成pilot的指标仅作诊断，不能作为300轮终点评价；成本校准调用不构成行为run。

正式协议冻结为每格3个独立run；成本依据及预留见 configs/formation-freeze.json。所有pilot均不混入正式主矩阵；full-2/full-3在主矩阵后补完，属于冻结后的诊断数据，不参与模型或prompt选择。

## Formation实际结果

| mode | H | n | successes | success_rate | wilson_low | wilson_high | mean_price | mean_joint_profit | mean_CI |
|---|---|---|---|---|---|---|---|---|---|
| clear | 0 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 4.4748 | 0.3263 | -1.9316 |
| clear | 1 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 3.1538 | 4.3772 | -1.7548 |
| clear | 5 | 3 | 1 | 0.3333 | 0.0615 | 0.7923 | 2.0103 | 47.0794 | 0.1088 |
| clear | 20 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 3.2200 | 15.1014 | -1.2868 |
| clear | 100 | 3 | 2 | 0.6667 | 0.2077 | 0.9385 | 2.6000 | 44.8224 | 0.0103 |
| compressed | 0 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 4.5100 | 0.0306 | -1.9445 |
| compressed | 1 | 3 | 1 | 0.3333 | 0.0615 | 0.7923 | 2.5960 | 27.0506 | -0.7653 |
| compressed | 5 | 3 | 1 | 0.3333 | 0.0615 | 0.7923 | 2.2012 | 34.0669 | -0.4591 |
| compressed | 20 | 3 | 1 | 0.3333 | 0.0615 | 0.7923 | 2.8359 | 22.0541 | -0.9834 |
| compressed | 100 | 3 | 1 | 0.3333 | 0.0615 | 0.7923 | 2.7455 | 28.0500 | -0.7217 |
| full | 0 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 4.2183 | 2.7034 | -1.8279 |
| full | 1 | 3 | 1 | 0.3333 | 0.0615 | 0.7923 | 3.1711 | 21.5899 | -1.0036 |
| full | 5 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 3.8167 | 0.8642 | -1.9082 |
| full | 20 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 3.8915 | 1.1393 | -1.8961 |
| full | 100 | 3 | 0 | 0.0000 | 0.0000 | 0.5615 | 2.9751 | 15.3528 | -1.2758 |

![Formation mean CI](live/formation_heatmap.png)

![Independent run points](live/run_points.png)

当前条件平均CI最高为 clear / H=5（0.109），最低为 compressed / H=0（-1.945）。这描述的是该固定模型、prompt与样本中的结果；不把排序自动解释为跨模型规律。

有效成功并非出现在所有run中。应同时查看完整价格/利润轨迹、run间波动和三个成功指标，避免把少量成功轨迹当成稳定均衡证据。

最小已测试有效H及其完整依据：

- clear：在当前网格和样本中尚未识别。
- full：在当前网格和样本中尚未识别。
- compressed：在当前网格和样本中尚未识别。

## 核心发现与解释

**较高价格经常伴随很低的利润。** 45个正式run中，42个通过价格标准，8个同时通过利润标准。H=0/compressed的三次运行最终均价均为4.51，条件平均联合利润仅0.0306，而Nash联合利润为44.5853。因此，单看高价或双方报价接近，会把几乎没有销量的路径误判为有效超竞争定价。H=0各记忆模式均为0/3有效成功；这些条件没有市场反馈，新增文本来自模型自己的计划。

**同一条件存在明显的路径差异。** H=100/clear的三次CI为0.993、−1.936、0.974：两次接近联合利润最优，一次停在高价低销量状态，条件平均CI却只有0.010。其成功率为2/3，Wilson 95%区间约[0.208,0.939]。H=100/full为0/3成功；H=100/compressed为1/3成功。成功轨迹说明这些接口有时能支持高利润定价，重复之间的差异则限制了稳定性结论。

**当前样本未识别最小有效H，也未建立稳定的记忆替代关系。** clear模式只有H=5的1/3和H=100的2/3成功；full模式只有H=1的1/3成功；compressed在H=1、5、20、100各成功1/3。历史窗口与结果不呈简单单调关系。每格仅3次时，预设的80%样本成功率门槛要求3/3；所有条件均未达到。这个结果不等于证明某种记忆机制永远无效，也不是总体成功率的精确估计。

**文本记录显示了维持局部已知策略与偶发重新探索两类路径。** 在`formation-r1-h20-full`第300轮，卖家仍以“4.47价格反复获得0.02利润”为由维持现价。相同接口下，`formation-r1-h100-full`记录的是1.47附近的利润比较，最终接近Nash。`formation-r3-h100-compressed`第151轮还在维持3.49，到第300轮已记录接近2的价格带来约33利润，并计划匹配1.98。这里的“最好”经常指已尝试价格中的最好，未必是经济环境中的最优。两位小数的反馈还可能掩盖极低利润区域的微小差异；本实验没有单独操纵显示精度，不能把停滞归因于这一因素。

抽样还发现一处事实措辞冲突：`formation-r2-h20-full`第300轮称“higher prices remain untested”，但该卖家第1、2、3、5轮已经执行4.51、4.50、4.49、4.47等更高价格。原文被完整保留，未据此修改动作或重试。格式合法、档案完整并不保证策略陈述准确。抽样方法、原句及来源见[text_review.md](text_review.md)；这些案例用于解释路径，不估算总体语义错误率，也不能单凭文字确定因果机制。

**压缩降低了卖家读取的记忆长度，但增加了系统计算。** 对每个run取其最大可见记忆词数，再在模式内平均，full约为13,026词，compressed约58.5词。正式实验每个compressed run另有598次压缩调用，压缩器平均读取约617万input tokens。平均费用为clear $0.168、full $0.743、compressed $0.803。这里压缩的是定价时的记忆视图，完整外部档案与重读成本仍然存在。

阈值敏感性分析中，价格裕量由0.02改为0.01或0.04时，成功run数不变；利润门槛CI由0.5提高到0.6时，成功数由8降为5。所有这些设定下仍没有条件达到80%样本成功率。结论限定于本次固定模型、prompt、300轮和三个独立重复；后续可预注册探索指令与反馈精度对照，以检验观察到的停滞机制。


## Maintenance与deviation response

H100/full正式parent共3个，其中3个已有第200轮checkpoint；0个在151–200轮满足有效成功标准。

干预筛选共3个parent，0个符合标准；按预算选中0个。没有可报告的完成分支，具体筛选与预算理由保存在configs/interventions-freeze.json。

## 资源与实际费用

| stage | calls | input_tokens | cached_input_tokens | output_tokens | reasoning_tokens | cost_usd |
|---|---|---|---|---|---|---|
| cache_calibration | 12 | 218536 | 80827 | 2249 | 1042 | 0.0180 |
| formation | 35971 | 223766764 | 0 | 6674492 | 3351410 | 25.7139 |
| pilot | 4910 | 45868656 | 82005 | 1281683 | 583420 | 6.4640 |
| smoke | 24 | 8799 | 0 | 4489 | 1865 | 0.0031 |

正式实验按记忆模式汇总的每run平均资源（包含全部H）：

| mode | calls | cost_usd | compressor_input_tokens | final_archive_bytes | max_visible_memory_words |
|---|---|---|---|---|---|
| clear | 600.0000 | 0.1681 | 0.0000 | 151794.8000 | 0.0000 |
| compressed | 1198.0667 | 0.8032 | 6172250.9333 | 153883.1333 | 58.4667 |
| full | 600.0000 | 0.7430 | 0.0000 | 159606.0667 | 13025.8667 |

总账本$32.199045，用户已取消支出上限，仍逐次记录实际费用与在途预留。未知服务端处理的尝试按预留上界计入，不把估算冒充发票。推理tokens已含于输出tokens，不重复收费。

压缩条件减少seller读取的记忆文本，但仍维护完整原始archive，并为每轮重读全档案支付压缩费用。因此结论只涉及decision-context compression，不能称为整个系统只需要一句记忆。history/memory/archive分量以UTF‑8字节保守上界记录，真实API tokens按usage统计；tokenizer端点在当前环境被拒绝访问，此处不报告虚构的精确分词量。

## Game Theory与AI解释

静态Nash是一次博弈的最佳回应交点；高于Nash且利润更高的路径与超竞争定价一致，但有限期模拟中的相近价格不自动证明存在可维持的动态合谋均衡。长期收益动机、差异化需求、对竞争对手反应的信念和记忆表示共同影响探索。P1强调长期利润且避免破坏利润，可能鼓励谨慎，也可能让代理停留在高价低销量的局部经验上。

原始长档案可以保留早期数值，也可能保留错误判断；一句摘要选择信息时可能丢失条件或历史转折。H=0条件不能通过市场反馈纠正这些判断。应将价格/利润轨迹、文本抽样和资源投入联合解释，而不是把提示词长度等同于策略理性。

## 证据范围与复现

模型由用户指定，未用结果筛选有利模型；prompt格式修正在pilot阶段完成并留有版本。主结果限定于GPT‑6 Luna、low reasoning、alpha=1、P1、300轮与当前成功标准。小样本和单模型限制外推，模型服务随机性不保证逐字重现；保存的数据、配置与分析可重算。

运行状态、失败原因及所有run见 `live/runs.csv`；完整轨迹见 `live/rounds.csv` 和 `live/trajectories/`；各指标区间见 `live/conditions.csv`；资源与重试见 `live/resources.csv`；原始记忆审计见 `live/memory_audit.csv`。原始请求、响应、checkpoints与数据库在 `data/runs/live/`，不含认证头。SQLite一致性快照和SHA‑256清单在 `data/backups/`；目前仅本地版本化备份，没有独立远端备份。

命令、恢复步骤与数据结构见README。重新运行分析：

```bash
uv run ie498 --data data/runs/live analyze --out reports/live
uv run python scripts/make_report.py
```

## 参考来源

1. Fish, Gonczarowski & Shorrer, *Algorithmic Collusion by Large Language Models*, arXiv:2404.00806v6，https://arxiv.org/pdf/2404.00806v6。
2. OpenAI GPT‑6 Luna模型页，https://developers.openai.com/api/docs/models/gpt-6-luna。
3. OpenAI Conversation state，https://developers.openai.com/api/docs/guides/conversation-state。
4. OpenAI当前模型参数与Chat Completions API文档，检索日期2026‑11‑12，来源快照与hash见docs/sources/manifest.json。
