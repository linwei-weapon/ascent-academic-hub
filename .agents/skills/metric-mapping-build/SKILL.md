---
name: metric-mapping-build
description: 从业务需求、源库结构和分析库设计建立应用层业务指标映射，维护三层来源、SQL与明确问题，经指标核验服务保存版本并验证真实数据。用于新建或调整指标映射和106教学数据总览核验；不生成页面原型，不分析生产代码处理过程。
---

# 业务指标映射与核验

从本目录上溯三级定位仓库。读 `AGENTS.md` 与本次业务模块需求；契约和持久化边界见[指标核验模块说明§13](../../../文档/4-需求文档/4.9-系统管理/指标核验模块说明.md#13-指标映射skill与数据库接入规格)。统一执行入口是 `code/scripts/metric_mapping.py`，不使用旧生成器覆盖新业务定义。

## 输入和范围

填写[输入模板](../../../code/metric-verification/contracts/mapping-input.template.json)：模块、业务指标范围、需求/数据库文件、已有决定、环境配置引用、检查范围、交付方式。`template=false`，稳定 `analysisId`；更新必须使用服务取得的 `baseRevisionId`。连接和令牌只用已有配置或环境变量引用，不放入包、报告或聊天。

原型/系统界面可辅助辨认目标指标、取得同条件实值。只记录指标标签、值、单位、范围、业务时间、观察时间和真实/演示来源；不提取页面树或交互需求。仅有界面且缺口径时先登记候选与问题。

应用业务结果才建立指标；分子分母、筛选、字段和中间节点作为组成依赖。需求独立使用的分子/分母可以独立建指标。保留公式、对象或时间不同的业务变体，不能因名称相似合并。106以用户明确决定、106原文为先；TOP6≥0、核查状态按106、TOP1超额影响人数公式已经确认，不重复提问。

服务只允许 `teaching-overview`（教学数据总览）与 `ai-briefing`（AI简报）两个模块，项目和环境仍由服务固定。旧调用默认教学数据总览；包操作从包内 `moduleId` 读取，也可用 `--module` 指定，两者不一致时拒绝。远端 `resume` 须用 `--module ai-briefing` 才读取AI简报。HTTP请求使用同一 `moduleId` 查询参数，不修改全局 `MV_MAPPING_MODULE`；AI模块未登记时不回退106目录。

## 执行

1. **准备。** 运行 `prepare` 获取本轮指标、必要依赖和待复核影响；更新从数据库版本开始。首个106包见 `code/metric-verification/mappings/teaching-overview/package.json`，其登记状态不能作为本轮运行成功证据。
2. **分析。** 用[输出模板](../../../code/metric-verification/contracts/mapping-output.template.json)填写指标定义和原文片段；从应用结果逆查事实、源及字典，记录物理表字段、粒度、关联、筛选和去重。源Oracle与测试镜像方言分开；ACT是事实，AGG是聚合应用，SYS按职责区分定义/配置/结果。查不到写缺口，不猜字段或把事实复算称作应用实值。
3. **建立SQL与依赖。** 每条SQL明确用途、参数、实际物理依赖和结果字段；count固定返回 `matched_records`。各层有查询或不可查询理由，不机械凑齐九条SQL。真正共用规则用 `sharedRules`，跨指标结果用 `metricRefs`，明确参数对应。变更求引用闭包后复核有无漏登记关系；未受影响指标从基线保留，不重生成整个模块。
4. **处理问题。** 查证后仅对影响结果的问题使用[问题模板](../../../code/metric-verification/contracts/mapping-question.template.json)。一次优先1—3个；业务含义问产品经理，字段枚举问数据负责人。引用已确认决定；未答不推定同意。聊天答复作为 `pendingAnswers` 保留原话和来源，`publish` 先存草稿、同步真实 `answerId`，再由本Skill落实规则/SQL并提交新 `packageId`；不伪造服务答复或自动猜规则。
5. **验证。** `validate` 默认离线，检查引用、范围、SQL适配和受影响集合。获授权 `save_draft` 后才通过服务验证新SQL；`analyze_only`不能隐式写库。使用[核算模板](../../../code/metric-verification/contracts/mapping-validation-case.template.json)选择能完整取得的真实业务小范围，同时读取并留存原始输入、count和被测结果；服务隐藏被测结果，先根据输入独立核算、提交预期，再读取结果比较。合成例子只解释口径。
6. **交付。** `publish` 经现有身份保存、回读hash，按输入明确的模式保持草稿或生效。AI简报生效在同一保护事务登记 `sys_metric_definition` 与 `sys_metric_page_binding`，不会写学校业务表；现存其他入口的同编码不能自动覆盖。用 `/mapping/registrations/{revisionId}?moduleId=ai-briefing` 回读实际定义、SQL模板、版本、绑定及head，不能用客户端“已登记”代替。已答复需落实但尚未处理时继续本次分析，不把CLI的下一步提示当成完成。用 `resume` 读取服务最新版本和答复，基线改变先重新整合。核验模块承接真实实值、同条件比较和人的判断；缺实值就明确条件不足。

## 可执行命令

从仓库根使用项目Python环境；运行 `python code/scripts/metric_mapping.py --help` 检查实际参数。

```text
python code/scripts/metric_mapping.py prepare --input INPUT.json --package PACKAGE.json --output work/metric-mapping/work.json
python code/scripts/metric_mapping.py validate --package PACKAGE.json --report work/metric-mapping/validation.json
python code/scripts/metric_mapping.py validate --package CHANGED.json --base BASE.json --partial --output COMPLETE.json --report work/metric-mapping/validation.json
python code/scripts/metric_mapping.py publish --package PACKAGE.json --mode save_draft --profile PROFILE.json --receipt work/metric-mapping/receipt.json
python code/scripts/metric_mapping.py validate --package PACKAGE.json --live --revision-id REVISION_ID --profile PROFILE.json --execution-request REQUEST.json --report work/metric-mapping/capture.json
python code/scripts/metric_mapping.py validate --package PACKAGE.json --live --revision-id REVISION_ID --profile PROFILE.json --evidence-id EXECUTION_ID --expectation-file EXPECTATION.json --report work/metric-mapping/calculation.json
python code/scripts/metric_mapping.py resume --analysis-id ANALYSIS_ID --profile PROFILE.json --output work/metric-mapping/resume.json
python code/scripts/metric_mapping.py validate --module ai-briefing --package code/metric-verification/mappings/ai-briefing/package.json --report work/metric-mapping/ai-validation.json
python code/scripts/metric_mapping.py resume --module ai-briefing --analysis-id ai-briefing-c01 --profile PROFILE.json --output work/metric-mapping/ai-resume.json
```

服务profile只含 `baseUrl`、`tokenEnv`、`identityEnv`、可选 `timeoutSeconds`；默认变量为 `MV_MAPPING_SERVICE_URL`、`MV_MAPPING_TOKEN`、`MV_MAPPING_IDENTITY`。令牌值不写文件；服务只允许本机HTTP或远程HTTPS，拒绝重定向。发布不直接写数据库，不自动迁移或授予权限。

`--partial`从基线保留未修改对象；删除必须有明确退役理由。输入中 `scope.metricIds` 要覆盖本次已授权必要依赖；范围冲突先保留草稿，不能凭自动影响扩大授权。

取证REQUEST填写包内queryId、旧消费锚点requirementId/scenarioId、明确parameters、validationCaseId和limit。脚本只输出证据ID/count/状态；通过核验模块的本人证据入口读取完整输入，再独立核算。EXPECTATION含method、basisRef、derivation、rows、inputContentHash、resultKnownBeforeCalculation；提交后结果才揭示。原始学生记录留在鉴权服务中，不复制到共享包或报告。

AI简报的贴源／事实输入以无学生标识的课程×状态分组展示，`attempts`保留原始人次。count同时返回 `source_records`（原始成绩记录数）和 `matched_records`（核算分组记录数）；证据完整性比较分组count与分组明细，不把分组数量当原始成绩行数。源库未提供独立作废字段，SQL投影空值并保留真实STATE原值，不能据此证明没有作废。组织映射、首修二元状态、P为N子集及版本可比仍须当次真实证据。

## 证据和完成判断

- 历史业务批次不可稳定重取，真实核算必须保存当次必要输入与输出于核验专用记录。共享包和报告只保存服务证据引用/摘要，不保存学生明细。
- 输入count与明细不一致、截断、留存失败或缺字段时缩小合法业务范围或标条件不足，不宣称验证通过。采集事务结束后才等待人工，不长时间占用事务。
- 同时读取三层不证明ETL时点对齐；批次名相同不证明业务范围相同。说明样本支持的范围，不能用单学生核算证明全量正确。
- 比较独立应用实值与需求复算，记录相同业务范围/时点/单位/精度。演示原型只能做明确标注的原型关联检查，不能充当测试库应用验收。
- 保存后从服务重新读取输入与结果核对；以后复核使用留存证据，不依赖源业务表再次查询。
- 分别报告：分析已整理、映射完整程度、草稿/生效、SQL技术执行、独立计算验证、原型关联和业务核验。服务不可达交付待导入包；不得把离线校验、查询成功或原型显示一致合并为“全部完成”。

产物遵循[回执模板](../../../code/metric-verification/contracts/mapping-receipt.template.json)，剩余条件具体指到指标、数据层、问题与证据。维护原模块说明及指标确认书，不另建重复方案。
