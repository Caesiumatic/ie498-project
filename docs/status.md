# 最终状态

- 模型：所有真实卖家、压缩器均为GPT‑6 Luna，low reasoning。
- 正式实验：15个条件×3次独立重复×300轮，45个run、13500轮全部完成。
- 完整v1.1 pilot：6个（paper_reference、clear、compressed及3个full）；后补的full-2/full-3不混入正式样本。
- 正式结果：42/45通过价格标准，8/45同时通过利润标准；无条件达到80%样本成功率，未识别最小已测试有效H。
- Maintenance/shock：全部3个预定parent均未通过第151–200轮资格标准，实际分支为0；功能及离线测试完成，实证问题因缺少合格起点而未估计。
- 用户指定每格3次后，第4/5批共30个未开始计划被标记cancelled_user，API费用为0；所有历史记录保留。
- v1.0筛选：5个按协议暂停、1个压缩格式重试耗尽，原始响应和失败原因保留；未作为完成实证样本。
- 费用账本：$32.19904462；用户已取消预算上限；无在途请求。未知处理状态的保守计费为$0.103625。
- 验证：22项测试通过；全数据审计通过，覆盖40917次尝试、15634个已保存轮次；详见reports/data_audit.json。
- 交付：研究报告、条件与run级指标、轨迹、资源成本、原始请求/响应、SQLite快照、Git bundle。交付脚本在归档前核验完整恢复，回执见reports/restore_verification.json；归档内DELIVERY_MANIFEST.json列出逐文件校验；归档文件本身的hash另存于本地reports/delivery_manifest.json。
- 备份仅为本地版本化快照，没有独立远端备份。密钥不进入Git、报告或交付包。

主报告：[research_report.md](../reports/research_report.md)。复算与恢复命令见README。
