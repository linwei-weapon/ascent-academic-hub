"""Skill 3：师资结构核查 faculty-structure（降级版，topic 层级）。

回答：在仅有单学期教学快照的现实下，哪些课程存在"单人依赖"的排课保险缺口？

走查结论（决定了本Skill的降级形态）：
  - dim_staff 有职称(1406人)但无年龄/司龄 → 年龄梯队维度整体挂起，明示排除
  - teaching_lesson 仅覆盖 2023-2024-1 单学期 → 只能做结构快照，不能做趋势
  - 因此本Skill只回答"保险型"问题：单人依赖课程清单 + 职称数据完整性

判定逻辑树：
  输入: agg_course_offering × agg_course_team（快照学期自动取最新）
  单人依赖: teacher_count=1 且 enrolled ≥ high_enrolled → high（校级保险缺口）
            teacher_count=1 且 mid_enrolled ≤ enrolled < high_enrolled → medium
            enrolled < mid_enrolled → 正常（小班单教师属常态，明示排除）
  数据质量: 快照内 unknown_title 占比 ≥ title_gap_ratio → 提示职称数据治理

边界：不对教师个体做任何评价；不预测离职/退休风险；快照学期必须显著声明。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..api import db as dbm
from .protocol import (DataRequirement, Signal, Skill, SkillContext,
                       SkillResult)

DATA_BOUNDARY = (
    "本Skill基于单学期教学快照（非实时数据），只反映该学期的排课结构；"
    "年龄与梯队维度因无可靠数据源整体挂起；不对教师个体作任何评价或风险预测。"
)

VERIFY_ROUTE = "/admin/operation/teacher-load"


class FacultyStructureSkill(Skill):
    skill_id = "faculty-structure"
    name = "师资结构核查"
    management_question = "哪些课程的全部教学压在一名教师身上，形成排课保险缺口？"
    description = ("基于单学期教学快照识别单人依赖课程（按修读规模分级），"
                   "并核查职称数据完整性；年龄梯队维度因数据缺失挂起并明示。")
    briefing_tier = "topic"
    data_requirements = [
        DataRequirement("agg_course_offering", "v2", True, "课程开班规模与教师数"),
        DataRequirement("agg_course_team", "v2", True, "课程教学团队职称结构"),
        DataRequirement("dim_course", "v2", True, "课程名称与开课单位"),
        DataRequirement("dim_staff", "v2", False, "职称数据完整性核查"),
    ]
    data_boundary = DATA_BOUNDARY

    default_config = {
        "high_enrolled": 300,
        "mid_enrolled": 30,
        "title_gap_ratio": 0.30,
        "max_course_signals": 5,
    }
    config_bounds = {
        "high_enrolled": {"type": "int", "min": 100, "max": 2000},
        "mid_enrolled": {"type": "int", "min": 10, "max": 300},
        "title_gap_ratio": {"type": "float", "min": 0.05, "max": 0.90},
        "max_course_signals": {"type": "int", "min": 1, "max": 20},
    }

    # ---------------------------------------------------------------
    def run(self, ctx: SkillContext) -> SkillResult:
        cfg = ctx.config
        readiness = self.check_readiness(ctx.legacy, ctx.v2)
        if not readiness["ready"]:
            return self._unavailable(ctx, readiness)

        semester = self._snapshot_semester(ctx.v2)
        if not semester:
            readiness["ready"] = False
            readiness["items"].append({
                "table": "agg_course_offering", "database": "v2",
                "available": False, "purpose": "快照学期为空",
            })
            return self._unavailable(ctx, readiness)

        scope_sql, scope_params = self._scope(ctx)
        courses = self._collect(ctx.v2, semester, scope_sql, scope_params, cfg)
        title_gap = self._title_gap(ctx.v2, semester, cfg)

        high = [c for c in courses if c["level"] == "high"]
        mid = [c for c in courses if c["level"] == "mid"]

        signals: list[Signal] = []
        signals += self._overview_signal(high, mid, semester, cfg)
        signals += self._course_signals(high, cfg, semester)
        signals += self._title_gap_signal(title_gap, semester)

        stats = {
            "snapshot_semester": semester,
            "courses_in_snapshot": len(courses) + self._excluded_count(ctx.v2, semester, cfg),
            "single_teacher_high": len(high),
            "single_teacher_mid": len(mid),
            "unknown_title_ratio": title_gap["ratio"] if title_gap else None,
        }
        exclusions = [
            {
                "what": "年龄梯队、司龄结构、退休风险维度",
                "why": "dim_staff 无年龄/入职时间数据，该维度整体挂起，不做推测性输出",
            },
            {
                "what": "小班单教师课程（修读<%d人）" % int(cfg["mid_enrolled"]),
                "why": "小班由一名教师承担属正常教学形态，不构成保险缺口",
            },
        ]
        return SkillResult(
            skill_id=self.skill_id, skill_name=self.name,
            management_question=self.management_question,
            signals=signals, summary_stats=stats, exclusions=exclusions,
            data_readiness=readiness, config_version=ctx.config_version,
            data_boundary=self.data_boundary, run_at=_now(),
        )

    # ---------------------------------------------------------------
    def _snapshot_semester(self, v2):
        row = dbm.query_one(v2, "SELECT MAX(semester_id) sem FROM agg_course_offering")
        return row["sem"] if row else None

    def _scope(self, ctx: SkillContext):
        """课程按开课单位过滤；非 college 受限身份不适用本Skill（topic 层级，宽容处理）。"""
        context = ctx.user.get("permission_context") or {}
        detail = context.get("detailScope") or {}
        scope_type = detail.get("type")
        if not context or scope_type == "all":
            return "", []
        if scope_type != "college":
            return "", []
        source_ids = detail.get("sourceScopeIds") or []
        if not source_ids:
            return "", []
        role_id = context.get("activeRole")
        placeholders = ",".join("?" * len(source_ids))
        rows = dbm.query(ctx.v2, f"""
            SELECT DISTINCT organization_id FROM access_scope_mapping
            WHERE role_id=? AND mapping_status='mapped' AND scope_type='college'
              AND source_scope_id IN ({placeholders}) AND organization_id IS NOT NULL
        """, tuple([role_id] + source_ids))
        orgs = [r["organization_id"] for r in rows]
        if not orgs:
            return "", []
        return f" AND c.organization_id IN ({','.join('?' * len(orgs))})", orgs

    def _collect(self, v2, semester, scope_sql, scope_params, cfg):
        rows = dbm.query(v2, f"""
            SELECT o.course_id, COALESCE(c.name, o.course_id) course_name,
                   c.organization_id, o.lesson_count, o.teacher_count, o.enrolled,
                   t.professor_count, t.associate_professor_count,
                   t.lecturer_count, t.unknown_title_count
            FROM agg_course_offering o
            LEFT JOIN agg_course_team t
              ON t.semester_id=o.semester_id AND t.course_id=o.course_id
            LEFT JOIN dim_course c ON c.course_id=o.course_id
            WHERE o.semester_id=? AND o.teacher_count=1
              AND o.enrolled >= ?
              {scope_sql}
            ORDER BY o.enrolled DESC
        """, tuple([semester, int(cfg["mid_enrolled"])] + scope_params))
        for r in rows:
            r["level"] = "high" if r["enrolled"] >= int(cfg["high_enrolled"]) else "mid"
        return rows

    def _excluded_count(self, v2, semester, cfg):
        row = dbm.query_one(v2, """
            SELECT COUNT(*) n FROM agg_course_offering
            WHERE semester_id=? AND teacher_count=1 AND enrolled < ?
        """, (semester, int(cfg["mid_enrolled"])))
        return row["n"] if row else 0

    def _title_gap(self, v2, semester, cfg):
        row = dbm.query_one(v2, """
            SELECT SUM(teacher_count) total, SUM(unknown_title_count) unknown
            FROM agg_course_team WHERE semester_id=?
        """, (semester,))
        if not row or not row["total"]:
            return None
        ratio = (row["unknown"] or 0) / row["total"]
        return {"ratio": round(ratio, 3), "unknown": row["unknown"] or 0,
                "total": row["total"],
                "triggered": ratio >= float(cfg["title_gap_ratio"])}

    # ---------------------------------------------------------------
    def _overview_signal(self, high, mid, semester, cfg) -> list[Signal]:
        if not high and not mid:
            return []
        sev = "medium" if high else "low"
        top = high[0] if high else mid[0]
        high_n = int(cfg["high_enrolled"])
        return [Signal(
            signal_id=f"{self.skill_id}:overview:{semester}",
            skill_id=self.skill_id,
            signal_type="single_teacher_overview",
            severity=sev,
            headline=(f"{semester}学期快照：{len(high)}门大规模课程（≥{high_n}人）"
                      f"由单一教师承担，最典型为{top['course_name']}（{top['enrolled']}人）"
                      + (f"；另有{len(mid)}门中等规模课程同构" if mid else "")),
            facts={
                "大规模单人课程": f"{len(high)}门",
                "中等规模单人课程": f"{len(mid)}门",
                "快照学期": semester,
            },
            entity={"type": "course_set", "id": f"single-teacher-{semester}",
                    "name": "单人依赖课程清单"},
            action={
                "owner": "教务处排课科 + 相关开课单位",
                "what": "为大规模单人课程配置备份主讲或助教梯队，纳入下一轮排课检查项",
                "when": "下一轮排课前",
                "rationale": "单一教师承担大规模课程时，任何突发缺勤都无备份方案，属排课保险缺口",
            },
            consequence="若教师突发缺勤，大规模课程无备份主讲，影响面为整门课全部学生。",
            confidence="medium",
            evidence={
                "table": "agg_course_offering × agg_course_team",
                "condition": f"semester_id='{semester}' AND teacher_count=1",
                "verify_route": VERIFY_ROUTE,
                "freshness": f"{semester}学期快照（非实时）",
            },
            suggested_questions=[
                "这些课程分别属于哪些开课单位？",
                "上次排课时这些课程是否有备份教师？",
            ],
            # 专题工作区判别矩阵明细（不进信号指纹）
            context={
                "high_enrolled_line": high_n,
                "high_courses": [
                    {"course_id": c["course_id"], "course_name": c["course_name"],
                     "enrolled": c["enrolled"], "lesson_count": c["lesson_count"],
                     "organization_id": c["organization_id"] or ""}
                    for c in high
                ],
                "mid_courses": [
                    {"course_id": c["course_id"], "course_name": c["course_name"],
                     "enrolled": c["enrolled"], "lesson_count": c["lesson_count"],
                     "organization_id": c["organization_id"] or ""}
                    for c in mid
                ],
            },
            data_boundary=DATA_BOUNDARY,
        )]

    def _course_signals(self, high, cfg, semester) -> list[Signal]:
        signals = []
        for c in high[: int(cfg["max_course_signals"])]:
            team = []
            if c["professor_count"]:
                team.append(f"教授{c['professor_count']}")
            if c["associate_professor_count"]:
                team.append(f"副教授{c['associate_professor_count']}")
            if c["lecturer_count"]:
                team.append(f"讲师{c['lecturer_count']}")
            if c["unknown_title_count"]:
                team.append(f"职称未登记{c['unknown_title_count']}")
            team_text = "、".join(team) if team else "职称信息缺失"
            signals.append(Signal(
                signal_id=f"{self.skill_id}:course:{c['course_id']}:{semester}",
                skill_id=self.skill_id,
                signal_type="single_teacher_course",
                severity="medium",
                headline=(f"{c['course_name']}：{c['enrolled']}人选课、{c['lesson_count']}个教学班，"
                          f"仅1名教师承担（{team_text}）"),
                facts={
                    "修读人数": f"{c['enrolled']}人",
                    "教学班数": f"{c['lesson_count']}个",
                    "承担教师": "1人",
                    "团队职称结构": team_text,
                    "开课单位": c["organization_id"] or "未登记",
                },
                entity={"type": "course", "id": c["course_id"],
                        "name": c["course_name"]},
                action={
                    "owner": c["organization_id"] or "开课单位",
                    "what": f"为{c['course_name']}明确备份主讲人选或配置助教",
                    "when": "下一轮排课前",
                    "rationale": "修读规模越大，单一教师缺勤的影响面越大，备份成本相对影响面极低",
                },
                consequence="教师突发缺勤时整门课停摆，影响全部修读学生。",
                confidence="medium",
                evidence={
                    "table": "agg_course_offering",
                    "condition": f"course_id='{c['course_id']}' AND semester_id='{semester}'",
                    "verify_route": VERIFY_ROUTE,
                    "freshness": f"{semester}学期快照（非实时）",
                },
                data_boundary=DATA_BOUNDARY,
            ))
        return signals

    def _title_gap_signal(self, title_gap, semester) -> list[Signal]:
        if not title_gap or not title_gap["triggered"]:
            return []
        pct = round(title_gap["ratio"] * 100, 1)
        return [Signal(
            signal_id=f"{self.skill_id}:title-gap:{semester}",
            skill_id=self.skill_id,
            signal_type="title_data_gap",
            severity="low",
            headline=(f"{semester}学期教学团队中{pct}%的教师职称未登记"
                      f"（{title_gap['unknown']}/{title_gap['total']}），"
                      f"职称结构分析可信度受限"),
            facts={
                "职称未登记占比": f"{pct}%",
                "涉及人次": f"{title_gap['unknown']}/{title_gap['total']}",
            },
            entity={"type": "data_quality", "id": "staff-title",
                    "name": "职称数据完整性"},
            action={
                "owner": "人事处 + 教务处数据管理员",
                "what": "补齐教学任务中教师的职称字段，或确认未登记是否为外聘教师",
                "when": "下次职称结构分析前",
                "rationale": "职称缺失超过阈值时，任何基于职称的结构分析都不应采信",
            },
            consequence="职称数据长期不补齐，师资结构类分析将持续失真。",
            confidence="high",
            evidence={
                "table": "agg_course_team",
                "condition": f"semester_id='{semester}'，unknown_title_count/teacher_count",
                "verify_route": VERIFY_ROUTE,
                "freshness": f"{semester}学期快照",
            },
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
