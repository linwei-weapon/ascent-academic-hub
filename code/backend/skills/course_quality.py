"""Skill 2：课程质量趋势 course-quality。

回答：9个学期的成绩序列里，哪些课程的未通过问题是结构性的（值得立项复盘），
哪些只是正常波动（不该浪费资源）？

判定逻辑树（阈值相对化——走查证实绝对阈值20%在本校数据中命中0门）：
  前置: 动态计算全校基线 = 当前学期全部可比课程未通过率中位数
  A 可比性门槛: ≥2学期 且 每学期样本≥min_sample
  B 状态判定:
    B1 持续偏高: 最近2学期 均 > max(基线×multiplier, floor)
    B2 显著恶化: 本学期 - 前期均值 > delta_pp 且 本学期 > 基线×1.5
    B3 高影响面: 未通过人数(必修加权×1.5) ≥ high_impact_students 且 率>基线
    B4 正常波动: 不输出
  C 下钻证据: 挂科分数段分布、先修链、改善课程清单

边界：不对未通过率差异做原因归因，只输出"值得核查"及核查方向。

M1 起课程级信号附带 V2 agg_course_pass_stat 的三分层通过率（首次/补考/重修）
与课程类别（公共必修等）作为附加证据；主判定序列仍基于 legacy fact_grade，
三分层只加不改，聚合表缺失时附加事实自动省略。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..api.deps import student_data_scope
from ..api import db as dbm
from .protocol import (DataRequirement, Signal, Skill, SkillContext,
                       SkillResult)

DATA_BOUNDARY = (
    "趋势判定基于相对基线（全校动态中位数），基线随全校整体水平变化；"
    "本Skill只标记值得核查的课程，不对未通过率差异做教学原因归因；"
    "信号附带的首次/补考/重修通过率与课程类别来自V2 agg_course_pass_stat"
    "（grade_attempt attempt_type 三分层，全校累计口径），仅作附加证据，不参与判定。"
)

VERIFY_ROUTE = "/admin/operation/course-quality"


class CourseQualitySkill(Skill):
    skill_id = "course-quality"
    name = "课程质量趋势"
    management_question = "哪些课程的未通过问题是结构性的（值得立项复盘），哪些只是正常波动？"
    description = ("9学期成绩序列上区分持续偏高/显著恶化/高影响面/正常波动，"
                   "并为命中课程自动生成挂科分数段与先修链下钻证据。")
    briefing_tier = "main"
    data_requirements = [
        DataRequirement("fact_grade", "legacy", True, "课程未通过率与分数段"),
        DataRequirement("dim_course", "legacy", True, "课程名称与必修属性"),
        DataRequirement("dim_student", "legacy", False, "权限范围过滤"),
        DataRequirement("agg_course_pass_stat", "v2", False,
                        "M1课程通过率三分层与课程类别（附加证据）"),
    ]
    data_boundary = DATA_BOUNDARY

    default_config = {
        "persistent_multiplier": 2.0,
        "persistent_floor": 0.10,
        "spike_multiplier": 1.5,
        "spike_delta_pp": 5.0,
        "min_sample": 30,
        "high_impact_students": 100,
        "required_weight": 1.5,
        "improve_delta_pp": 3.0,
        "max_course_signals": 6,
    }
    config_bounds = {
        "persistent_multiplier": {"type": "float", "min": 1.2, "max": 5.0},
        "persistent_floor": {"type": "float", "min": 0.03, "max": 0.40},
        "spike_multiplier": {"type": "float", "min": 1.1, "max": 4.0},
        "spike_delta_pp": {"type": "float", "min": 2.0, "max": 30.0},
        "min_sample": {"type": "int", "min": 20, "max": 200},
        "high_impact_students": {"type": "int", "min": 30, "max": 1000},
        "required_weight": {"type": "float", "min": 1.0, "max": 3.0},
        "improve_delta_pp": {"type": "float", "min": 1.0, "max": 20.0},
        "max_course_signals": {"type": "int", "min": 2, "max": 15},
    }

    # 明细下钻：门数类数字直达课程清单，"未通过人数"直达本学期挂科学生清单；
    # "全校基线/修读人数/课程属性/状态"等聚合或判定值不下钻。
    _OVERVIEW_COURSE_COLUMNS = [
        {"key": "course_id", "label": "课程号"},
        {"key": "course_name", "label": "课程名称"},
        {"key": "rate_pct", "label": "本学期未通过率(%)"},
        {"key": "fails", "label": "未通过人数"},
        {"key": "total", "label": "修读人数"},
    ]
    detail_specs = {
        "quality_overview": {
            "持续偏高": {
                "context_key": "courses",
                "title": "持续偏高课程清单（建议立项复盘）",
                "columns": _OVERVIEW_COURSE_COLUMNS,
                "filter": {"key": "state", "equals": "persistent"},
            },
            "显著恶化": {
                "context_key": "courses",
                "title": "显著恶化课程清单（建议原因核查）",
                "columns": _OVERVIEW_COURSE_COLUMNS,
                "filter": {"key": "state", "equals": "spike"},
            },
            "高影响面": {
                "context_key": "courses",
                "title": "高影响面课程清单（建议学习支持）",
                "columns": _OVERVIEW_COURSE_COLUMNS,
                "filter": {"key": "state", "equals": "high_impact"},
            },
        },
        "course_persistent": {
            "未通过人数": {
                "context_key": "failed_students",
                "title": "本学期未通过学生清单",
                "columns": [
                    {"key": "student_id", "label": "学号"},
                    {"key": "student_name", "label": "姓名"},
                    {"key": "college_id", "label": "学院"},
                    {"key": "score", "label": "分数"},
                ],
                "total_key": "failed_total",
            },
        },
        "course_spike": {
            "未通过人数": {
                "context_key": "failed_students",
                "title": "本学期未通过学生清单",
                "columns": [
                    {"key": "student_id", "label": "学号"},
                    {"key": "student_name", "label": "姓名"},
                    {"key": "college_id", "label": "学院"},
                    {"key": "score", "label": "分数"},
                ],
                "total_key": "failed_total",
            },
        },
        "course_high_impact": {
            "未通过人数": {
                "context_key": "failed_students",
                "title": "本学期未通过学生清单",
                "columns": [
                    {"key": "student_id", "label": "学号"},
                    {"key": "student_name", "label": "姓名"},
                    {"key": "college_id", "label": "学院"},
                    {"key": "score", "label": "分数"},
                ],
                "total_key": "failed_total",
            },
        },
        "improving": {
            "改善课程": {
                "context_key": "courses",
                "title": "持续改善课程清单",
                "columns": [
                    {"key": "course_id", "label": "课程号"},
                    {"key": "course_name", "label": "课程名称"},
                    {"key": "from", "label": "改善前未通过率(%)"},
                    {"key": "to", "label": "本学期未通过率(%)"},
                ],
            },
        },
    }

    # ---------------------------------------------------------------
    def run(self, ctx: SkillContext) -> SkillResult:
        cfg = ctx.config
        legacy = ctx.legacy
        readiness = self.check_readiness(legacy, ctx.v2)
        if not readiness["ready"]:
            return self._unavailable(ctx, readiness)

        scope_sql, scope_params = self._scope(ctx)
        trend = self._course_trend(legacy, ctx.semester, scope_sql, scope_params, cfg)
        baseline = self._baseline(trend, ctx.semester)
        judged = self._judge(legacy, trend, baseline, ctx.semester, cfg)
        improving = self._improving(trend, baseline, ctx.semester, cfg)

        signals: list[Signal] = []
        signals += self._overview_signal(judged, baseline, ctx.semester)
        signals += self._course_signals(legacy, judged, cfg, ctx.semester,
                                        scope_sql, scope_params, v2=ctx.v2)
        signals += self._positive_signal(improving)

        stats = {
            "baseline_fail_rate": round(baseline * 100, 1),
            "comparable_courses": len({t["course_id"] for t in trend}),
            "persistent_courses": sum(1 for j in judged if j["state"] == "persistent"),
            "spike_courses": sum(1 for j in judged if j["state"] == "spike"),
            "high_impact_courses": sum(1 for j in judged if j["state"] == "high_impact"),
            "improving_courses": len(improving),
        }
        exclusions = [{
            "what": f"{stats['comparable_courses'] - stats['persistent_courses'] - stats['spike_courses'] - stats['high_impact_courses']}门可比课程",
            "why": "未通过率处于全校基线正常区间或为单学期小波动，不输出核查信号",
        }]
        return SkillResult(
            skill_id=self.skill_id, skill_name=self.name,
            management_question=self.management_question,
            signals=signals, summary_stats=stats, exclusions=exclusions,
            data_readiness=readiness, config_version=ctx.config_version,
            data_boundary=self.data_boundary, run_at=_now(),
        )

    # ---------------------------------------------------------------
    def _scope(self, ctx: SkillContext):
        context = ctx.user.get("permission_context") or {}
        if not context:
            return "", []
        frag, params = student_data_scope(ctx.user, ctx.legacy, "s")
        return (f" AND {frag}" if frag else ""), params

    def _course_trend(self, legacy, semester, scope_sql, scope_params, cfg):
        """课程×学期未通过率序列。有范围过滤时 join 学生表。"""
        join_s = "JOIN dim_student s ON s.student_id=g.student_id" if scope_sql else ""
        return dbm.query(legacy, f"""
            SELECT g.course_id, COALESCE(c.name, g.course_id) course_name,
                   MAX(COALESCE(g.is_required, c.is_required, 0)) is_required,
                   g.semester_id,
                   COUNT(*) total,
                   SUM(CASE WHEN g.is_pass=0 THEN 1 ELSE 0 END) fails
            FROM fact_grade g
            {join_s}
            LEFT JOIN dim_course c ON c.course_id=g.course_id
            WHERE g.score IS NOT NULL AND g.is_pass IS NOT NULL
              {scope_sql}
            GROUP BY g.course_id, g.semester_id
            HAVING COUNT(*) >= ?
        """, tuple(scope_params + [int(cfg["min_sample"])]))

    def _baseline(self, trend, semester):
        rates = sorted(
            t["fails"] / t["total"]
            for t in trend if t["semester_id"] == semester and t["total"] > 0
        )
        if not rates:
            return 0.0
        mid = len(rates) // 2
        if len(rates) % 2:
            return rates[mid]
        return (rates[mid - 1] + rates[mid]) / 2

    def _judge(self, legacy, trend, baseline, semester, cfg):
        by_course: dict[str, list] = {}
        for t in trend:
            by_course.setdefault(t["course_id"], []).append(t)

        floor = float(cfg["persistent_floor"])
        mult = float(cfg["persistent_multiplier"])
        spike_mult = float(cfg["spike_multiplier"])
        delta = float(cfg["spike_delta_pp"]) / 100
        impact_n = int(cfg["high_impact_students"])
        req_w = float(cfg["required_weight"])
        threshold = max(baseline * mult, floor)

        judged = []
        for course_id, rows in by_course.items():
            rows.sort(key=lambda r: r["semester_id"])
            sems = [r["semester_id"] for r in rows]
            if semester not in sems:
                continue
            cur = rows[-1]
            cur_rate = cur["fails"] / cur["total"] if cur["total"] else 0
            name = cur["course_name"]
            weighted_fails = cur["fails"] * (req_w if cur["is_required"] else 1.0)

            state = None
            # B1 持续偏高：最近2学期均超线
            if len(rows) >= 2:
                prev = rows[-2]
                prev_rate = prev["fails"] / prev["total"] if prev["total"] else 0
                if cur_rate > threshold and prev_rate > threshold:
                    state = "persistent"
            # B2 显著恶化
            if state is None and len(rows) >= 2:
                hist = [r for r in rows[:-1]][-4:]
                hist_rates = [r["fails"] / r["total"] for r in hist if r["total"]]
                if hist_rates:
                    avg = sum(hist_rates) / len(hist_rates)
                    if (cur_rate - avg) * 100 > float(cfg["spike_delta_pp"]) \
                            and cur_rate > baseline * spike_mult:
                        state = "spike"
            # B3 高影响面
            if state is None and weighted_fails >= impact_n and cur_rate > baseline:
                state = "high_impact"
            if state is None:
                continue
            history = [
                {"semester": r["semester_id"], "rate": round(r["fails"] / r["total"] * 100, 1),
                 "total": r["total"], "fails": r["fails"]}
                for r in rows[-4:]
            ]
            judged.append({
                "course_id": course_id, "course_name": name,
                "is_required": cur["is_required"], "state": state,
                "cur_rate": cur_rate, "cur_fails": cur["fails"],
                "cur_total": cur["total"], "history": history,
            })
        rank = {"persistent": 0, "spike": 1, "high_impact": 2}
        judged.sort(key=lambda j: (rank[j["state"]], -j["cur_rate"]))
        return judged

    def _improving(self, trend, baseline, semester, cfg):
        delta = float(cfg["improve_delta_pp"]) / 100
        by_course: dict[str, list] = {}
        for t in trend:
            by_course.setdefault(t["course_id"], []).append(t)
        out = []
        for course_id, rows in by_course.items():
            rows.sort(key=lambda r: r["semester_id"])
            if len(rows) < 3 or rows[-1]["semester_id"] != semester:
                continue
            r3, r2, r1 = rows[-3:]
            f3 = r3["fails"] / r3["total"] if r3["total"] else 0
            f2 = r2["fails"] / r2["total"] if r2["total"] else 0
            f1 = r1["fails"] / r1["total"] if r1["total"] else 0
            if f1 < f2 < f3 and (f3 - f1) >= delta and f3 > baseline:
                out.append({"course_id": course_id, "course_name": r1["course_name"],
                            "from": round(f3 * 100, 1), "to": round(f1 * 100, 1)})
        out.sort(key=lambda x: x["from"] - x["to"], reverse=True)
        return out[:5]

    # ---------------------------------------------------------------
    def _overview_signal(self, judged, baseline, semester) -> list[Signal]:
        if not judged:
            return []
        persistent = [j for j in judged if j["state"] == "persistent"]
        spike = [j for j in judged if j["state"] == "spike"]
        impact = [j for j in judged if j["state"] == "high_impact"]
        sev = "high" if persistent else "medium"
        parts = []
        if persistent:
            parts.append(f"{len(persistent)}门持续偏高（建议立项复盘）")
        if spike:
            parts.append(f"{len(spike)}门显著恶化（建议原因核查）")
        if impact:
            parts.append(f"{len(impact)}门高影响面（建议学习支持）")
        top = judged[0]
        return [Signal(
            signal_id=f"{self.skill_id}:overview:{semester}",
            skill_id=self.skill_id,
            signal_type="quality_overview",
            severity=sev,
            headline=(f"本学期课程质量核查清单：{'，'.join(parts)}。"
                      f"全校未通过率基线为{round(baseline * 100, 1)}%，"
                      f"最需关注的是{top['course_name']}"),
            facts={
                "持续偏高": f"{len(persistent)}门",
                "显著恶化": f"{len(spike)}门",
                "高影响面": f"{len(impact)}门",
                "全校基线": f"{round(baseline * 100, 1)}%",
            },
            entity={"type": "course_set", "id": f"quality-{semester}",
                    "name": "本学期课程质量核查清单"},
            action={
                "owner": "教务处教研科",
                "what": "按状态类型分流：持续偏高立项复盘，显著恶化核查原因，高影响面配学习支持",
                "when": "下一轮教学任务制定前",
                "rationale": "三类问题的干预成本差一个数量级，混用同一种手段会错配资源",
            },
            consequence="若对持续性问题只做临时处置，每学期将重复投入重修成本且问题不收敛。",
            confidence="high",
            evidence={
                "table": "fact_grade",
                "condition": "按课程×学期聚合，样本≥min_sample",
                "verify_route": VERIFY_ROUTE,
                "freshness": f"截至{semester}学期成绩",
            },
            suggested_questions=[
                "持续偏高的课程有哪些共同特征？",
                "显著恶化的课程分数段怎么分布？",
            ],
            # 门数类数字的课程清单（明细下钻数据源，不进信号指纹）
            context={
                "courses": [
                    {"course_id": j["course_id"], "course_name": j["course_name"],
                     "state": j["state"],
                     "rate_pct": round(j["cur_rate"] * 100, 1),
                     "fails": j["cur_fails"], "total": j["cur_total"]}
                    for j in judged
                ],
            },
            data_boundary=DATA_BOUNDARY,
        )]

    def _pass_layers(self, v2, course_id):
        """M1：V2 agg_course_pass_stat 三分层通过率与课程类别（全校累计口径）。

        纯附加证据：库/表缺失或课程无记录时返回 None，不影响主判定。
        """
        if v2 is None:
            return None
        try:
            exists = dbm.scalar(v2, """SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='agg_course_pass_stat'""")
            if not exists:
                return None
            row = dbm.query_one(v2, """
                SELECT MAX(course_group) course_group,
                       SUM(first_attempts) fa, SUM(first_pass) fp,
                       SUM(makeup_attempts) ma, SUM(makeup_pass) mp,
                       SUM(retake_attempts) ra, SUM(retake_pass) rp
                FROM agg_course_pass_stat WHERE course_id=?
                GROUP BY course_id""", (course_id,))
        except Exception:
            return None
        if not row:
            return None

        def _pct(passed, attempts):
            return round(passed * 100.0 / attempts, 1) if attempts else None

        return {
            "course_group": row.get("course_group"),
            "first_pass_rate": _pct(row.get("fp"), row.get("fa")),
            "makeup_pass_rate": _pct(row.get("mp"), row.get("ma")),
            "retake_pass_rate": _pct(row.get("rp"), row.get("ra")),
        }

    def _course_signals(self, legacy, judged, cfg, semester,
                        scope_sql="", scope_params=(), v2=None) -> list[Signal]:
        signals = []
        for j in judged[: int(cfg["max_course_signals"])]:
            band = self._score_band(legacy, j["course_id"], semester)
            prereq = self._prereq_signal(legacy, j["course_name"])
            layers = self._pass_layers(v2, j["course_id"])
            failed_rows, failed_total = self._failed_students(
                legacy, j["course_id"], semester, scope_sql, scope_params)
            state_label = {"persistent": "持续偏高", "spike": "显著恶化",
                           "high_impact": "高影响面"}[j["state"]]
            action_map = {
                "persistent": {
                    "owner": "开课学院 + 教务处教研科",
                    "what": f"对{j['course_name']}启动课程级复盘（考核结构、先修链条、教学支持）",
                    "when": "下一轮教学任务制定前",
                    "rationale": "连续多学期超过全校基线，属于结构性问题，临时手段无法收敛",
                },
                "spike": {
                    "owner": "开课学院",
                    "what": f"核查{j['course_name']}本学期异常原因（先核对成绩录入与考核变化，再判断教学因素）",
                    "when": "本学期成绩复核期内",
                    "rationale": "单学期显著偏离自身基线，先排除数据与考核口径因素",
                },
                "high_impact": {
                    "owner": "开课学院 + 学工部",
                    "what": f"为{j['course_name']}配置助教/答疑等学习支持资源",
                    "when": "下一轮开课前",
                    "rationale": "未通过人数规模大，支持资源覆盖效率最高",
                },
            }
            band_text = ""
            if band:
                band_text = f"；挂科集中在{band['band']}分段（占{band['pct']}%）"
            prereq_text = f"；{prereq}" if prereq else ""
            facts = {
                "本学期未通过率": f"{round(j['cur_rate'] * 100, 1)}%",
                "未通过人数": f"{j['cur_fails']}人",
                "修读人数": f"{j['cur_total']}人",
                "课程属性": "必修" if j["is_required"] else "选修",
                "状态": state_label,
            }
            if layers:
                # M1：三分层通过率与课程类别（只加不改既有键）。
                facts["首次通过率"] = (
                    f"{layers['first_pass_rate']}%" if layers["first_pass_rate"] is not None else "—")
                facts["补考通过率"] = (
                    f"{layers['makeup_pass_rate']}%" if layers["makeup_pass_rate"] is not None else "—")
                facts["重修通过率"] = (
                    f"{layers['retake_pass_rate']}%" if layers["retake_pass_rate"] is not None else "—")
                facts["课程类别"] = layers["course_group"] or "其他"
            signals.append(Signal(
                signal_id=f"{self.skill_id}:course:{j['course_id']}",
                skill_id=self.skill_id,
                signal_type=f"course_{j['state']}",
                severity="high" if j["state"] == "persistent" else "medium",
                headline=(f"{j['course_name']}（{state_label}）：本学期未通过率"
                          f"{round(j['cur_rate'] * 100, 1)}%、{j['cur_fails']}人未通过"
                          f"{band_text}{prereq_text}"),
                facts=facts,
                entity={"type": "course", "id": j["course_id"],
                        "name": j["course_name"]},
                action=action_map[j["state"]],
                consequence={
                    "persistent": "若不立项复盘，该课将持续占据重修资源并影响后续课程链条。",
                    "spike": "若不及时核查，异常原因将无从追溯，下学期可能重演。",
                    "high_impact": "若不配置支持，大量学生将进入重修通道，挤压教学资源。",
                }[j["state"]],
                confidence="high" if j["cur_total"] >= 100 else "medium",
                evidence={
                    "table": "fact_grade",
                    "condition": f"course_id='{j['course_id']}'，按学期聚合",
                    "verify_route": f"{VERIFY_ROUTE}?course={j['course_id']}",
                    "freshness": "按学期成绩实时聚合",
                },
                context={"history": j["history"], "score_band": band,
                         "prereq": prereq, "pass_layers": layers,
                         "failed_students": failed_rows,
                         "failed_total": failed_total},
                suggested_questions=[
                    f"{j['course_name']}的挂科学生先修课成绩如何？",
                    "这门课历学期的未通过率变化？",
                    "和同类课程相比处于什么水平？",
                ],
                data_boundary=DATA_BOUNDARY,
            ))
        return signals

    def _failed_students(self, legacy, course_id, semester,
                         scope_sql, scope_params, cap=200):
        """本学期该课未通过学生行（明细下钻数据源；沿用权限范围过滤）。"""
        rows = dbm.query(legacy, f"""
            SELECT g.student_id, COALESCE(s.name, '') student_name,
                   COALESCE(s.college_id, '') college_id, g.score
            FROM fact_grade g
            LEFT JOIN dim_student s ON s.student_id = g.student_id
            WHERE g.course_id=? AND g.semester_id=?
              AND g.is_pass=0 AND g.score IS NOT NULL
              {scope_sql}
            ORDER BY g.score ASC
        """, tuple([course_id, semester] + list(scope_params)))
        return rows[:cap], len(rows)

    def _score_band(self, legacy, course_id, semester):
        """本学期挂科分数段（样本<5时不输出，避免小样本误导）。"""
        rows = dbm.query(legacy, """
            SELECT CASE WHEN score<40 THEN '0-39' WHEN score<50 THEN '40-49'
                        WHEN score<60 THEN '50-59' ELSE '60+' END band,
                   COUNT(*) n
            FROM fact_grade
            WHERE course_id=? AND semester_id=? AND is_pass=0 AND score IS NOT NULL
            GROUP BY band
        """, (course_id, semester))
        total = sum(r["n"] for r in rows)
        if total < 5:
            return None
        top = max(rows, key=lambda r: r["n"])
        return {"band": top["band"], "pct": round(top["n"] / total * 100, 1),
                "fails": total}

    def _prereq_signal(self, legacy, course_name):
        """同名先修课（Ⅰ/Ⅱ命名对）挂科者先修成绩关联。"""
        if not course_name or ("Ⅱ" not in course_name and "II" not in course_name):
            return None
        prereq_name = course_name.replace("Ⅱ", "Ⅰ").replace("II", "I")
        row = dbm.query_one(legacy, """
            SELECT COUNT(*) fails,
                   SUM(CASE WHEN prev.best < 70 THEN 1 ELSE 0 END) weak
            FROM (SELECT DISTINCT g.student_id FROM fact_grade g
                  JOIN dim_course c ON c.course_id=g.course_id
                  WHERE c.name=? AND g.is_pass=0) f
            LEFT JOIN (SELECT g2.student_id, MAX(g2.score) best FROM fact_grade g2
                  JOIN dim_course c2 ON c2.course_id=g2.course_id
                  WHERE c2.name=? GROUP BY g2.student_id) prev
              ON prev.student_id=f.student_id
        """, (course_name, prereq_name))
        if not row or not row["fails"] or row["weak"] is None:
            return None
        pct = round(row["weak"] / row["fails"] * 100, 1)
        if pct < 50:
            return None
        return f"未通过学生中{pct}%的先修课《{prereq_name}》成绩低于70分（先修链信号）"

    def _positive_signal(self, improving) -> list[Signal]:
        if not improving:
            return []
        names = "、".join(i["course_name"] for i in improving[:3])
        return [Signal(
            signal_id=f"{self.skill_id}:improving",
            skill_id=self.skill_id,
            signal_type="improving",
            severity="low",
            headline=f"持续改善：{names}等课程未通过率连续两学期下降",
            facts={"改善课程": f"{len(improving)}门"},
            entity={"type": "course_set", "id": "improving", "name": "持续改善课程"},
            action={
                "owner": "教务处教研科",
                "what": "总结这些课程的干预经验，作为持续偏高课程复盘的参照",
                "when": "学期复盘时",
                "rationale": "改善案例是成本最低的课程建设知识来源",
            },
            consequence="—",
            confidence="medium",
            evidence={
                "table": "fact_grade",
                "condition": "未通过率连续2学期下降且降幅≥阈值",
                "verify_route": VERIFY_ROUTE,
                "freshness": "按学期成绩实时聚合",
            },
            context={"courses": improving},
            data_boundary=DATA_BOUNDARY,
        )]

    def _unavailable(self, ctx, readiness):
        return SkillResult(
            skill_id=self.skill_id, skill_name=self.name,
            management_question=self.management_question,
            signals=[], summary_stats={}, exclusions=[],
            data_readiness=readiness, config_version=ctx.config_version,
            data_boundary=self.data_boundary, run_at=_now(),
        )


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
