# 91 AI决策Skill链路与决策简报实现记录

> 实现日期：2026-07-21
> 实现分支：`产品终稿`
> 范围：Skill协议层、首批4个Skill、信号合并与快照diff、模板简报引擎、建议追踪闭环、决策简报前端页面与菜单授权、LLM编排层（阶段4：叙事增强+对话编排+稳定性防线）
> 结论：新链路端到端可用，与旧 `/api/admin/ai/experts` 并存；LLM 为可选增强层（默认关闭，关闭即完整规则版）；学校配置中心UI、黄金评估集为预留的后续阶段

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

## 7. 前端决策简报页（阶段3收口，2026-07-21）

**四种卡片**（`components/cards/`，统一五要素：判断→依据→动作→时限→代价）：结论卡（优先处置/积极变化）、风险卡（代价前置，观察项/滞留类）、方案卡（动作为主体，建议追踪）、证据卡（弹层：数据表/条件/时效/口径/关联信号，数字点击≤2次到核验路由）。

**简报首页**（`reports/decision/`）：ToplineBar → 优先处置（结论卡带排名）→ 上次建议追踪（方案卡）→ 专题分区 Tabs → 观察项（风险卡）/积极变化 → 已消除。

**专题工作区 ×4**（`reports/decision/skills/:skillId`，数据源 `POST /skills/{id}/run`）：
- 毕业缺口：顶部时限条（目标届+毕业审核时点）+ 待处理/待核验**双列强制分流**（overview 信号 context 携带前后50条名单与总数）
- 课程质量：基线与四态统计 + 课程卡（状态大标签 + 近4学期未通过率趋势缩略图 + 证据包：分数段/先修链）+ 向好清单
- 预警优先级：全景统计 + 本周优先介入队列（排名/等级/合成理由/评分/滞留标记）+ 滞留督办区
- 师资结构：判别矩阵（教师数×修读规模，高风险/中风险落点、小班明示排除、多人承担不检查）+ 课程清单 + 排除说明主体面板 + 职称数据完整性

**旧页面收口（决策点 D1/D4/D7）**：`ManagementBriefing.vue`、`DecisionSimulation.vue` 删除，路由重定向到决策简报；菜单仅保留「决策简报」（seed + `migrate_decision_menu_v2.py` 幂等迁移已执行）；`ai.ts` 旧专家/模拟/要情客户端函数移除（学生个体洞察接口保留）；后端旧专家接口暂保留未下线，归阶段6统一处置。后端两个 Skill 的 overview 信号补充工作区明细 context（不进信号指纹，不影响快照缓存）。

## 8. 验证记录

- 后端测试：`test_decision_skills.py` + `test_decision_briefing.py` 共 31 例；全套 95 例从 `code/` 目录运行全绿（`test_ai_expert_protocol.py` 中钉死旧 DecisionSimulation 页面的结构性用例随页面下线移除；从 `code/backend/` 直接跑 pytest 会有 3 个存量模块因 `sys.path` 收集失败，非代码问题）。
- 前端：`npm run build` 通过；`vue-tsc` 下 decision 相关文件 0 错误（存量旧文件错误不在本次范围）。
- 真实库端到端：4 Skill 产出 24 条信号（10/5/2/7），二次生成指纹命中缓存，追踪写入后强制重算正确呈现 `recheck/active` 组合；毕业缺口 context 返回 受阻144/待核验1852（各带前50名单），师资 context 返回 高风险10/中风险344（分界线300人）；`auth/me` 菜单中 AI管理决策 分组仅剩「决策简报」。

## 9. 阶段4：LLM编排层（2026-07-22）

在规则版之上叠加可选的 LLM 增强层。铁律不变：**数字唯一来源是确定性代码，LLM 只做叙事**。

### 9.1 配置与客户端（可切换、配置驱动，决策点 D2）

- `skills/llm_config.py`：配置存 legacy 库 `sys_ai_decision_llm_config`（与决策模块其他表同库，单键 `decision.llm`）。默认 `enabled=false`——关闭时系统就是完整的规则版产品。供应商统一抽象为 OpenAI Chat Completions 协议，国内模型API/私有化网关均可接入。
- `skills/llm_client.py`：httpx 同步客户端。错误分类 `not_configured / timeout / network / http / invalid_response`；仅超时/网络/5xx 重试且 **重试≤1次**；4xx 与解析失败不重试。所有失败抛 `LLMError`，由上层决定回退与标注。

