# 91 AI决策Skill链路与决策简报实现记录

> 实现日期：2026-07-21
> 实现分支：`产品终稿`
> 范围：Skill协议层、首批4个Skill、信号合并与快照diff、模板简报引擎、建议追踪闭环、决策简报前端页面与菜单授权
> 结论：新链路端到端可用，与旧 `/api/admin/ai/experts` 并存；LLM增强、专题工作区、学校配置覆写界面为预留的后续阶段

## 1. 设计原则

- **数字唯一来源是代码**：所有数字、分级、排序、diff 由确定性 SQL/代码产出；`llm_enhanced` 仅为协议预留，规则模板引擎（`rule_template`）本身就是完整可用的最终产品，LLM 关闭或失败不影响简报可用性。
- **数据不变不制造任务**：简报按全量信号指纹缓存；指纹未变直接复用上次快照（`cache_hit=true`），保留原有变化标记。
- **信号是管理语义单元**：每个信号携带严重度、事实数字、责任-时点-动作建议、不处理代价、置信度、数据锚点与口径边界，前端只负责呈现，不再二次加工判断。

## 2. Skill协议（`decision-skill/1.0`）

`backend/skills/protocol.py` 定义：

- `DataRequirement`：部署体检声明；必需表缺失时 Skill 标记不可用而不是运行时报错，非必需表缺失时附降级说明。
- `Signal`：五要素结构（headline 事实陈述 / facts 关键数字 / action 责任-时点-动作-理由 / consequence 不处理代价 / evidence 表-条件-核验路由-时效），`signal_id` 确定性生成，同数据必同ID；`change`（new/upgraded/ongoing/resolved）由快照diff回填。
- `SkillResult`：信号列表 + 聚合数字 + 显式排除项 + 数据体检 + 生效配置版本 + 口径边界。
- 配置治理：产品默认配置 + 学校覆写合并生效；`validate_override` 按 `config_bounds` 白名单校验，不允许覆写公式与数据来源（保存端点留待后续阶段）。

## 3. 首批4个Skill

| Skill | 管理问题 | 简报权重 | 事实证据路由 |
|---|---|---|---|
| `graduation-gap` 毕业缺口核查 | 目标毕业届中，谁的毕业路真的被堵了？学校还有没有留出路？ | main | `/admin/curriculum?tab=graduation-readiness` |
| `course-quality` 课程质量趋势 | 哪些课程未通过是结构性的（值得立项复盘），哪些只是正常波动？ | main | `/admin/operation/course-quality` |
| `alert-priority` 预警优先级 | 数千条活动预警中，本周有限干预注意力先给哪几名学生？ | main | `/admin/alert` |
| `faculty-structure` 师资结构核查 | 哪些课程全部教学压在一名教师身上，形成排课保险缺口？ | topic | `/admin/operation/teacher-load` |

Skill 数量由数据可支撑的管理问题决定，经 `registry.py` 数据驱动注册。

## 4. 信号合并、快照diff与简报装配

- `merger.py`：按严重度排序取 TopN 优先事项；同一管理实体被 ≥2 个 Skill 命中时标记**跨专题热点**并互填 `related`；与上次快照摘要比对回填 `change` 标记并输出 `resolved_since_last`。
- `briefing.py`：模板引擎装配固定结构简报（topline/urgency/priority_items/skill_sections/watch_items/positive_developments/previous_followup/resolved_since_last）；`store.py` 落快照与信号摘要，指纹未变时缓存命中并把最新追踪状态现取嵌回（追踪不进指纹）。

## 5. 建议追踪闭环

一期为手动闭环：`open / in_progress / done / dismissed` 四状态，按用户授权范围（`scope_key`）隔离。追踪状态 × 信号是否仍存在组合出五种呈现：`recheck`（标完成但信号仍在，需复核，排最前）、`active`、`signal_gone`（待确认完成）、`closed`、`dismissed`。

## 6. API与权限

`/api/admin/ai/decision`（`ai_decision.py`，已挂载 `main.py`）：

| 端点 | 用途 |
|---|---|
| `GET /skills` | Skill清单：元数据 + 数据体检 + 生效配置版本 |
| `POST /skills/{id}/run` | 单独运行一个Skill（专题工作区数据源，前端尚未消费） |
| `GET /briefing?force=` | 决策简报；指纹命中返回缓存，`force=true` 强制重算 |
| `GET /tracking`、`PUT /tracking` | 建议追踪查询与手动闭环 |

全部端点校验统一权限上下文；学院身份只看到本学院范围信号。

## 7. 前端决策简报页

`views/admin/reports/decision/`：ToplineBar（总判断+紧急度+生成方式+快照指纹）→ 优先处置（带排名信号卡）→ 上次建议追踪（五状态表格+快捷操作）→ 专题信号分区（每Skill一个Tab，含聚合数字、显式排除项与口径边界）→ 观察项 / 积极变化（紧凑卡）→ 已消除清单。信号卡支持事实证据路由跳转、情境化追问跳转决策研判、追踪状态标记（完成/忽略可补备注）。

路由 `reports/decision`；菜单「决策简报」挂在 AI管理决策 分组首位（sort 200），授权 7 个管理角色（校领导/教务处/运行科/教研科/实践科/质量办/学院院长/教学秘书），与 管理要情 一致。`seed.py` 面向新装库，`code/scripts/migrate_decision_menu.py` 幂等迁移存量库（已执行）。

## 8. 验证记录

- 后端测试：`test_decision_skills.py` + `test_decision_briefing.py` 共 31 例；全套 96 例从 `code/` 目录运行全绿（注意：从 `code/backend/` 直接跑 pytest 会有 3 个存量模块因 `sys.path` 收集失败，非代码问题）。
- 前端：`npm run build` 通过；`vue-tsc` 下 decision 相关文件 0 错误（存量旧文件错误不在本次范围）。
- 真实库端到端：4 Skill 产出 24 条信号（10/5/2/7），二次生成指纹命中缓存，追踪写入后强制重算正确呈现 `recheck/active` 组合，验证数据已清理。

## 9. 后续阶段预留

1. `llm_enhanced` 叙事增强（协议与前端标记已预留，不改变任何数字）。
2. 专题工作区：消费 `GET /skills` 与 `POST /skills/{id}/run`，含数据体检展示与单专题运行。
3. 学校配置覆写保存端点与界面（`config_store` 版本管理、发布、回滚函数已就绪）。
