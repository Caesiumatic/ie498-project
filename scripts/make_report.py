"""Generate a Chinese research report strictly from saved data; no API access."""
import json
from pathlib import Path
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.storage import Store,budget_label
from ie498.analysis import analyze


def table(frame,columns):
    if frame.empty:return '无符合条件的数据。\n'
    lines=['| '+' | '.join(columns)+' |','|'+'|'.join(['---']*len(columns))+'|']
    for _,row in frame.iterrows():
        values=[]
        for col in columns:
            value=row[col]
            if pd.isna(value):value='—'
            elif isinstance(value,float):value=f'{value:.4f}'
            values.append(str(value))
        lines.append('| '+' | '.join(values)+' |')
    return '\n'.join(lines)+'\n'


def read_csv(path):
    try:return pd.read_csv(path)
    except pd.errors.EmptyDataError:return pd.DataFrame()


def main():
    store=Store(ROOT/'data/runs/live',readonly=True)
    out=ROOT/'reports/live';analyze(store,out)
    runs=read_csv(out/'runs.csv');costs=read_csv(out/'resources.csv');conditions=read_csv(out/'conditions.csv')
    merged=runs.merge(costs[['run','cost_usd','calls']],left_on='id',right_on='run',how='left')
    primary=merged[merged.eligible_primary]
    pilots=merged[merged.stage=='pilot']
    spending=store.spending()
    allowance='用户已取消支出上限，仍逐次记录实际费用与在途预留。' if spending['budget'] is None else f"尚有${spending['budget']-spending['spent']:.6f}预算空间（不代表账户余额）。"
    attempts=store.rows("SELECT status,COUNT(*) n,SUM(cost) cost FROM api_attempts GROUP BY status")
    uncertain=sum(r['cost'] for r in attempts if r['status']=='uncertain')
    successes=int(primary.effective_success.sum()) if len(primary) else 0
    text=f'''# IE498：战略记忆与重复双企业博弈中的超竞争定价

## 摘要

本项目在 logit 需求的重复 Bertrand 双企业博弈中，研究可见市场历史 H∈{{0,1,5,20,100}} 与 clear、full、compressed 战略记忆的影响。所有真实卖家和压缩器使用用户指定的 GPT‑6 Luna，low 推理设置。主实验独立单位为300轮的完整双企业run。

当前已完成 **{len(primary)} 个正式formation run**，其中 **{successes} 个**满足预先定义的有效超竞争标准。完成的pilot有 {sum(pilots.status=='completed')} 个；中断/失败pilot保留在独立记录中。费用账本共 **${spending['spent']:.6f}**，其中未知处理状态的保守计费 **${uncertain:.6f}**，预算状态为{budget_label(spending)}。下文仅依据已保存数据陈述结论。第4、5批的30个未开始计划按用户指令取消，未产生API费用。

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

'''
    text+=table(pilots,['id','status','rounds_completed','CI','effective_success','cost_usd'])
    text+='\n未完成pilot的指标仅作诊断，不能作为300轮终点评价；成本校准调用不构成行为run。\n'
    freeze=ROOT/'configs/formation-freeze.json'
    if freeze.exists():
        f=json.loads(freeze.read_text())
        text+=f"\n正式协议冻结为每格{f['repeats']}个独立run；成本依据及预留见 configs/formation-freeze.json。所有pilot均不混入正式主矩阵；full-2/full-3在主矩阵后补完，属于冻结后的诊断数据，不参与模型或prompt选择。\n"
    else:text+='\n正式重复数尚未冻结。\n'
    text+='\n## Formation实际结果\n\n'
    if len(conditions):
        text+=table(conditions,['mode','H','n','successes','success_rate','wilson_low','wilson_high','mean_price','mean_joint_profit','mean_CI'])
        text+='\n![Formation mean CI](live/formation_heatmap.png)\n\n![Independent run points](live/run_points.png)\n'
        best=conditions.loc[conditions.mean_CI.idxmax()];worst=conditions.loc[conditions.mean_CI.idxmin()]
        text+=f"\n当前条件平均CI最高为 {best['mode']} / H={int(best.H)}（{best.mean_CI:.3f}），最低为 {worst['mode']} / H={int(worst.H)}（{worst.mean_CI:.3f}）。这描述的是该固定模型、prompt与样本中的结果；不把排序自动解释为跨模型规律。\n"
        if successes==0:
            text+='\n所有已完成正式run均未同时通过价格与利润标准，因此当前网格中未识别最小已测试有效H；也没有依据宣称一句压缩记忆已替代长历史以维持有效超竞争定价。负结果仍可说明该模型和协议下的学习或探索局限。\n'
        elif successes<len(primary):
            text+='\n有效成功并非出现在所有run中。应同时查看完整价格/利润轨迹、run间波动和三个成功指标，避免把少量成功轨迹当成稳定均衡证据。\n'
    else:text+='没有可纳入主分析的完成formation run；不使用mock或短smoke替代实证结果。\n'
    text+='\n最小已测试有效H及其完整依据：\n\n'
    for row in json.loads((out/'minimum_tested_effective_H.json').read_text()):
        h=row['minimum_tested_effective_H'];e=row['evidence']
        if e:
            text+=f"- {row['mode']}：H={h}；{e['successes']}/{e['n']}成功，Wilson 95%区间[{e['wilson_low']:.3f}, {e['wilson_high']:.3f}]。\n"
        else:text+=f"- {row['mode']}：在当前网格和样本中尚未识别。\n"
    interpretation=ROOT/'reports/interpretation.md'
    if interpretation.exists():text+='\n'+interpretation.read_text()+'\n'
    text+='\n## Maintenance与deviation response\n\n'
    eligible=read_csv(out/'parent_eligibility.csv');paired=read_csv(out/'paired.csv')
    if len(eligible):text+=f"H100/full正式parent共{len(eligible)}个，其中{int(eligible.checkpoint_available.sum())}个已有第200轮checkpoint；{int(eligible.eligible.sum())}个在151–200轮满足有效成功标准。\n\n"
    if len(paired):
        text+=table(paired,['parent','child','stage','H','mode','eligible_parent','delta_CI','delta_joint_profit','effective_success'])
        text+='\n共享parent的分支按parent聚合。自然延续作为对照，执行冲击为一次拟定价×.9。响应指标从下一轮起测量；相对对照的动态差异包含后续独立模型采样噪声，不能单凭降价断言惩罚意图。\n'
        maintenance=paired[paired.stage=='maintenance']
        if len(maintenance):
            text+='\n维持时长以首次不满足标准的20轮滚动窗口结束位置计（相对分叉起点）；未出现则右删失：\n\n'
            text+=table(maintenance,['child','first_failed_20_round_window_end','survival_censored','followup_rounds'])
        shock=paired[paired.stage=='shock']
        if len(shock):
            text+='\n响应持续性使用与自然延续的价格差绝对值≥.02的后续轮数；恢复时间为首次连续5轮价格差<.02的起点：\n\n'
            text+=table(shock,['child','first_opponent_price_delta','response_rounds','recovery_time','zero_shock'])
        if (out/'shock_response.png').exists():text+='\n![Deviation response](live/shock_response.png)\n'
    else:
        intervention_plan=ROOT/'configs/interventions-freeze.json'
        if intervention_plan.exists():
            ip=json.loads(intervention_plan.read_text());n_eligible=sum(r['eligible'] for r in ip['candidates'])
            text+=f'干预筛选共{len(ip["candidates"])}个parent，{n_eligible}个符合标准；按预算选中{sum(r["selected"] for r in ip["candidates"])}个。没有可报告的完成分支，具体筛选与预算理由保存在configs/interventions-freeze.json。\n'
        else:text+='尚无完成并可配对的maintenance/shock数据；具体未执行原因见最终状态记录。\n'
    text+='\n## 资源与实际费用\n\n'
    bystage=costs.groupby('stage',as_index=False)[['calls','input_tokens','cached_input_tokens','output_tokens','reasoning_tokens','cost_usd']].sum()
    text+=table(bystage,list(bystage.columns))
    if len(primary):
        bymode=costs.merge(primary[['id','mode']],left_on='run',right_on='id').groupby('mode',as_index=False)[['calls','cost_usd','compressor_input_tokens','final_archive_bytes','max_visible_memory_words']].mean()
        text+='\n正式实验按记忆模式汇总的每run平均资源（包含全部H）：\n\n'
        text+=table(bymode,list(bymode.columns))
    text+=f'''\n总账本${spending['spent']:.6f}，{allowance}未知服务端处理的尝试按预留上界计入，不把估算冒充发票。推理tokens已含于输出tokens，不重复收费。

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
'''
    (ROOT/'reports/research_report.md').write_text(text)
    store.close()
    print(ROOT/'reports/research_report.md')


if __name__=='__main__':main()
