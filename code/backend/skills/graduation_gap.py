"""Skill 1：毕业缺口核查 graduation-gap（头牌Skill）。

回答：目标毕业届在校生中，谁的毕业路真的被堵了？学校还有没有给他们留出路？

判定逻辑树（经2026-07-21数据走查验证）：
  A 学生分流（仅目标毕业届、在校状态）
    A1 确定受阻：必修 completion_status='failed'
    A2 高度疑似：必修 not_completed/unknown + is_overdue=1
        + 建议学期属临近毕业学期 + 无已通过替代认定 + 无在途成绩记录
    A3 其余不输出
  B 课程聚合 + 出路判定（有路径/无路径/可认定）
  C 行动分级：校级协调 / 学院处理 / 个案核验

数据边界：v2 teaching_lesson 仅含 2023-2024-1 学期，"出路"判定基于
历史开课记录，不代表未来开课承诺。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ..api.permission_context import v2_student_scope
from ..api import db as dbm
from .protocol import (DataRequirement, Signal, Skill, SkillContext,
                       SkillResult)

TARGET_TABLES = [
    DataRequirement("student_plan_course_status", "v2", True,
                    "识别学生必修课程完成证据"),
    DataRequirement("dim_student", "v2", True,
                    "限定目标毕业届在校人群"),
    DataRequirement("teaching_lesson", "v2", True,
                    "判定课程历史供给（有/无路径）"),
    DataRequirement("student_course_substitution", "v2", False,
                    "排除已替代认定的误判", "替代关系缺失时疑似范围会偏大"),
    DataRequirement("grade_attempt", "v2", False,
                    "排除有在途成绩记录的学生", "缺失时疑似范围会偏大"),
]

NEAR_GRAD_DEFAULT = ["7", "8", "3S"]

DATA_BOUNDARY = (
    "教学任务数据仅含2023-2024-1学期，课程出路判定基于历史开课记录，"
    "不代表未来开课承诺；疑似类(A2)未经人工核验不得作为学生未完成结论。"
)

VERIFY_ROUTE = "/admin/curriculum?tab=graduation-readiness"


class GraduationGapSkill(Skill):
    skill_id = "graduation-gap"
    name = "毕业缺口核查"
    management_question = "目标毕业届中，谁的毕业路真的被堵了？学校还有没有给他们留出路？"
    description = ("区分必修明确未通过与待核验证据，匹配课程历史供给，"
                   "输出校级协调/学院处理/个案核验三级行动清单。")
    briefing_tier = "main"
    data_requirements = TARGET_TABLES
    data_boundary = DATA_BOUNDARY

    default_config = {
        "target_grade": 2022,
        "near_grad_terms": NEAR_GRAD_DEFAULT,
        "coordination_min_students": 20,
        "coordination_min_majors": 3,
        "structural_gap_min_students": 50,
        "max_course_signals": 8,
        "rule_version": "growth-v1",
    }
    config_bounds = {
        "target_grade": {"type": "int", "min": 2015, "max": 2035},
        "near_grad_terms": {"type": "list"},
        "coordination_min_students": {"type": "int", "min": 5, "max": 200},
        "coordination_min_majors": {"type": "int", "min": 1, "max": 20},
        "structural_gap_min_students": {"type": "int", "min": 20, "max": 500},
        "max_course_signals": {"type": "int", "min": 3, "max": 20},
    }

    # ---------------------------------------------------------------
    def run(self, ctx: SkillContext) -> SkillResult:
        cfg = ctx.config
        v2 = ctx.v2
        readiness = self.check_readiness(ctx.legacy, v2)
        if not readiness["ready"]:
            return self._unavailable(ctx, readiness)

        scope_sql, scope_params = self._scope(ctx)
        grade = int(cfg["target_grade"])
        near_terms = list(cfg["near_grad_terms"])

        a1 = self._collect_failed(v2, grade, scope_sql, scope_params, cfg)
        a2 = self._collect_suspected(v2, grade, near_terms,
                                     scope_sql, scope_params, cfg)
        courses = self._aggregate_courses(v2, a1, a2, cfg)

        signals: list[Signal] = []
        signals += self._overview_signal(a1, a2, grade)
        signals += self._course_signals(courses, cfg)
        signals += self._verify_signal(a2, courses, grade)

        structural_courses = {c["course_id"] for c in courses if c["level"] == "structural"}
        scattered = {s["student_id"] for s in a2 if s["course_id"] not in structural_courses}
        stats = {
            "target_grade": grade,
            "blocked_students": len({s["student_id"] for s in a1}),
            "blocked_courses": len({s["course_id"] for s in a1}),
            "suspected_students": len({s["student_id"] for s in a2}),
            "structural_courses": len(structural_courses),
            "scattered_suspected_students": len(scattered),
            "coordination_courses": sum(1 for c in courses if c["level"] == "school"),
            "college_courses": sum(1 for c in courses if c["level"] == "college"),
        }
        exclusions = self._exclusions(v2, grade, a1, a2, cfg, scope_sql, scope_params)
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
        frag, params = v2_student_scope(context, ctx.v2, "s")
        return (f" AND {frag}" if frag else ""), params

    def _collect_failed(self, v2, grade, scope_sql, scope_params, cfg):
        return dbm.query(v2, f"""
            SELECT x.student_id, x.course_id, COALESCE(c.name, x.course_id) course_name,
                   x.module, x.suggested_term, s.major_code, s.major_name,
                   s.organization_id, s.class_code
            FROM student_plan_course_status x
            JOIN dim_student s ON s.student_id = x.student_id
            LEFT JOIN dim_course c ON c.course_id = x.course_id
            WHERE x.rule_version=? AND x.requirement_type='必修'
              AND x.completion_status='failed'
              AND s.entry_grade=? AND s.student_status='在校'
              {scope_sql}
        """, tuple([cfg["rule_version"], grade] + scope_params))

    def _collect_suspected(self, v2, grade, near_terms,
                           scope_sql, scope_params, cfg):
        """A2 三条件收敛（走查结论：is_overdue 单独使用会命中11.5万条）。"""
        ph = ",".join("?" * len(near_terms))
        return dbm.query(v2, f"""
            SELECT x.student_id, x.course_id, COALESCE(c.name, x.course_id) course_name,
                   x.module, x.suggested_term, s.major_code, s.major_name,
                   s.organization_id, s.class_code
            FROM student_plan_course_status x
            JOIN dim_student s ON s.student_id = x.student_id
            LEFT JOIN dim_course c ON c.course_id = x.course_id
            WHERE x.rule_version=? AND x.requirement_type='必修'
              AND x.completion_status IN ('not_completed','unknown')
              AND x.is_overdue=1
              AND x.suggested_term IN ({ph})
              AND s.entry_grade=? AND s.student_status='在校'
              AND NOT EXISTS (
                    SELECT 1 FROM student_course_substitution sub
                    WHERE sub.student_id=x.student_id
                      AND sub.original_course_id=x.course_id
                      AND sub.approval_status='通过')
              AND NOT EXISTS (
                    SELECT 1 FROM grade_attempt g
                    WHERE g.student_id=x.student_id
                      AND g.course_id=x.course_id
                      AND g.is_void=0 AND COALESCE(g.is_published,1)=0)
              {scope_sql}
        """, tuple([cfg["rule_version"]] + near_terms + [grade] + scope_params))

    # ---------------------------------------------------------------
    def _aggregate_courses(self, v2, a1, a2, cfg):
        by_course: dict[str, dict] = {}
        for row in a1:
            c = by_course.setdefault(row["course_id"], {
                "course_id": row["course_id"], "course_name": row["course_name"],
                "failed": set(), "suspected": set(), "majors": set(), "orgs": set(),
            })
            c["failed"].add(row["student_id"])
            if row.get("major_code"):
                c["majors"].add(row["major_code"])
            if row.get("organization_id"):
                c["orgs"].add(row["organization_id"])
        for row in a2:
            c = by_course.setdefault(row["course_id"], {
                "course_id": row["course_id"], "course_name": row["course_name"],
                "failed": set(), "suspected": set(), "majors": set(), "orgs": set(),
            })
            c["suspected"].add(row["student_id"])
            if row.get("major_code"):
                c["majors"].add(row["major_code"])
            if row.get("organization_id"):
                c["orgs"].add(row["organization_id"])

        courses = []
        for c in by_course.values():
            supply = dbm.query_one(v2, """
                SELECT COUNT(DISTINCT lesson_id) lessons,
                       COUNT(DISTINCT semester_id) sems,
                       COALESCE(SUM(enrolled),0) enrolled
                FROM teaching_lesson WHERE course_id=?
            """, (c["course_id"],)) or {}
            subs = dbm.scalar(v2, """
                SELECT COUNT(DISTINCT substitution_id) FROM student_course_substitution
                WHERE original_course_id=? AND approval_status='通过'
            """, (c["course_id"],)) or 0
            lessons = supply.get("lessons") or 0
            if subs > 0 and lessons == 0:
                path = "可认定"
            elif lessons > 0:
                path = "有路径"
            else:
                path = "无路径"
            failed_n, suspected_n = len(c["failed"]), len(c["suspected"])
            majors_n = len(c["majors"])
            # 分级（走查修正）：
            # - 协调动作只由硬证据(failed)驱动；疑似(A2)单独走核验通道
            # - 疑似高度集中 = 结构性证据缺口（方案映射/成绩回写问题），集中核验
            if failed_n > 0 and path == "无路径" and (
                    failed_n >= int(cfg["coordination_min_students"])
                    or majors_n >= int(cfg["coordination_min_majors"])):
                level = "school"
            elif failed_n > 0:
                level = "college"
            elif suspected_n >= int(cfg["structural_gap_min_students"]):
                level = "structural"
            else:
                level = "verify"
            courses.append({
                **{k: v for k, v in c.items() if k not in ("failed", "suspected", "majors", "orgs")},
                "failed_n": failed_n, "suspected_n": suspected_n,
                "majors_n": majors_n, "orgs_n": len(c["orgs"]),
                "lessons": lessons, "supply_sems": supply.get("sems") or 0,
                "substitutions": subs, "path": path, "level": level,
                "impact": failed_n * 2 + suspected_n + (majors_n - 1) * 3,
            })
        courses.sort(key=lambda c: (
            {"school": 0, "college": 1, "structural": 2, "verify": 3}[c["level"]],
            -c["impact"]))
        return courses

    # ---------------------------------------------------------------
    def _overview_signal(self, a1, a2, grade) -> list[Signal]:
        students = {s["student_id"] for s in a1}
        if not students:
            return []
        courses = {s["course_id"] for s in a1}
        top = self._top_course_name(a1)
        return [Signal(
            signal_id=f"{self.skill_id}:blocked:{grade}",
            skill_id=self.skill_id,
            signal_type="blocked_overview",
            severity="high",
            headline=(f"{grade}届在校应届生中，{len(students)}人存在必修课明确未通过记录，"
                      f"集中在{len(courses)}门课程，涉及人数最多的课程为{top}"),
            facts={
                "受阻学生": f"{len(students)}人",
                "涉及课程": f"{len(courses)}门",
                "目标届": f"{grade}届在校应届生",
            },
            entity={"type": "student_group", "id": f"grade-{grade}",
                    "name": f"{grade}届在校应届生"},
            action={
                "owner": "教务处",
                "what": "按下方课程级清单分派学院核查，优先处理无开课路径的课程",
                "when": "毕业审核启动前",
                "rationale": "明确未通过属硬证据，可直接进入处理通道，无需先核验",
            },
            consequence="若不提前分派处理，缺口将在毕业审核阶段集中暴露，失去资源调配窗口。",
            confidence="high",
            evidence={
                "table": "student_plan_course_status",
                "condition": "requirement_type='必修' AND completion_status='failed'",
                "verify_route": VERIFY_ROUTE,
                "freshness": "growth-v1 规则实时计算",
            },
            suggested_questions=[
                "这些学生都是谁？按什么顺序处理？",
                "哪些课程没有补修路径？",
                "按学院分布看，哪个学院压力最大？",
            ],
            data_boundary=DATA_BOUNDARY,
        )]

    def _top_course_name(self, a1) -> str:
        counts: dict[str, tuple[str, int]] = {}
        for s in a1:
            name, n = counts.get(s["course_id"], (s["course_name"], 0))
            counts[s["course_id"]] = (name, n + 1)
        if not counts:
            return "—"
        name, n = max(counts.values(), key=lambda x: x[1])
        return f"{name}（{n}人）"

    def _course_signals(self, courses, cfg) -> list[Signal]:
        signals = []
        limit = int(cfg["max_course_signals"])
        actionable = [c for c in courses if c["level"] in ("school", "college", "structural")]
        for c in actionable[:limit]:
            if c["level"] == "structural":
                signals.append(self._structural_signal(c))
            else:
                signals.append(self._gap_signal(c))
        return signals

    def _gap_signal(self, c) -> Signal:
        school = c["level"] == "school"
        parts = []
        if c["failed_n"]:
            parts.append(f"{c['failed_n']}人明确未通过")
        if c["suspected_n"]:
            parts.append(f"另有{c['suspected_n']}人待核验")
        detail = "、".join(parts)
        return Signal(
            signal_id=f"{self.skill_id}:course:{c['course_id']}",
            skill_id=self.skill_id,
            signal_type="course_gap",
            severity="critical" if school else "high",
            headline=(f"{c['course_name']}：{detail}，覆盖{c['majors_n']}个专业，"
                      f"出路判定为「{c['path']}」"
                      + ("——需校级协调补修资源" if school else "")),
            facts={
                "明确未通过": f"{c['failed_n']}人",
                "待核验": f"{c['suspected_n']}人",
                "覆盖专业": f"{c['majors_n']}个",
                "历史教学班": f"{c['lessons']}个",
                "出路判定": c["path"],
            },
            entity={"type": "course", "id": c["course_id"],
                    "name": c["course_name"]},
            action=(
                {
                    "owner": "教务处牵头，相关学院配合",
                    "what": (f"确认{c['course_name']}补修安排：历史无教学班记录，"
                             f"需协调开课或逐案认定"),
                    "when": "毕业审核启动前",
                    "rationale": "无历史开课路径且明确未通过影响面达到校级协调线，学院无法自行消化",
                } if school else {
                    "owner": "学生所在学院",
                    "what": (f"组织{c['course_name']}未通过学生补修或认定，"
                             f"出路判定为「{c['path']}」"
                             + (f"（近学年有{c['lessons']}个教学班记录可循）" if c["lessons"] else "")),
                    "when": "补修报名窗口关闭前",
                    "rationale": "存在明确未通过硬证据，学院可直接引导学生处理",
                }
            ),
            consequence=(
                "若不在毕业审核前协调，学生将失去最后的课程补修机会，"
                "缺口直接转化为延毕风险。" if school else
                "若错过补修窗口，缺口将累积到毕业审核阶段集中处理。"),
            confidence="high",
            evidence={
                "table": "student_plan_course_status + teaching_lesson",
                "condition": f"course_id='{c['course_id']}'",
                "verify_route": f"{VERIFY_ROUTE}&course={c['course_id']}",
                "freshness": "growth-v1 规则实时计算",
            },
            context={
                "path": c["path"], "substitutions": c["substitutions"],
                "supply_semesters": c["supply_sems"],
            },
            suggested_questions=[
                f"{c['course_name']}的受阻学生名单？",
                "这门课历史上开过几个班、规模多大？",
                "如果协调开课，预计需要多少资源？",
            ],
            data_boundary=DATA_BOUNDARY,
        )

    def _structural_signal(self, c) -> Signal:
        return Signal(
            signal_id=f"{self.skill_id}:structural:{c['course_id']}",
            skill_id=self.skill_id,
            signal_type="structural_gap",
            severity="medium",
            headline=(f"{c['course_name']}：{c['suspected_n']}名应届生缺完成证据且高度集中"
                      f"——疑似方案映射或成绩回写问题，应集中核验而非按缺修处理"),
            facts={
                "集中待核验": f"{c['suspected_n']}人",
                "覆盖专业": f"{c['majors_n']}个",
                "历史教学班": f"{c['lessons']}个",
                "替代认定先例": f"{c['substitutions']}条",
            },
            entity={"type": "course", "id": c["course_id"],
                    "name": c["course_name"]},
            action={
                "owner": "教务处学籍科 + 开课单位",
                "what": (f"集中核验{c['course_name']}的完成证据回写与方案课程映射，"
                         f"确认是数据问题还是真实缺口"),
                "when": "毕业审核名单形成前",
                "rationale": "缺口高度集中在一门课通常是结构性数据问题，逐生处理会误伤并掩盖根因",
            },
            consequence="若按缺修处理将误伤大量学生；若属映射问题不修复，后续每届都会重复出现。",
            confidence="medium",
            evidence={
                "table": "student_plan_course_status",
                "condition": f"course_id='{c['course_id']}' AND is_overdue=1",
                "verify_route": f"{VERIFY_ROUTE}&course={c['course_id']}",
                "freshness": "growth-v1 规则实时计算",
            },
            context={"path": c["path"], "supply_semesters": c["supply_sems"]},
            suggested_questions=[
                f"{c['course_name']}缺证据学生的共同特征是什么？",
                "这门课的成绩是如何回写的？",
            ],
            data_boundary=DATA_BOUNDARY,
        )

    def _verify_signal(self, a2, courses, grade) -> list[Signal]:
        """分散型待核验（不属于结构性缺口的A2学生）：低优先级，学院抽查。"""
        structural_ids = {c["course_id"] for c in courses if c["level"] == "structural"}
        scattered = [s for s in a2 if s["course_id"] not in structural_ids]
        students = {s["student_id"] for s in scattered}
        if not students:
            return []
        courses_n = len({s["course_id"] for s in scattered})
        return [Signal(
            signal_id=f"{self.skill_id}:verify:{grade}",
            skill_id=self.skill_id,
            signal_type="verification_pool",
            severity="low",
            headline=(f"另有{len(students)}名{grade}届学生存在分散的必修完成证据缺口"
                      f"（涉及{courses_n}门课程），由各学院抽查核验"),
            facts={
                "分散待核验学生": f"{len(students)}人",
                "涉及课程": f"{courses_n}门",
            },
            entity={"type": "student_group", "id": f"verify-{grade}",
                    "name": f"{grade}届分散待核验学生"},
            action={
                "owner": "各学院教学秘书",
                "what": "抽查核验选课记录、免修认定、课程替代与成绩回写状态",
                "when": "毕业审核名单形成前",
                "rationale": "分散缺口多为个体数据问题，抽查确认后即可排除",
            },
            consequence="若遗漏真实个体缺口，会在毕业审核时暴露；但优先级低于结构性核验。",
            confidence="medium",
            evidence={
                "table": "student_plan_course_status",
                "condition": "is_overdue=1 且建议学期临近毕业 且无替代认定/在途成绩",
                "verify_route": VERIFY_ROUTE,
                "freshness": "growth-v1 规则实时计算",
            },
            suggested_questions=[
                "待核验学生按学院怎么分布？",
            ],
            data_boundary=DATA_BOUNDARY,
        )]

    def _exclusions(self, v2, grade, a1, a2, cfg, scope_sql, scope_params):
        total = dbm.scalar(v2, f"""
            SELECT COUNT(*) FROM dim_student s
            WHERE s.entry_grade=? AND s.student_status='在校' {scope_sql}
        """, tuple([grade] + scope_params)) or 0
        clean = total - len({s["student_id"] for s in a1}) - len({s["student_id"] for s in a2})
        return [{
            "what": f"{grade}届其余{max(clean, 0)}名在校生",
            "why": "必修课程无明确未通过记录，且不属于临近毕业证据缺口，维持常规推进",
        }]

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