### 9.2 简报叙事增强（数字校验拒绝→回退模板）

- `skills/narrative.py`：SystemPrompt 固化七级泛化光谱 L1-4（复述/组织/解释规则/关联引用信号ID）与禁区清单（不评价具体教师个人、不推断学生心理品行、不预测未来数据、不输出人事处分建议、不引用材料外数字）。
- **数字防线**：允许集 = 发给 LLM 的材料中出现的全部数字字面量（阿拉伯数字 + 紧邻量词的中文数字）。LLM 输出逐字段校验，出现允许集外数字 → 该字段回退模板版；topline 通过则 `generation_method=llm_enhanced`，否则保持 `rule_template`。
- 增强在快照落库前执行一次并随指纹缓存：同数据 → 同指纹 → 同叙事（同数据100%一致），缓存命中零 LLM 成本。
- 失败诚实标注（决策点 D3）：`llm_status` 字段（disabled/ok/failed:<kind>），前端 ToplineBar 按 `generation_method` 显示「LLM增强/规则生成」角标。旧快照缓存命中时补默认值向后兼容。

### 9.3 对话编排（POST /chat，SSE）

- `skills/chat.py`：**意图路由五类**（确定性规则，可单测）：
  - **查证**：不调 LLM，数字直接来自 Skill 信号，代码模板作答，零幻觉面；
  - **假设测算**：诚实声明能力边界（旧模拟页已按 D1 下线，测算 Skill 属后续阶段），引导到可查证基线；
  - **比较**：LLM 只组织已引用信号的事实，失败回退事实罗列；
  - **归因**：强制「事实层/假设层(待验证+验证路径)/行动层」三明治，假设层为 L5 条件性开放，未通过校验的假设整条丢弃并诚实说明；
  - **开放**：LLM 在材料边界内作答，失败回退简报事实摘要。
- 数字允许集 = 材料 + 对话历史（不引用对话中未出现过的数字）。
- **数字防线先于流式**：SSE 事件序为 `meta`（意图+引用信号，毫秒级先到）→ `delta`（LLM 文本先缓冲、校验通过才分片下发）→ `done`（结构块+追问建议+llm_status）。已读出的错误数字无法撤回，故不做真流式逐 token 下发。
- 追问建议（followups）随 done 返回，前端 chips 免输入（打字<30%）；卡片追问按钮带 signalId 锚定上下文。

### 9.4 前端接入

- `ChatDrawer.vue`：对话抽屉。消息流（用户/助手）、意图标签、引用信号迷你卡、三明治分层块（事实蓝/假设琥珀+待验证标/行动绿）、追问 chips、状态角标（LLM增强/数据直查/规则生成/规则生成·已回退）。LLM 未启用时开场明示「回答全部来自规则与数据直查」。
- 接入点：简报页头「决策追问」按钮；结论卡/风险卡「追问」按钮（带信号上下文与预置问题）；证据卡「可追问」直接发问。
- `GET /llm-status` 端点：前端据此前置提示生成口径，不暴露密钥。

### 9.5 验证记录（阶段4）

- 单测 35 例（`test_decision_llm.py`）：配置存取与非法键忽略、数字提取（千分位/百分号/中文量词）、叙事增强全路径（有效替换/编造数字拒绝/单字段丢弃/异常回退/非法JSON）、客户端错误分类与重试上限、五意图分类、信号匹配、五类回答器（含历史数字允许集）、SSE 端点（含 LLM 故障注入）。全套 **130 例** 从 `code/` 目录运行全绿。
- 端到端（`work/verify_stage4.py`，打真实服务 22 项）：LLM 默认关闭、简报规则生成、查证数字真实、三明治分层、测算能力边界、signalId 锚定、**故障注入**（不可达端点 → 简报与对话均回退且 `failed:*` 诚实标注）、恢复后回到 disabled。
- 前端 `npm run build` 通过。

### 9.6 后续阶段预留（里程碑B 剩余）

1. 学校配置中心 UI（系统管理内）：Skill 阈值/推荐问题 草稿→发布→回滚（`config_store` 已就绪），以及 `decision.llm` 配置的可视化编辑（目前仅库内配置）。
2. 黄金评估集（30-50条）与回归指标：信号命中率≥95%、Top1一致率≥90%、数字错误率=0；后端旧专家/模拟接口随评估收口统一下线。
3. 可选增强：真实 token 级流式（需配套在线增量数字校验）；归因假设层的多假设排序。
