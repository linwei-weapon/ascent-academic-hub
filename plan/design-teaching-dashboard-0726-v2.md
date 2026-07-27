---
goal: 教学数据总览07.26修改详细设计与开发方案
version: 2.9
date_created: 2026-07-26
last_updated: 2026-07-27
owner: 产品终稿任务
status: 'Implemented'
tags: [design, feature, dashboard, teaching-analysis, drilldown]
---

# Introduction

![Status: Implemented](https://img.shields.io/badge/status-Implemented-green)

本方案将 `修改需求/07.26 教学数据总览修改说明.md` 转化为可确认、可开发、可测试的实施基线。

方案采用两级组织方式：

1. 先统筹设计跨学校、学院、专业复用的通用能力，避免相同历史下钻功能重复建设。
2. 再按“教学数据总览首页 → 学院详情 → 专业详情 → 课程详情 → 课程学生画像 → 学生证据及完整档案”列出每个具体修改点。

方案已于 2026-07-27 获得确认并进入实施阶段。实施过程不修改数据库结构或原始需求文档，任务完成情况按本文档检查表持续更新。

## 1. Requirements & Constraints

### 1.1 总体要求

- **REQ-001**: 本次所有修改、新增页面、弹窗、抽屉、表格和图表必须遵循 `docs/93-教学管理分析UE公共契约.md`，并继承现有系统的操作、视觉、配色、布局、权限、加载、空状态和返回规范。
- **REQ-002**: 方案必须同时提供“通用能力统筹设计”和“按页面/层级修改清单”，每项现有功能修改定位到当前文件、组件、函数或返回字段。
- **REQ-003**: 学校、学院、专业层级的同类历史指标下钻使用同一个前端组件、同一个后端接口契约和同一套指标定义，仅通过 scope 参数改变统计范围。
- **REQ-004**: 新增功能必须补齐需求未明示的标题、说明、查询条件、默认值、自动带入条件、数据字段、交互状态、返回行为、权限和异常处理。
- **REQ-005**: 表格中的学年和学期合并为一个“学年学期”字段，显示值直接复用系统原有学期选项（当前为 `2025-2026-2`），不拆成两个低信息量字段，也不另建格式规则。
- **REQ-006**: 历史指标弹窗覆盖有效成绩覆盖率、挂科学生率、学生平均 GPA、有效预警学生率、首次通过率、补考通过率、重修通过率、公共必修首次通过率。
- **REQ-007**: 学院详情重命名专业核查区域，重新设计年级本学期修读结果，并在现有专业列表中补齐各专业本学期修读结果。
- **REQ-008**: 专业详情支持在籍学生卡下钻、预警学生名单、三项历史指标下钻和年级全部课程查看。
- **REQ-009**: 课程详情调整未通过率口径和名称，新增平均 GPA，显示全部行政班，并修正课程学生画像入口。
- **REQ-010**: 课程学生画像作为教学数据总览证据链中的独立无菜单详情页，不激活学生成长与学业分析；增加课程成绩和课程 GP。
- **REQ-011**: 学生证据抽屉和完整学生档案统一将“当前 GPA”调整为按课程学分加权的“总 GPA”。
- **REQ-012**: 同一指标在后端计算、前端名称、Tooltip、弹窗、列表、导出、测试和指标口径确认书中保持一致。
- **REQ-013**: 缺失数据、零分母、不适用、无权限和接口失败必须分别表达，禁止把无数据渲染为健康的 0 或 0%。
- **REQ-014**: 所有查询、详情、证据、导出和直接 URL 必须在服务端按当前工作身份重新鉴权，AI 和前端路由不得扩大数据范围。
- **REQ-015**: 本次原则上不增加、删除或修改任何数据库表、字段、索引和约束；历史学籍只读访问既有学期源库，总 GPA 和其他新增值通过查询时计算，不提交真实数据库或敏感配置。
- **REQ-016**: 模块验收时同步更新教学数据总览实施文档、产品终稿检查表、验收清单和指标口径确认书。
- **REQ-017**: 方案中出现的每个查询条件、列表字段、统计字段和排序字段必须具有现有接口字段、现有数据库字段或明确可执行计算作为证据；无证据且非原始需求必需的字段从方案删除。

### 1.2 强制设计规范

- **GUD-001**: 页面结构按“标题与管理目标 → 工作身份/数据范围/统计周期 → 筛选 → 管理结论 → KPI → 趋势/比较 → 明细 → 口径与边界”排列。
- **GUD-002**: 视觉基线使用现有 Style A“靛蓝清爽”主题，不为本需求另建主题，不在页面内新增无语义的十六进制颜色。
- **GUD-003**: 页面标题使用 `.sa-page-title`，副标题使用 `.sa-page-sub`，内容卡使用 `.sa-card`，KPI 容器使用 `.sa-kpi-row`，表格使用 `DataTable.vue`。
- **GUD-004**: 颜色只使用现有语义变量：主操作/选中 `--sa-primary`，正向/达标 `--sa-teal`，待核验 `--sa-amber`，风险/未通过 `--sa-danger`，正文 `--sa-text`，次要信息 `--sa-muted`，不可用 `--sa-faint`。
- **GUD-005**: 卡片、弹窗、抽屉和图表的操作反馈必须符合现有交互：可下钻才显示指针、悬停和“查看趋势/查看名单”提示；不可下钻卡片无点击暗示。
- **GUD-006**: 查询条件不超过两个且查询成本低时允许选择后局部刷新；存在范围、起止学期等组合条件时采用“草稿条件 + 查询 + 重置”，只允许最后一次请求更新界面。
- **GUD-007**: 详情优先在弹窗或抽屉内打开，背景页面保留筛选、分页和滚动位置；最多两层抽屉，第二层提供返回上一级入口。
- **GUD-008**: 表格遵守对象识别列、业务列、操作列三区域规则，数字右对齐，默认业务列不超过 8 个，抽屉内默认业务列不超过 6 个，字段变化必须提升 `configVersion`。
- **GUD-009**: 图表必须显示标题、用途、周期、单位、图例、Tooltip、无数据说明和口径入口；图表颜色不随筛选数据自动改变语义。
- **GUD-010**: 首次加载 300ms 内显示骨架或明确反馈；条件刷新保留旧结果并显示局部更新状态；弹窗/抽屉失败在内部提供重试。
- **GUD-011**: 所有新增内容覆盖加载中、正常、无数据、部分数据、权限不足和接口失败六种状态。
- **GUD-012**: 新详情页进入后回到顶部，浏览器返回和页面内返回都恢复来源页筛选、分页、滚动和当前工作身份。
- **GUD-013**: 响应式布局沿用现有断点；宽度不足时优先隐藏低优先级列，不通过无限横向滚动挤压核心字段。
- **GUD-014**: 交互元素支持键盘聚焦和 Enter/Space 激活；弹窗关闭后焦点回到触发卡片，并尊重 `prefers-reduced-motion`。

### 1.3 安全与数据约束

- **SEC-001**: scopeType、scopeId、semester、courseId、studentId 等前端参数只表达用户意图，后端必须与当前权限集合取交集。
- **SEC-002**: 二级学院只能查看本学院历史明细；允许的跨学院比较仍只返回聚合，不得通过历史弹窗进入他院学生或预警名单。
- **SEC-003**: 辅导员、班主任和导师的历史统计、课程学生画像、名单、证据和导出都按有效人员关系限制。
- **CON-001**: 当前 `analytics.sqlite` 有 9 个学期成绩，但 `dim_student` 只有当前学籍；历史覆盖率等指标的准确分母必须按学期只读查询既有源库 `students` 名单，不能用当前学籍反推，也不新增历史表。
- **CON-002**: 当前 `fact_alert` 仅有 `2025-2026-2` 的有效预警数据，不能直接声称存在真实历年有效预警率。
- **CON-003**: `analytics_v2.sqlite` 的 `grade_attempt` 与 `agg_course_pass_stat` 可支持首次、补考、重修和公共必修通过率历史统计。
- **CON-004**: 普通页面不新增一级或二级菜单；课程学生画像是教学数据总览链路内的无菜单详情页。
- **CON-005**: 本轮不重构教学数据总览之外的学生成长与学业分析，只保证原有通用学生名单行为不受影响。
- **CON-006**: 当前 dashboard 的学生平均 GPA 使用 `AVG(g.gpa)`，而公共指标模块 `code/backend/api/academic_metrics.py` 已提供学分加权 GPA；本次历史趋势不能继续复制不一致算法，当前卡、历史弹窗和各层级比较必须同步统一到公共加权口径。
- **CON-007**: 实施范围禁止执行 `CREATE TABLE`、`ALTER TABLE`、`DROP TABLE`、新增列、删除列或修改 `schema.sql/schema_v2.sql`；若后续确认必须调整数据库结构，必须另立需求并再次获得用户确认。

### 1.4 分类总览

| 分类 | 层级/页面 | 主要修改 | 复用的通用能力 |
|---|---|---|---|
| 校级 | 教学数据总览首页 | 8 类历史指标下钻、优先核查 TOP1、课程画像入口 | 历史指标弹窗、可下钻 KPI、上下文继承 |
| 院级 | 学院详情 | 4 类历史指标下钻、专业区改名、年级矩阵、专业修读结果 | 历史指标弹窗、年级结果矩阵、DataTable |
| 专业级 | 专业详情 | 在籍学生下钻、预警名单、3 类历史指标下钻、更多课程 | 可下钻 KPI、历史指标弹窗、名单抽屉 |
| 课程级 | 课程详情 | 未通过率、平均 GPA、全部行政班、课程画像入口 | 统一指标口径、DataTable、上下文继承 |
| 课程—学生级 | 课程学生画像 | 独立路由语义、锁定课程条件、成绩和 GP | 课程上下文模式、学生名单组件 |
| 学生级 | 学生证据/完整档案 | 当前 GPA 改总 GPA | 统一累计 GPA 服务、证据返回链 |
| 数据访问层 | 既有分析库与学期源库 | 只读学期学生名单、现有成绩、现有预警可用性、查询时有效结果去重 | 只读适配器、内存聚合与缓存，不改变数据库结构 |

#### 1.4.1 查询字段与展示字段可用性审计

状态定义：

- `现有直接可用`：当前接口已返回，前端已使用。
- `现有数据可计算`：数据库字段和公共计算函数已存在，只需在目标接口中聚合或补充返回。
- `现有源库只读可用`：分析库没有字段，但既有学期源库可以只读获取，不需要改变数据库结构。
- `当前不可用`：所有既有库都没有可靠事实；页面必须披露边界，不新增数据库结构补造历史。
- `删除`：原方案自行扩展且没有现成业务依据，不进入开发。

| 场景 | 字段/条件 | 状态 | 代码或数据证据 | 方案处理 |
|---|---|---|---|---|
| 专业预警名单筛选 | 风险等级 | 现有直接可用 | `alert_monitor.py:RISK_LEVELS`、`GET /api/admin/alerts/options.levels`、`GET /students?level=` | 保留，沿用现有名称“风险等级” |
| 专业预警名单筛选 | 预警类型 | 现有直接可用 | `fact_alert.type`、`GET /api/admin/alerts/options.types`、`GET /students?type=` | 保留 |
| 专业预警名单筛选 | 核查状态 | 现有直接可用 | `alert_event.workflow_status` 经 `_student_cte()` 汇总为 `management_state`，接口参数为 `management` | 保留，名称改为现有“核查状态”，不称“处置状态” |
| 专业预警名单筛选 | 行政班、姓名/学号 | 现有直接可用 | `/students` 参数 `class_id`、`q`；`_base_sql()` 查询 `dim_student.class_id/name/student_id` | 保留 |
| 专业预警名单筛选 | 年级 | 删除 | `/students` 当前没有 grade 查询参数，原始需求未要求必须按年级筛选 | 从查询条件删除；年级仍可作为返回字段展示 |
| 专业预警名单列 | 学生、年级、行政班 | 现有直接可用 | `/students` 返回 `studentId/studentName/grade/className` | 保留 |
| 专业预警名单列 | 最高风险 | 现有直接可用 | `_student_cte()` 按 level 风险序取第一条，返回 `highestLevel` | 保留现有名称“最高风险” |
| 专业预警名单列 | 主要触发证据 | 现有直接可用 | 返回 `primaryType + primaryReason + primaryRuleId`；现有预警页已合并展示 | 保留，替代原方案“主要类型”单列 |
| 专业预警名单列 | 规则命中 | 现有直接可用 | `_student_cte()` 的 `alert_count`，返回 `alertCount` | 保留现有名称“规则命中”，不称“有效预警数” |
| 专业预警名单列 | 核查状态 | 现有直接可用 | 返回 `managementState/managementLabel` | 保留现有名称“核查状态” |
| 专业预警名单列 | 最近变化 | 现有直接可用 | `_student_cte()` 取 `MAX(COALESCE(updated_at,created_at))`，返回 `latestAt` | 作为可选列，名称使用现有“最近变化”，不称“最近识别时间” |
| 专业预警名单列 | 核查入口 | 现有直接可用 | 现有预警页调用 `showStudent(row)` 打开 `AlertStudentDrawer.vue` | 保留“核查”操作并复用现有抽屉，不另造“证据”字段 |
| 年级更多课程筛选 | 课程代码/名称关键词 | 现有数据可计算 | `dim_course.course_id/name`，专业详情课程查询已连接 `dim_course` | 保留，新增分页接口用同一字段过滤 |
| 年级更多课程筛选 | 课程性质 | 删除 | `dim_course.course_nature/is_required` 虽存在，但原 TOP3 接口和原始需求均未要求该筛选 | 本次不增加，避免扩大需求 |
| 年级更多课程筛选 | 风险等级 | 删除 | 当前课程行无风险等级字段或正式分级规则 | 删除 |
| 年级更多课程列 | 课程代码、课程名称 | 现有直接可用 | 当前返回 `id/name`，其中 id 即 `dim_course.course_id` | 保留 |
| 年级更多课程列 | 未通过人次、有效成绩人次、未通过人次率 | 现有直接可用 | 当前返回 `failCount/totalCount/failRate` | 保留并复用当前口径 |
| 年级更多课程列 | 较专业偏离 | 删除 | 当前无该字段，需求未要求 | 删除 |
| 年级更多课程列 | 风险等级 | 删除 | 当前无课程风险分级 | 删除 |
| 课程行政班列 | 行政班、有效成绩人次、平均分、未通过人次率、任课教师 | 现有直接可用 | `course_detail()` 返回 `className/students/avgScore/failRate/teacher` | 保留；把当前误导性的“人数”列改名“有效成绩人次” |
| 课程行政班列 | 行政班平均 GPA、未通过学生数、复合风险系数 | 删除 | 当前接口未返回，原始需求只要求显示全部并排序 | 删除；排序沿用现有未通过人次率 |
| 课程学生画像筛选 | 学院、专业、年级、行政班、姓名/学号 | 现有直接可用 | `students.py:student_list()` 已支持 `college/major/grade/class_id/keyword` | 按来源范围决定锁定或可筛选 |
| 课程学生画像筛选 | 预警状态 | 删除 | `student_list()` 不支持预警状态筛选，原始需求未提出 | 删除 |
| 课程学生画像列 | 学号、姓名、学院、专业、行政班、年级、筛选期 GPA、未通过数、预警 | 现有直接可用 | `student_list()` 当前返回字段和 `List.vue:studentCols` | 保留既有字段 |
| 课程学生画像列 | 课程成绩、课程成绩绩点(GP) | 现有数据可计算 | `fact_grade.score/gpa/course_id/semester_id/student_id` | 新增；按所选课程和学期取每生最新有效记录 |
| 课程学生画像列 | 考试类型 | 删除 | V2 有 `grade_attempt.attempt_type`，但当前课程名单使用旧分析库且原始需求未提出该列 | 本次不跨库新增 |
| 学生总 GPA | GPA、学分、有效课程结果 | 现有数据可计算 | `fact_grade.gpa/credits`、`academic_metrics.py:effective_course_outcomes_for_students()`、`weighted_gpa_expression()` | 基于现有公共函数扩展累计有效结果加权计算 |
| 历史在籍分母 | 学期、学生、学院、专业、年级、班级、状态 | 现有源库只读可用 | `config.TS_DIR/{semester}.db` 已存在；`extract_ts.py` 已逐学期读取 `students` 表及 `student_id/college/major/grade_year/class_name` | 新增只读数据访问函数，查询时聚合并做进程内缓存；不落新表 |
| 历史有效预警 | 学期有效状态 | 当前不可用 | 当前 `fact_alert` 仅有一个学期的完整快照，源学期库没有当时规则状态快照 | 旧学期显示不可用；只有经确认后才可按当前规则即时回算并标记“派生回算”，仍不落库 |

### 1.5 通用能力 A：历史指标下钻

#### 1.5.1 适用范围

一个组件和一套接口支持以下组合：

| 指标 ID | 指标名称 | 学校 | 学院 | 专业 | 图表类型 |
|---|---|:---:|:---:|:---:|---|
| `valid_result_coverage_rate` | 有效成绩覆盖率 | 是 | 是 | 是 | 人数堆叠柱 + 比率折线 |
| `current_fail_student_rate` | 挂科学生率 | 是 | 是 | 是 | 人数堆叠柱 + 比率折线 |
| `average_student_gpa` | 学生平均 GPA | 是 | 是 | 是 | GPA 折线 |
| `active_alert_student_rate` | 有效预警学生率 | 是 | 是 | 否 | 人数堆叠柱 + 比率折线 |
| `first_pass_rate` | 首次通过率 | 是 | 否 | 否 | 人次堆叠柱 + 比率折线 |
| `makeup_pass_rate` | 补考通过率 | 是 | 否 | 否 | 人次堆叠柱 + 比率折线 |
| `retake_pass_rate` | 重修通过率 | 是 | 否 | 否 | 人次堆叠柱 + 比率折线 |
| `public_required_first_pass_rate` | 公共必修首次通过率 | 是 | 否 | 否 | 人次堆叠柱 + 比率折线 |

统一计算口径：

| 指标 ID | 分子 | 分母/聚合方法 | 环比 |
|---|---|---|---|
| `valid_result_coverage_rate` | 当学期至少有一条有效成绩的去重学生数 | 当学期授权范围内有效在籍学生数 | 百分点差 |
| `current_fail_student_rate` | 当学期至少一门最终有效结果未通过的去重学生数 | 当学期至少有一条有效成绩的去重学生数 | 百分点差，下降为改善 |
| `average_student_gpa` | 使用 `academic_metrics.py:per_student_weighted_gpa()` 按 `Σ(GP×学分)÷Σ学分` 计算每名学生当学期 GPA | 对范围内有有效加权 GPA 的学生求算术平均，每名学生只贡献一次 | GPA 数值差 |
| `active_alert_student_rate` | 当学期处于有效预警状态的去重学生数 | 当学期授权范围内有效在籍学生数 | 百分点差，下降为改善 |
| `first_pass_rate` | 首次修读且结果明确的通过学生数 | 首次修读且结果明确的学生数 | 百分点差 |
| `makeup_pass_rate` | 结果明确的补考通过人次 | 结果明确的补考人次 | 百分点差 |
| `retake_pass_rate` | 结果明确的重修通过人次 | 结果明确的重修人次 | 百分点差 |
| `public_required_first_pass_rate` | 公共必修首次修读且结果明确的通过学生数 | 公共必修首次修读且结果明确的学生数 | 百分点差 |

学校、学院、专业的范围关联规则：

| scopeType | 当学期基础人群 | 成绩分子关联 | 预警分子关联 |
|---|---|---|---|
| `school` | 历史学期只读打开 `TS_DIR/{semester}.db` 的 `students` 表，与当前身份授权学生 ID 取交集；当前统计学期使用总览卡片同一 `dim_student` 授权名单 | 使用所得 student_id 集合限定同学期 `fact_grade` | 仅当前 `fact_alert` 有可用学期；旧学期返回不可用 |
| `college` | 历史学期将源库 `students.college` 映射现有 `dim_college.name/id` 后限定 scopeId，再与授权学生 ID 取交集；当前统计学期使用总览卡片同一学院名单 | 只统计该学院当学期名单学生的成绩；历史学期不使用学生当前学院反推历史学院 | 仅当前学期可计算该学院有效预警 |
| `major` | 历史学期将源库 `students.major` 映射现有 `dim_major.name/id` 后限定 scopeId，再与授权学生 ID 取交集；当前统计学期使用总览卡片同一专业名单 | 只统计该专业当学期名单学生的成绩；历史学期不使用学生当前专业反推历史专业 | 本期不提供专业历史预警率弹窗 |

各层级只改变基础人群，不改变指标公式。覆盖率分母在历史学期使用源学期库同层级学生名单，当前统计学期使用当前总览卡片同一名单；挂科学生率分母使用同层级当学期有有效成绩的学生；平均 GPA 只对同层级当学期有加权 GPA 的学生求平均。历史源库文件缺失、`students` 表缺失或组织名称无法映射时，该历史学期返回不可用原因，不回退使用当前 `dim_student`。

学院、专业不复制计算函数，只传入：

```text
metricId
scopeType = school | college | major
scopeId = 空 | college_id | major_id
scopeName
currentSemester
activeIdentityId
```

后端使用同一指标注册表，根据 scope 生成授权学生集合并聚合。

#### 1.5.2 展现形式

- 组件：新增 `code/frontend/src/components/MetricHistoryDialog.vue`。
- 形式：`el-dialog`，不是独立路由页面，不改变侧栏菜单。
- 宽度：桌面端 `min(1080px, 88vw)`，最大高度 `82vh`；窄屏使用 `94vw`。
- 布局：标题和范围摘要 → 查询区 → 趋势图 → 明细表 → 口径与边界折叠区。
- 背景页：保持原筛选、分页、滚动、图表和 KPI，不因打开弹窗重新加载。

#### 1.5.3 标题规范

- 主标题：`{统计范围名称} · {指标名称}历年趋势`。
- 学校示例：`全校 · 有效成绩覆盖率历年趋势`。
- 学院示例：`人工智能学院 · 有效成绩覆盖率历年趋势`。
- 专业示例：`计算机科学与技术 · 学生平均GPA历年趋势`。
- 副标题：`统计范围：{范围} ｜ 数据周期：{起始学期—结束学期} ｜ 数据来源：{真实/派生/回算} ｜ 更新时间：{时间}`。
- 指标卡中的当前学期只作为打开弹窗时的结束学期，不改变历史指标定义。

#### 1.5.4 查询条件

| 条件 | 类型 | 默认值 | 是否可改 | 规则 |
|---|---|---|---|---|
| 统计范围 | 只读标签 | 从来源页面带入 | 否 | 防止弹窗内切换范围绕开来源语义 |
| 起始学期 | 学期选择器 | 当前可用最早标准学期 | 是 | 只能选择已接入且不晚于结束学期的学期 |
| 结束学期 | 学期选择器 | 来源页面当前学期 | 是 | 不得晚于当前数据批次 |
| 指标 | 隐藏固定参数 | 触发卡片 metricId | 否 | 不在一个弹窗中切换指标，避免标题和口径混乱 |

起止学期属于组合条件，使用“查询”和“重置”按钮。选择条件不立即请求，条件变更后显示“筛选条件尚未应用”。

#### 1.5.5 自动带入与返回

- 自动带入当前工作身份、授权范围、来源页面学期、scopeType、scopeId、scopeName 和 metricId。
- 不允许从 URL 或浏览器控制台传入更大范围；后端再次鉴权。
- 弹窗不修改来源页 URL，不需要面包屑。
- 关闭弹窗恢复焦点到触发 KPI；重新打开同一指标可复用当前身份和条件下的缓存。
- 切换工作身份、来源页学期或组织范围后清除旧缓存并关闭不再合法的弹窗。

#### 1.5.6 明细表

比率类默认列：

| 顺序 | 字段 | 说明 |
|---:|---|---|
| 1 | 学年学期 | 复用系统原有学期选项显示，例如 `2025-2026-2` |
| 2 | 指标值 | 百分比，保留 1 位小数 |
| 3 | 较上学期 | 只显示带正负号的数值，不追加“个百分点”；无数据或无计算结果显示“-” |
| 4 | 分子 | 按指标显示“覆盖人数/挂科人数/预警人数/通过人次” |
| 5 | 分母 | 按指标显示“在籍人数/有效成绩人数/考试人次” |

GPA 类默认列：

| 顺序 | 字段 | 说明 |
|---:|---|---|
| 1 | 学年学期 | 合并显示 |
| 2 | 学生平均 GPA | 保留 2 位小数 |
| 3 | 较上学期 | GPA 数值差 |
| 4 | 有 GPA 学生数 | 统计基数 |

表格使用 `DataTable`，学年学期和指标值为必选列，不显示“数据状态”列；表格与图表均复用系统学期选项的“最新在前”顺序。弹窗使用“‘-’：表示学年学期对应内容无数据或无计算结果”的统一说明，表格空值和图表悬浮空值均显示“-”。

#### 1.5.7 图表规范

- 比率图：单学期只有一个柱位；指标色实心柱段表示分子，覆盖整柱总高度的透明虚线边框表示完整分母，比率折线使用右轴。
- 覆盖率/通过率：分子实心柱和比率折线沿用对应指标色，完整分母使用中性虚线边框，不用灰色填充表达差额。
- 挂科率/预警率：分子实心柱和比率折线沿用风险指标色，完整分母使用中性虚线边框，不用灰色填充表达差额。
- GPA：只显示 `--sa-primary` 折线和数据点，不添加无对应量纲的人数柱。
- 比率图自定义图例依次表示“实心分子、虚线框完整分母（柱总高）、折线比率”；Tooltip 只显示学年学期、分子、完整分母和比率，不显示内部差额。
- 分母为 0、对应学期真实数据缺失或不可比时不画 0 点，显示断点和“暂无可比数据”。

#### 1.5.8 接口契约

建议接口：

```http
GET /api/admin/dashboard/metric-history
  ?metric_id=valid_result_coverage_rate
  &scope_type=college
  &scope_id=COLLEGE_ID
  &start_semester=2021-2022-2
  &end_semester=2025-2026-2
```

统一响应：

```json
{
  "metric": {
    "id": "valid_result_coverage_rate",
    "name": "有效成绩覆盖率",
    "unit": "%",
    "formula": "有有效成绩学生数÷当学期在籍学生数",
    "purpose": "判断当前成绩数据是否足以支持正式分析"
  },
  "scope": {
    "type": "college",
    "id": "COLLEGE_ID",
    "name": "学院名称",
    "restricted": false
  },
  "periods": [
    {
      "semesterId": "2025-2026-2",
      "semesterLabel": "2025-2026学年 第2学期",
      "value": 96.8,
      "delta": 1.2,
      "numerator": 1240,
      "denominator": 1281,
      "sampleCount": 1240,
      "sourceType": "real",
      "comparable": true,
      "unavailableReason": null
    }
  ],
  "evidence": {
    "dataAsOf": "2026-07-27",
    "sourceTables": [],
    "ruleVersion": "dashboard-history-v1",
    "limitation": ""
  }
}
```

### 1.6 通用能力 B：可下钻 KPI

- 扩展 `KpiCard.vue` 的可选属性：`interactive`、`actionText`、`selected`、`disabledReason`。
- 新增事件：`drilldown`；支持 click、Enter、Space。
- 可下钻卡右下显示“查看历年趋势”“查看学生名单”或“查看预警名单”，不使用含义模糊的“查看”。
- hover/聚焦边框使用 `--sa-primary`，风险卡仍保留风险色，不用高饱和背景填满整卡。
- 该能力默认关闭，未修改页面的 KPI 外观和事件保持不变。

### 1.7 通用能力 C：层级上下文继承

所有下钻统一使用以下上下文：

```text
semester
collegeId / collegeName
majorId / majorName
grade
courseId / courseName
returnTo / returnLabel
page / pageSize / scrollY
```

规则：

1. 下一级自动继承上一级已应用条件，不继承未应用的草稿条件。
2. 页面标题、范围条、接口参数和返回链接使用同一个上下文对象。
3. URL 只保存业务上下文，不保存工作身份授权结果；授权结果由登录态解析。
4. 用户清除某一层级条件时同时清除其下游条件，例如清除学院必须清除专业。
5. 课程学生画像锁定 courseId 和 semester，不允许把课程条件清空后变为全校学生名单。

### 1.8 通用能力 D：名单/明细抽屉

专业预警名单和年级全部课程不是同一业务组件，但遵循同一结构：

- 标题：`{范围名称} · {对象名单名称}`。
- 副标题：范围、学期、匹配数量、数据来源。
- 查询区：关键词和不超过 5 个业务筛选；超过 2 个条件时使用“查询/重置”。
- 内容区：`DataTable` + 服务端分页。
- 操作列：使用“证据”或“详情”。
- 关闭：恢复来源页展开年级、滚动和筛选。
- 空状态：说明是无匹配、未接入、无权限还是统计条件不足。

### 1.9 通用能力 E：总 GPA

统一后端函数输出：

```text
cumulativeGpa
weightedPointsSum
includedCredits
includedCourseCount
excludedRecordCount
formulaVersion
limitation
```

公式：

```text
总 GPA = Σ（最终有效课程 GP × 计入 GPA 的课程学分）
         ÷ Σ（计入 GPA 的课程学分）
```

同一课程存在首次、补考、重修时只计一次最终有效结果。零学分、GP 为空和明确不计 GPA 的课程排除。学生学期 GPA 趋势继续保留，但不得再把最新学期 GPA 标成总 GPA。

实现基于现有 `academic_metrics.py:effective_course_outcomes_for_students()` 返回的每生每课最新有效 `latestGpa/latestCredits`，不重新发明有效结果排序。实施时补充 `source='real'` 限制并新增累计加权封装；`per_student_weighted_gpa()` 继续用于单学期/筛选期 GPA，但总 GPA 必须先按学生—课程去重后再加权。

### 1.10 按页面/层级的具体修改清单

#### 1.10.1 教学数据总览首页（校级）

| 编号 | 类型 | 现有修改点 | 目标设计 | 统筹能力 | 具体文件 |
|---|---|---|---|---|---|
| HOME-01 | 新增功能 | `index.vue` 的有效成绩覆盖率、当前挂科学生率、学生平均 GPA、当前有效预警学生率卡片 | 点击分别打开学校范围历史指标弹窗；当前学期作为结束学期 | 通用能力 A、B | `code/frontend/src/views/admin/dashboard/index.vue`、`dashboard.py` |
| HOME-02 | 新增功能 | `index.vue` 的首次、补考、重修、公共必修首次通过率为静态摘要 | 四卡复用同一历史弹窗；统计范围锁定当前授权范围 | 通用能力 A、B | `index.vue`、`dashboard.py` |
| HOME-03 | 现有功能修改 | `dashboard.py` 的 `managementFocus` 可能返回学院、课程各一项，前端最多显示 2 项 | 按确认口径只显示全局 TOP1，或文案明确“各类 TOP1” | 指标排序契约 | `dashboard.py:dashboard()`、`index.vue` |
| HOME-04 | 现有功能修改 | 优先核查课程 → 课程详情 → `/admin/students/list`，菜单激活学生成长 | 改为课程学生画像专属路由，保持教学数据总览菜单激活 | 通用能力 C | `CourseDetail.vue:goStudents()`、`router/index.ts`、`menu.ts` |

首页布局不新增整行大卡。历史能力通过现有 KPI 的明确下钻提示进入，避免首屏继续增高。

#### 1.10.2 学院详情（院级）

| 编号 | 类型 | 现有修改点 | 目标设计 | 统筹能力 | 具体文件 |
|---|---|---|---|---|---|
| COL-01 | 新增功能 | `Detail.vue` 四张 KPI 为静态卡 | 学院范围历史下钻，scopeId 固定当前学院 | 通用能力 A、B | `Detail.vue`、`dashboard.py:college_detail()` |
| COL-02 | 现有功能修改 | 标题“专业偏离与优先核查”，列“较学院” | 改为“本学院的所有专业偏离与核查”“较学院挂科率偏离值（百分点）” | 文案与指标契约 | `Detail.vue:majorCols` |
| COL-03 | 现有功能增强 | 年级图只在 Tooltip 中显示有效人数、GPA、挂科率 | 改为四指标年级对比矩阵，学分通过率用堆叠条，其余三项固定显示 | GUD-004、GUD-009 | `Detail.vue:gradeOption`、`dashboard.py:gradeCompare` |
| COL-04 | 现有功能增强 | 专业表已有人数、覆盖率、GPA、挂科率、预警率，缺学分通过率 | 在同一表增加“本学期课程学分通过占比”，不新增重复专业模块 | DataTable 契约 | `Detail.vue:majorCols`、`dashboard.py:majors` |

年级矩阵排列：

```text
年级 | 学分通过/未通过堆叠条 | 有效成绩人数 | 平均GPA | 挂科学生率
```

默认按入学年级倒序；风险项用红/橙文字和图标提示，不打乱固定年级位置。

学院页计算范围统一为“当前学院 + 当前工作身份授权学生 + 所选学期”：

- 年级/专业有效成绩人数：范围内当学期 `fact_grade.is_pass IS NOT NULL` 的去重学生数。
- 年级/专业课程学分通过占比：范围内当学期通过记录学分合计 ÷ 有通过判定记录学分合计；不等同培养方案完成度。
- 年级/专业学生平均 GPA：先用 `per_student_weighted_gpa()` 计算每名学生当学期学分加权 GPA，再对有 GPA 学生求算术平均。
- 年级/专业挂科学生率：当学期至少一门未通过的去重学生数 ÷ 当学期有有效成绩的去重学生数。
- 专业较学院挂科率偏离值：专业挂科学生率减学院同口径挂科学生率，单位为百分点；学院均值必须按全院分子合计÷全院分母合计，不对专业百分比做简单平均。

#### 1.10.3 专业详情（专业级）

| 编号 | 类型 | 现有修改点 | 目标设计 | 统筹能力 | 具体文件 |
|---|---|---|---|---|---|
| MAJ-01 | 现有功能修改 | KPI 标签为“范围内学生/在校生”，不可点击 | 统一为“在籍学生”；副文案说明授权范围；点击等同现有“查看本专业全部学生” | 通用能力 B、C | `MajorDetail.vue`、`dashboard.py:major_detail()` |
| MAJ-02 | 新增功能 | 预警学生只有人数 | 点击打开专业预警学生名单弹窗 | 通用能力 B、D | 新增 `MajorAlertStudentsDialog.vue`，扩展 `alert_monitor.py` |
| MAJ-03 | 新增功能 | 覆盖率、挂科率、平均 GPA 为静态 KPI | 专业范围历史下钻 | 通用能力 A、B | `MajorDetail.vue`、`dashboard.py` |
| MAJ-04 | 新增功能 | 每个年级只返回并显示 TOP3 课程 | 保留 TOP3 摘要，增加“更多课程（N）”抽屉查看全部 | 通用能力 D | `MajorDetail.vue`、`dashboard.py` |

专业页当前值和历史值使用同一范围：

- 基础人群为当前专业下、当前工作身份可查看的学生；历史弹窗按对应学期源库 `students` 的专业名单替换当前专业名单，并与当前身份授权学生 ID 取交集。
- 覆盖率、挂科学生率、学生平均 GPA 的分子分母与 1.5 节一致，只把 scopeType 固定为 `major`。
- 专业年级课程统计继续限定专业、年级、学期和授权范围，不能只按 courseId 查询全校。

专业预警名单：

- 标题：`{专业名称} · 当前有效预警学生名单`。
- 自动带入：学院、专业和当前身份；专业不可修改。
- 统计周期直接读取预警接口 `meta.currentSemester`/当前规则快照，不把专业详情选择的历史成绩学期传给预警接口，因为现有 `/api/admin/alerts/students` 没有 semester 参数，当前预警本身是当前时点口径。
- 查询条件：关键词（姓名/学号）、行政班、风险等级、预警类型、核查状态。五项均由现有 `/api/admin/alerts/students` 和 `/api/admin/alerts/options` 支持；不增加当前接口没有的年级筛选。
- 默认列：学生（姓名+学号）、年级、行政班、最高风险、主要触发证据、规则命中、核查状态、核查。
- 可选列：最近变化。该字段直接使用现有 `latestAt`；默认隐藏以遵守抽屉表格列数上限。
- 学院和专业已固定在标题/范围条中，不重复占用表格列。
- “核查”复用现有 `AlertStudentDrawer.vue`，不新建另一套学生预警证据模型；关闭后恢复名单页码和筛选。
- 字段语义直接沿用现有预警监控：“规则命中”是当前有效预警记录数，“核查状态”是多条预警事件汇总后的管理状态，“最近变化”是事件更新时间或预警生成时间的最大值。

年级更多课程：

- 标题：`{专业名称} · {年级}全部课程修读结果`。
- 自动带入：专业、年级、学期和身份。
- 查询条件：课程代码/名称关键词。当前业务目标只是从 TOP3 查看全部课程，不增加课程性质和风险等级筛选。
- 默认列：课程代码、课程名称、未通过人次、有效成绩人次、未通过人次率、详情。
- 数据范围：当前专业、年级、学期、角色权限范围内所有具有有效成绩的课程；不再保留当前 TOP3 查询中的 `fc>0 AND total>=8` 限制，因此零未通过课程也能查看。
- 默认排序：未通过人次率降序，同率按有效成绩人次降序，再按课程名称；服务端分页，不在初始专业页面预载全部课程。
- 不规划“风险等级、较专业偏离、课程性质”等原需求未提出且当前课程摘要未提供的字段。

#### 1.10.4 课程详情（课程级）

| 编号 | 类型 | 现有修改点 | 目标设计 | 具体文件 |
|---|---|---|---|---|
| COURSE-01 | 现有功能修改 | KPI 为“首次未通过率” | 按确认口径改为“未通过率”或“首次考试未通过率”，同步公式和提示，不只改文案 | `dashboard.py:course_detail()`、`CourseDetail.vue` |
| COURSE-02 | 新增功能 | 平均分后无平均 GPA | 新增平均 GPA 卡，使用当前课程、学期和来源范围内最终有效课程 GP 的算术平均 | `dashboard.py:course_detail()`、`CourseDetail.vue` |
| COURSE-03 | 现有功能修改 | 主表只显示高风险行政班 TOP10，抽屉显示全部 | 主区标题改“全部行政班”，显示当前接口已经返回的全部授权行政班 | `CourseDetail.vue`、`dashboard.py:classDetail` |
| COURSE-04 | 现有功能修改 | 需求写“按风险系数”，但当前系统没有独立风险系数，实际按未通过人次率排序 | 不新增复合指标；明确改为“按未通过人次率降序，同率按有效成绩人次降序” | `dashboard.py`、`CourseDetail.vue` |
| COURSE-05 | 现有功能修改 | “查看全部修读学生”进入通用学生名单 | 进入 `/admin/course/:id/students`，自动带入课程、学期、学院、专业、年级和返回路径 | `CourseDetail.vue:goStudents()`、`router/index.ts` |

课程页筛选和范围：

- 页面已有学期及来源学院/专业/年级上下文时继续锁定，不在课程详情中悄悄扩大到全校。
- 课程“未通过率”和“平均 GPA”先按 student_id+course_id+semester_id 从 `fact_grade` 取最后一条真实有效记录；未通过率为其中 `is_pass=0` 的去重学生数÷具有最终有效结果的去重学生数，平均 GPA 为其中 GPA 非空学生的课程 GP 算术平均。
- “全部行政班”表示当前课程分析范围内的全部行政班，不等同教学班。
- 默认列：排序、行政班、有效成绩人次、平均分、未通过人次率、任课教师。
- 当前 `classDetail.students` 实际来自 `COUNT(*)`，表示有效成绩人次，不改造成未经需求确认的去重学生数。
- 行政班数量来自单门课程和单学期，先沿用现有接口一次返回并由 `DataTable` 分页；实测超过性能阈值后才改服务端分页。不再保留内容重复的“全部行政班”抽屉。

#### 1.10.5 课程-学生学业画像（课程—学生级）

| 编号 | 类型 | 现有修改点 | 目标设计 | 具体文件 |
|---|---|---|---|---|
| CSP-01 | 新增无菜单详情页 | 当前复用 `/admin/students/list` 并激活学生成长 | 新增 `/admin/course/:id/students`，页面标题“课程-学生学业画像”，菜单保持教学数据总览 | `router/index.ts`、`menu.ts`、`students/List.vue` |
| CSP-02 | 现有功能增强 | 通用学生列表允许清空课程语境 | 课程画像模式锁定课程和学期，学院/专业/年级显示为已应用范围 | `students/List.vue` |
| CSP-03 | 新增字段 | 学生表无课程成绩、课程 GP | 在筛选期 GPA 前增加“课程成绩”和“课程成绩绩点(GP)”，仅课程画像模式显示 | `students.py:student_list()`、`students/List.vue:studentCols` |
| CSP-04 | 现有功能修改 | 标题按查询条件拼成“学生学业画像” | 标题区显示课程名、课程代码、学期、来源范围和匹配学生数 | `students/List.vue:pageTitle` |

页面标题：

```text
课程-学生学业画像
{课程名称}（{课程代码}） · {学年学期} · {学院/专业/年级或全校授权范围}
```

查询条件：

- 只读锁定：课程、学期。
- 可查询：关键词（学号/姓名）、学院、专业、年级、行政班；这些条件均为 `student_list()` 已有参数。
- 不新增当前 `student_list()` 不支持且原始需求未提出的预警状态筛选。
- 从学院/专业/年级进入时相应组织条件自动带入并锁定，避免从专业课程详情进入后扩大为全校课程；从全校课程详情进入时组织条件可用于继续缩小范围。
- 3 个以上条件使用“查询/重置”；重置恢复到来源页自动带入值，不清空课程和学期。

默认列顺序：

```text
学号、姓名、学院、专业、行政班、年级、
课程成绩、课程成绩绩点(GP)、筛选期GPA、当前预警、操作
```

`筛选期未通过门数`和`管理关注`作为现有可选列默认隐藏。来源上下文已经锁定学院、专业或年级时，对应组织列默认隐藏但仍可在列设置中打开。学号、姓名、课程成绩、课程成绩绩点(GP)、操作为必选列，默认可见业务列最多 8 个。

课程成绩与课程 GP 取数：

1. 只查询当前 courseId、semester 和已授权学生。
2. 数据字段直接使用 `fact_grade.score` 与 `fact_grade.gpa`。
3. 仅保留 `source='real' AND is_pass IS NOT NULL` 的有效记录。
4. 同一学生、课程、学期存在多条有效记录时，按 `grade_id/rowid` 倒序取最后一条，与现有 `academic_metrics.py` 的有效结果排序方式一致。
5. 本次不增加考试类型列，不跨库读取 V2 `attempt_type`。

#### 1.10.6 学生证据及完整档案（学生级）

| 编号 | 类型 | 现有修改点 | 目标设计 | 具体文件 |
|---|---|---|---|---|
| STU-01 | 现有功能修改 | `StudentEvidenceDrawer.vue` 显示最新有成绩学期的“当前 GPA” | 改为“总 GPA”，展示公式、纳入学分和排除记录说明；学期 GPA 趋势保留 | `StudentEvidenceDrawer.vue`、学生证据接口 |
| STU-02 | 现有功能修改 | `alert.py:student_detail()` KPI 为“当前 GPA” | 使用统一总 GPA 服务，完整档案显示相同数值和版本 | `alert.py:student_detail()`、`student/Detail.vue` |
| STU-03 | 现有功能增强 | 从课程名单进入完整档案后的返回依赖通用 returnTo | 保留课程、学期、页码、筛选和滚动位置，返回课程学生画像 | `StudentEvidenceDrawer.vue:openFullProfile()`、`student/Detail.vue` |

总 GPA 卡标题固定为“总 GPA”；Tooltip：

```text
按所有计入 GPA 的最终有效课程结果进行学分加权。
公式：Σ（课程GP×课程学分）÷Σ计入GPA课程学分。
```

若学校规则尚未确认，显示规则版本和“按产品默认有效结果规则计算”，不得隐藏边界。

### 1.11 待确认项及推荐默认值

以下推荐值在获得“全部按推荐方案执行”确认后写入实施基线；若用户指定其他值，以明确记录的值替换：

| 编号 | 待确认问题 | 推荐默认值 |
|---|---|---|
| DEC-01 | 历史有效预警率 | 不新增预警快照表；现有当前学期正常展示，旧学期显示“暂无真实历史快照”，不默认回算 |
| DEC-02 | 历史在籍分母 | 历史学期只读查询源库 `students` 表并与当前授权 ID 取交集；趋势中的当前统计学期使用总览卡片同一 `dim_student` 授权名单，保证当前值一致；不回填分析库 |
| DEC-03 | 历史范围 | 展示教学总览现有 9 个标准学期，不含第3学期 |
| DEC-04 | 优先核查 TOP1 | 学院和课程候选统一排序，只显示一个全局 TOP1 |
| DEC-05 | 课程未通过率 | 最终有效结果未通过学生数÷有最终有效结果学生数 |
| DEC-06 | 行政班风险排序 | 暂按未通过学生率降序，不发明复合风险系数 |
| DEC-07 | 课程成绩/GP | 显示所选课程和学期内最后一条真实有效记录的 score 与 gpa；本次不增加考试类型 |
| DEC-08 | 总 GPA | 复用现有每生每课最新有效结果，每门课程只计一次；零学分、不计 GPA、GP 缺失排除 |
| DEC-09 | 年级排列 | 按入学年级倒序固定排列，风险只做颜色强调 |
| DEC-10 | 课程详情平均 GPA | 显示当前课程范围内最终有效课程 GP 的算术平均，不使用学生的全课程总 GPA |
| DEC-11 | 学期显示与排序 | 本轮新增入口直接复用系统原有筛选元数据的学期 `value/label` 与“最新在前”顺序，不另建格式化或排序规则；当前数据下显示为 `YYYY-YYYY-N` |
| DEC-12 | 历史比率图 | 每学期一个柱位：指标色实心柱段为分子，覆盖柱总高的透明中性虚线边框为完整分母，折线为比率；自定义图例分别使用实心色块、虚线框和折线符号，并标注完整分母为“柱总高”；悬浮提示只展示分子、完整分母和比率，不展示内部差额；纵轴单位直接附在刻度值后 |
| DEC-13 | 历史空值展示 | 弹窗统一说明“‘-’：表示学年学期对应内容无数据或无计算结果”；图表悬浮和明细表空值均显示“-”，明细表不展示数据状态列；接口内部状态与原因继续保留用于空值判断，不改变计算逻辑 |
| DEC-14 | 历史环比显示 | 历年学期明细“较上学期”列只显示带正负号的数值，例如 `-4.1`，不追加“个百分点”；仅调整展示，不改变差值计算 |

## 2. Implementation Steps

### Implementation Phase 0: 确认门禁与基线冻结

- **GOAL-001**: 确保实施输入已经确认且公共设计规范可自动验收。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-001 | 检查本文件 front matter 状态；若不是 In progress，停止业务实现并只接受方案修订。 | ✅ | 2026-07-27 |
| TASK-002 | 将 DEC-01～DEC-12 的确认结果写入本文件，冻结指标名称、公式、分子、分母、数据范围、排序、图表和空值规则。 | ✅ | 2026-07-27 |
| TASK-003 | 建立公共契约和字段证据对照表；每个查询条件、默认列和排序字段记录接口字段、数据库字段或计算函数，未通过证据门禁的非必需字段不得实现。 | ✅ | 2026-07-27 |

### Implementation Phase 1: 只读历史数据访问与指标注册

- **GOAL-002**: 在不修改任何数据库结构和数据的前提下，复用现有分析库与各学期源库，建立所有层级共用的历史指标只读访问能力。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-004 | 新增 `code/backend/api/historical_roster.py` 只读适配器，复用 `etl/config.py:TS_DIR` 和 `extract_ts.py:SEMESTERS` 定位各学期源库，以 SQLite URI `mode=ro` 打开 `{semester}.db`，仅读取 `students` 表既有字段；禁止执行 DDL、DML 和落库缓存。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-005 | 在只读适配器中标准化 `student_id/college/major/grade_year/class_name`，以名称映射现有组织维表，并在内存中输出学期学生集合、组织集合、状态分布、映射率和重复学生统计；映射失败必须披露，不写回源库或分析库。依赖 TASK-004。 | ✅ | 2026-07-27 |
| TASK-006 | 增加有界进程内缓存，缓存键至少包含源库绝对路径、文件修改时间、学期、scope 类型/标识和授权范围指纹；缓存仅保存聚合结果或授权学生 ID 集合，服务重启可自然失效，不新增缓存表或本地持久化文件。依赖 TASK-005。 | ✅ | 2026-07-27 |
| TASK-007 | 按 DEC-01 实现历史预警可用性判定：仅使用现有 `fact_alert.semester_id/activation_batch_id` 能证明的真实期间；无法证明的旧学期返回 `null + unavailableReason`，不建快照表、不复制当前记录、不补 0。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-008 | 在 `dashboard.py` 建立 metricId 注册表，明确 8 个历史指标的名称、单位、公式、分子、分母、方向、来源和适用 scope。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-009 | 增加数据质量测试，验证源库只读打开、必需表/字段、学期完整、重复学生、组织映射、分子不大于分母、预警来源和 V2 标识映射；测试前后分析库与源库 schema 必须一致。依赖 TASK-006、TASK-007。 | ✅ | 2026-07-27 |

### Implementation Phase 2: 通用后端服务

- **GOAL-003**: 用同一后端接口支持学校、学院、专业历史下钻及课程画像数据。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-010 | 在 `code/backend/api/routers/dashboard.py` 新增 `GET /api/admin/dashboard/metric-history`，实现 metricId、scopeType、scopeId、起止学期参数校验。依赖 TASK-008。 | ✅ | 2026-07-27 |
| TASK-011 | 复用 `permission_context` 生成授权学生集合；学校、学院、专业聚合均在授权集合内计算，并拒绝越权 scopeId。依赖 TASK-010。 | ✅ | 2026-07-27 |
| TASK-012 | 按 1.5 节 scope 关联表实现覆盖率、挂科学生率、平均 GPA、有效预警学生率历史聚合；学院/专业历史范围使用只读源学期 `students` 适配器，GPA 复用 `per_student_weighted_gpa()`，历史预警只返回可证明的真实期间，不可用学期返回 null、状态和原因。依赖 TASK-004～TASK-007、TASK-011。 | ✅ | 2026-07-27 |
| TASK-013 | 实现四项课程结果通过率历史聚合；全校范围使用 `agg_course_pass_stat`，受限范围从授权学生 `grade_attempt` 聚合。依赖 TASK-011。 | ✅ | 2026-07-27 |
| TASK-014 | 为历史接口增加按身份范围指纹、metricId、scope 和起止学期隔离的短时缓存。依赖 TASK-012、TASK-013。 | ✅ | 2026-07-27 |
| TASK-015 | 在 `students.py:student_list()` 的 course+semester 模式按 student_id+course_id+semester_id 取最后一条真实有效 `fact_grade`，只新增 `courseScore` 和 `courseGp`。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-016 | 基于 `academic_metrics.py:effective_course_outcomes_for_students()` 建立累计 GPA 封装，按学生—课程最新真实有效结果去重后加权，输出总 GPA、分子、分母、排除数和规则版本。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-017 | 复用现有 `/api/admin/alerts/students` 和 `/api/admin/alerts/options`；专业通过已有 `major` 参数锁定，筛选仅使用 q、class_id、level、type、management，并增加契约测试验证专业范围和字段完整性。依赖 TASK-011。 | ✅ | 2026-07-27 |
| TASK-018 | 提供专业年级全部课程分页接口，参数仅含 major_id、grade、semester、q、page、page_size；返回 courseId、courseName、failCount、totalCount、failRate，包含零未通过课程。依赖 TASK-011。 | ✅ | 2026-07-27 |
| TASK-052 | 校准 `dashboard.py:dashboard()`、`college_detail()`、`major_detail()` 及学院年级/专业聚合中的 GPA：先按学生和学期用 `weighted_gpa_expression()` 计算学分加权 GPA，再对学生求平均；同步当前卡、比较表和历史接口。依赖 TASK-002。 | ✅ | 2026-07-27 |

### Implementation Phase 3: 通用前端能力

- **GOAL-004**: 实现符合系统规范的可复用下钻、筛选和返回能力。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-019 | 向 `KpiCard.vue` 增加默认关闭的 interactive、actionText、disabledReason 和 drilldown 事件，补齐键盘和焦点样式。 | ✅ | 2026-07-27 |
| TASK-020 | 新增 `MetricHistoryDialog.vue`，严格实现 1.5 节标题、查询、图表、表格、六类状态、重试、焦点恢复和响应式设计。依赖 TASK-010、TASK-019。 | ✅ | 2026-07-27 |
| TASK-021 | 新增历史指标前端配置映射，metricId 显式映射标题、单位、图表色、分子/分母列名，禁止按中文标题推断。依赖 TASK-020。 | ✅ | 2026-07-27 |
| TASK-022 | 新增共享 dashboard drill context 工具，负责 URL 参数、已应用条件、returnTo、分页和滚动恢复。 | ✅ | 2026-07-27 |
| TASK-023 | 新增 `MajorAlertStudentsDialog.vue`，按 1.4.1 已验证字段实现专业预警名单，并复用 `AlertStudentDrawer.vue` 的“核查”入口。依赖 TASK-017、TASK-019。 | ✅ | 2026-07-27 |
| TASK-024 | 新增 `GradeCoursesDrawer.vue`，只实现课程代码/名称关键词、已验证的五个数据字段、分页和课程详情入口。依赖 TASK-018。 | ✅ | 2026-07-27 |

### Implementation Phase 4: 校级与院级页面

- **GOAL-005**: 完成教学数据总览首页和学院详情的所有修改。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-025 | 修改 `dashboard/index.vue`，为四张管理摘要 KPI 和四张课程辅助指标绑定同一历史弹窗；不增加新的首屏卡片区。依赖 TASK-020、TASK-021。 | ✅ | 2026-07-27 |
| TASK-026 | 修改 `dashboard.py:dashboard()` 和首页文案，使优先核查严格符合 DEC-04。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-027 | 修改 `dashboard/Detail.vue`，为学院四张 KPI 绑定学院 scope 的同一历史弹窗。依赖 TASK-020。 | ✅ | 2026-07-27 |
| TASK-028 | 修改学院专业区标题、偏离列名、Tooltip 和 DataTable 配置版本。 | ✅ | 2026-07-27 |
| TASK-029 | 扩展 `college_detail()` 的 gradeCompare 和 majors 返回字段，补齐学分通过分子/分母、GPA 样本和不可用原因。依赖 TASK-008、TASK-052。 | ✅ | 2026-07-27 |
| TASK-030 | 将学院年级图改为四指标对比矩阵，并扩展现有专业表，不新增重复专业模块。依赖 TASK-029。 | ✅ | 2026-07-27 |

### Implementation Phase 5: 专业级与课程级页面

- **GOAL-006**: 完成专业详情和课程详情的所有修改。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-031 | 为专业 KPI 增加稳定 ID，将学生卡改为“在籍学生”并绑定现有专业学生下钻。依赖 TASK-019、TASK-022。 | ✅ | 2026-07-27 |
| TASK-032 | 为专业预警学生卡绑定名单弹窗，为覆盖率、挂科率、平均 GPA 绑定历史弹窗。依赖 TASK-020、TASK-023。 | ✅ | 2026-07-27 |
| TASK-033 | 在每个专业年级块保留 TOP3 摘要并增加“更多课程（N）”，打开年级课程抽屉。依赖 TASK-024。 | ✅ | 2026-07-27 |
| TASK-034 | 按 DEC-05 修改课程未通过率名称、公式、返回字段、Tooltip 和测试，不只修改显示文字。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-035 | 按 DEC-10 在 `course_detail()` 计算当前课程范围内最终有效课程 GP 的算术平均，并在 `CourseDetail.vue` 平均分后插入“平均 GPA”KPI。依赖 TASK-002、TASK-008。 | ✅ | 2026-07-27 |
| TASK-036 | 按 DEC-06 保留 `course_detail()` 现有“未通过人次率降序、同率按有效成绩人次降序”，前端直接使用全部 `classDetail`、把“人数”改为“有效成绩人次”，移除 TOP10 切片及重复抽屉。依赖 TASK-002。 | ✅ | 2026-07-27 |
| TASK-037 | 修改 `CourseDetail.vue:goStudents()`，使用课程画像专属路由并传递完整 drill context。依赖 TASK-022。 | ✅ | 2026-07-27 |

### Implementation Phase 6: 课程学生画像与学生档案

- **GOAL-007**: 完成课程—学生—档案证据链并保持原学生模块兼容。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-038 | 在 `router/index.ts` 新增 `/admin/course/:id/students`，路由准入按教学数据总览权限；保留原 `/admin/students/list`。 | ✅ | 2026-07-27 |
| TASK-039 | 修改 `menu.ts`，新课程画像路由激活教学数据总览，通用学生名单仍激活学生成长与学业分析。依赖 TASK-038。 | ✅ | 2026-07-27 |
| TASK-040 | 扩展 `students/List.vue` 的 courseProfile 模式，实现固定标题、范围条、锁定课程/学期、查询/重置和返回。依赖 TASK-022、TASK-038。 | ✅ | 2026-07-27 |
| TASK-041 | 仅在 courseProfile 模式把“课程成绩”和“课程成绩绩点(GP)”插到筛选期 GPA 前，提升 DataTable configVersion并配置必选/默认隐藏列。依赖 TASK-015、TASK-040。 | ✅ | 2026-07-27 |
| TASK-042 | 修改学生证据接口和 `StudentEvidenceDrawer.vue`，把当前 GPA 改为统一总 GPA并显示公式、纳入学分、排除数和版本。依赖 TASK-016。 | ✅ | 2026-07-27 |
| TASK-043 | 修改 `alert.py:student_detail()` 和 `student/Detail.vue`，完整档案使用同一总 GPA；保留学期 GPA 趋势。依赖 TASK-016。 | ✅ | 2026-07-27 |
| TASK-044 | 验证课程画像 → 学生证据 → 完整档案 → 原课程画像的返回链，恢复筛选、分页和滚动。依赖 TASK-039～TASK-043。 | ✅ | 2026-07-27 |

### Implementation Phase 7: 文档、测试与交付

- **GOAL-008**: 证明所有修改符合业务、视觉、权限、数据和交付规范。

| Task | Description | Completed | Date |
|---|---|---|---|
| TASK-045 | 新增历史指标、权限、只读源学期适配、课程成绩/GP、总 GPA、零分母、GPA层级一致性、行政班排序和年级课程分页后端测试。依赖 TASK-004～TASK-044、TASK-052。 | ✅ | 2026-07-27 |
| TASK-046 | 新增前端契约测试，覆盖 Style A 类名/变量、标题、查询条件、KPI 下钻、菜单激活、表格列、六类状态和返回上下文。依赖 TASK-019～TASK-044。 | ✅ | 2026-07-27 |
| TASK-047 | 更新 `docs/本科教学分析与学业决策支持平台需求调研及指标口径确认书V2.md`，同步名称、公式、用途、来源、边界和核查路径。依赖 TASK-025～TASK-044。 | ✅ | 2026-07-27 |
| TASK-048 | 更新 `docs/94-教学数据总览UE深度走查与优化方案.md`、`docs/80-原型最终集成验收与生产交接清单.md` 和 `docs/82-产品终稿改造执行计划与检查表.md`。依赖 TASK-025～TASK-044。 | ✅ | 2026-07-27 |
| TASK-049 | 执行前端生产构建、完整后端单测、e2e_check.py 和 git diff --check。依赖 TASK-045～TASK-048。 | ✅ | 2026-07-27 |
| TASK-050 | 按校领导/教务处、学院、两个班主任/辅导员、两个导师、系统管理员完成浏览器回归，覆盖直接 URL、接口、导出、下钻、返回和身份切换。依赖 TASK-049。 | ✅ | 2026-07-27 |
| TASK-051 | 仓库版本确认后，将指标口径确认书同步覆盖到 `D:\AI教育\AI学业助手\14-技术方案\本科教学分析与学业决策支持平台需求调研及指标口径确认书V2.md`。依赖 TASK-050。 | ✅ | 2026-07-27 |

## 3. Alternatives

- **ALT-001**: 每个页面分别实现一套历史弹窗。未采用，因为会重复指标口径、图表、权限和异常逻辑；改用 metricId + scope 的通用能力。
- **ALT-002**: 将历史下钻做成独立路由页面。未采用，因为需求是从 KPI 查看辅助历史证据，弹窗更能保留当前工作现场且不增加隐性菜单。
- **ALT-003**: 弹窗同时允许切换指标和组织。未采用，因为会扩大权限和认知范围；指标和组织从触发卡锁定，只允许调整起止学期。
- **ALT-004**: 表格拆分学年、学期两列。未采用，因为每条记录只有一个完整周期，合并为“学年学期”更紧凑且目标不变。
- **ALT-005**: 为各专业本学期修读结果再建一张新表。未采用，因为学院页已有全专业表；直接扩展现有表可避免重复信息和两套排序。
- **ALT-006**: 用当前学籍人数作为所有历史分母。未采用，因为组织和学籍状态会变化，结果不可审计；改为查询现有各学期源库的 `students` 表并在内存聚合。
- **ALT-007**: 用当前预警记录填满所有历史学期。未采用，因为会伪造历史状态；缺失必须披露或经确认后按当前规则回算。
- **ALT-008**: 立即建立复合行政班风险系数。暂未采用，因为缺少正式权重和版本；默认使用明确的未通过学生率排序。
- **ALT-009**: 复制一套新的课程学生名单页面。未采用，复用 `students/List.vue` 的显式 courseProfile 模式可保持筛选、证据和分页能力一致。
- **ALT-010**: 新建历史学籍表或预警快照表。未采用，因为本轮原则上不增加、删除或修改数据库表、字段、索引和约束；历史学籍走现有源库只读查询，历史预警缺失如实披露。

## 4. Dependencies

- **DEP-001**: `docs/93-教学管理分析UE公共契约.md`，所有新增交互和页面的强制基线。
- **DEP-002**: `code/frontend/src/assets/styles/core/style-a.scss`，现有配色、字号、圆角、间距和视觉语义。
- **DEP-003**: `KpiCard.vue`、`DataTable.vue`、`EChart.vue` 和 Element Plus，禁止另建平行 UI 体系。
- **DEP-004**: `code/backend/api/deps.py` 的当前身份和数据范围解析。
- **DEP-005**: `analytics.sqlite` 的成绩、当前学籍、组织和预警数据，仅只读查询，不调整 schema。
- **DEP-006**: `analytics_v2.sqlite` 的 `grade_attempt` 与 `agg_course_pass_stat`，仅只读查询，不调整 schema。
- **DEP-007**: 各学期源数据库的 `students` 表，按只读连接访问；真实数据库不修改、不提交 Git。
- **DEP-008**: 学校正式的学籍状态、补考、重修和 GPA 规则，用于替换或确认 DEC-02、DEC-07、DEC-08。

## 5. Files

- **FILE-001**: `code/backend/api/routers/dashboard.py`：历史指标接口、首页、学院、专业、课程聚合。
- **FILE-002**: `code/backend/api/routers/students.py`：课程学生画像列表、课程成绩和 GP。
- **FILE-003**: `code/backend/api/routers/alert.py`：学生完整档案和总 GPA。
- **FILE-004**: `code/backend/api/routers/alert_monitor.py`：复用现有专业预警名单筛选和返回契约；仅在契约测试发现缺陷时修正，不新增未经验证字段。
- **FILE-005**: `code/backend/api/deps.py`：仅复用或补充统一 scope helper，不复制角色白名单。
- **FILE-006**: `code/backend/api/historical_roster.py`：新增各学期源库只读访问、标准化、组织映射与进程内缓存；不包含 DDL/DML。
- **FILE-007**: `code/backend/etl/config.py`、`code/backend/etl/extract_ts.py`：仅复用既有 `TS_DIR`、学期清单和字段契约，原则上不修改。
- **FILE-008**: `code/frontend/src/components/KpiCard.vue`：可选下钻交互。
- **FILE-009**: `code/frontend/src/components/MetricHistoryDialog.vue`：新增通用历史指标弹窗。
- **FILE-010**: `code/frontend/src/components/MajorAlertStudentsDialog.vue`：新增专业预警名单弹窗。
- **FILE-011**: `code/frontend/src/components/GradeCoursesDrawer.vue`：新增年级全部课程抽屉。
- **FILE-012**: `code/frontend/src/views/admin/dashboard/index.vue`：校级修改。
- **FILE-013**: `code/frontend/src/views/admin/dashboard/Detail.vue`：院级修改。
- **FILE-014**: `code/frontend/src/views/admin/dashboard/MajorDetail.vue`：专业级修改。
- **FILE-015**: `code/frontend/src/views/admin/dashboard/CourseDetail.vue`：课程级修改。
- **FILE-016**: `code/frontend/src/views/admin/students/List.vue`：课程学生画像模式。
- **FILE-017**: `code/frontend/src/components/StudentEvidenceDrawer.vue`：学生证据总 GPA。
- **FILE-018**: `code/frontend/src/views/admin/student/Detail.vue`：完整档案总 GPA 和返回。
- **FILE-019**: `code/frontend/src/router/index.ts`、`code/frontend/src/utils/menu.ts`：路由、准入、菜单激活。
- **FILE-020**: `code/backend/tests/`：历史指标、权限、课程画像和总 GPA 契约测试。
- **FILE-021**: `docs/94-教学数据总览UE深度走查与优化方案.md`、`docs/80-原型最终集成验收与生产交接清单.md`、`docs/82-产品终稿改造执行计划与检查表.md`。
- **FILE-022**: `docs/本科教学分析与学业决策支持平台需求调研及指标口径确认书V2.md`。
- **FILE-023**: 真实数据库、`.env`、密钥、令牌、运行日志和个人配置不得修改后提交。

## 6. Testing

- **TEST-001**: 历史指标接口在 school、college、major scope 下返回相同结构；学院/专业分子分母使用对应学期源库 `students` 的组织字段，不使用当前 `dim_student` 组织反推历史。
- **TEST-002**: 越权 collegeId、majorId、courseId、studentId 返回 403 或空授权结果，不回退全校。
- **TEST-003**: 源学期适配器使用 `mode=ro`，同一条件重复查询结果一致；历史分母不读取当前 `dim_student` 代替，查询前后源库和分析库的文件修改时间与 schema 指纹不变。
- **TEST-004**: 无真实历史预警数据的学期返回 `null + unavailableReason`，不返回 0%，也不使用当前预警记录填充。
- **TEST-005**: 比率弹窗标题、范围、起止学期、查询/重置、单柱堆叠、折线和明细表一致。
- **TEST-006**: GPA 弹窗只绘制 GPA 折线，空值形成断点且不落到 0。
- **TEST-007**: Style A 变量、`.sa-page-title`、`.sa-page-sub`、`.sa-card`、`.sa-kpi-row` 和 `DataTable` 被复用，无新增平行主题。
- **TEST-008**: 可下钻 KPI 有 hover、焦点、Enter/Space 和明确动作提示；静态 KPI 不显示点击暗示。
- **TEST-009**: 学院年级矩阵和专业表同时显示需求四指标，空值和风险颜色符合公共契约。
- **TEST-010**: 专业预警名单固定专业范围，验证 q、class_id、level、type、management 五项筛选，以及 student、grade、className、highestLevel、primaryReason、alertCount、managementLabel、latestAt 字段和核查入口。
- **TEST-011**: 年级更多课程只使用课程关键词，按需加载包含零未通过课程的全部课程；返回字段严格为课程代码、名称、未通过人次、有效成绩人次、未通过人次率及分页信息。
- **TEST-012**: 课程全部行政班按未通过人次率、有效成绩人次降序；表格只展示现有可获取字段，不出现复合风险系数、行政班 GPA 或未通过学生数。
- **TEST-013**: `/admin/course/:id/students` 标题为“课程-学生学业画像”，激活教学数据总览；`/admin/students/list` 仍激活学生成长。
- **TEST-014**: 课程画像锁定课程和学期，重置不清空锁定上下文，查询条件不出现后端不支持的预警状态，课程成绩/GP 位于筛选期 GPA 前。
- **TEST-015**: 同一学生、课程、学期存在多条有效记录时只显示最后一条真实有效 score 和 gpa，不返回未规划的考试类型。
- **TEST-016**: 学生证据和完整档案总 GPA 数值、公式、纳入学分、排除数和规则版本一致。
- **TEST-017**: 课程画像 → 证据抽屉 → 完整档案 → 返回时恢复筛选、页码和滚动位置。
- **TEST-018**: 所有新增内容覆盖加载中、正常、无数据、部分数据、无权限和失败六种状态。
- **TEST-019**: 前端执行 `npm.cmd run build`；后端执行 `python -X utf8 -m unittest discover -s code/backend/tests`。
- **TEST-020**: 服务运行后执行 `python -X utf8 code/scripts/e2e_check.py` 和多角色浏览器回归。
- **TEST-021**: 提交前执行 `git diff --check`，确认未包含数据库、密钥、环境文件和任务外修改。
- **TEST-022**: 自动扫描新增前端列 key 和查询参数，逐项与后端响应契约/函数签名匹配；无证据字段使测试失败。
- **TEST-023**: 使用同一成绩夹具验证学校、学院、专业当前卡、学院年级/专业表和历史弹窗的学生平均 GPA 均为“个人学分加权 GPA 后按学生平均”，且分子分母均受对应 scope 限制。
- **TEST-024**: 对比开发前后 `analytics.sqlite`、`analytics_v2.sqlite` 和各学期源库的 `sqlite_master`、`PRAGMA table_info`、索引与约束清单，确认本轮无表、字段、索引或约束增加、减少和修改。

## 7. Risks & Assumptions

- **RISK-001**: 历史学籍状态映射不完整会改变覆盖率和预警率分母；实施前必须输出状态分布并确认纳入规则。
- **RISK-002**: 当前没有真实历史预警快照；默认缺失披露会使弹窗早期数据不完整，但比伪造历史可靠。
- **RISK-003**: 旧库和 V2 库的学期、课程或学生标识可能无法全部映射；未映射记录必须计数、披露并排除。
- **RISK-004**: “未通过率”和“风险系数”若只改文案会产生正式口径误导；DEC-05、DEC-06 未冻结前不得实施。
- **RISK-005**: 学校补考/重修政策可能不同于最终有效结果默认规则；总 GPA 必须保留公式版本和边界。
- **RISK-006**: 扩展通用 `KpiCard` 可能影响其他模块；新增行为默认关闭并进行全局视觉回归。
- **RISK-007**: `students/List.vue` 双模式可能互相污染；必须以 route meta 和显式列配置隔离。
- **RISK-008**: 预警学生和全部课程可能增加数据量，使用现有/新增服务端分页；行政班限定单课程单学期，先使用现有全量返回和前端分页，并设置数量与响应耗时监测阈值。
- **ASSUMPTION-001**: 各学期源库 `students` 表可读取并可映射统一组织和学生标识。
- **ASSUMPTION-002**: V2 成绩尝试字段足以区分首次、补考、重修、最终有效结果和 GP。
- **ASSUMPTION-003**: 本次不新增菜单，不改变教学数据总览以外模块的产品定位。
- **ASSUMPTION-004**: 用户接受在目标一致的前提下合并低价值字段、复用组件和调整展示形式。
- **ASSUMPTION-005**: 如只读源库或现有字段无法支持某项指标，本轮优先降级为“不可用/部分可用”并披露原因，不以修改数据库结构兜底；任何例外须另立需求并再次确认。

## 8. Related Specifications / Further Reading

- `修改需求/07.26 教学数据总览修改说明.md`
- `docs/93-教学管理分析UE公共契约.md`
- `docs/94-教学数据总览UE深度走查与优化方案.md`
- `docs/04-使用手册.md`
- `docs/05-二次开发指南.md`
- `docs/80-原型最终集成验收与生产交接清单.md`
- `docs/82-产品终稿改造执行计划与检查表.md`
- `code/frontend/src/assets/styles/core/style-a.scss`
- `code/frontend/src/components/KpiCard.vue`
- `code/frontend/src/components/DataTable.vue`
- `code/backend/api/routers/dashboard.py`
