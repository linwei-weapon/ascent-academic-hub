"""Skill 4：预警优先级 alert-priority。

回答：5577条活动预警里，管理者本周有限的注意力应该先给哪几名学生？

判定逻辑树（纯排序与分流，不改写预警本身的定级）：
  输入: fact_alert(is_active=1) × alert_event(认领状态) × fact_grade(本学期必修未通过/GPA环比)
  评分: level_weight(严重40/警告20/提醒10)
      + fail_weight(本学期必修未通过×fail_per, 封顶fail_cap)
      + trend_weight(GPA环比下降>gpa_drop_mild +trend_mild分, >gpa_drop_severe +trend_severe分)
      + stall_weight(预警生成>stall_days天仍未认领 +stall分)
  输出: Top N 本周优先队列 + 滞留信号(严重级>stale_days天未认领)

边界：本Skill只做注意力排序与滞留提示，不新增/关闭预警，处理动作仍在预警工作台完成。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..api.deps import student_data_scope
from ..api import db as dbm
from .protocol import (DataRequirement, Signal, Skill, SkillContext,
                       SkillResult)

DATA_BOUNDARY = (
    "优先级评分仅用于注意力排序，不改变预警定级与处理流程；"
    "GPA环比基于相邻两个有成绩学期，转专业/休复学学生的环比可能失真。"
)

VERIFY_ROUTE = "/admin/alert"

LEVEL_LABEL = {"严重": "严重", "警告": "警告", "提醒": "提醒"}


class AlertPrioritySkill(Skill):
    skill_id = "alert-priority"
    name = "预警优先级"
    management_question = "数千条活动预警中，本周有限的干预注意力应该先给哪几名学生？"
    description = ("对活动预警按 等级×学业证据×趋势×滞留时长 综合评分，"
                   "输出本周优先介入队列与滞留预警提示；只做排序分流，不改动预警本身。")
    briefing_tier = "main"
    data_requirements = [
        DataRequirement("fact_alert", "legacy", True, "活动预警等级与类型"),
        DataRequirement("alert_event", "legacy", True, "预警认领状态与滞留时长"),
        DataRequirement("fact_grade", "legacy", True, "本学期必修未通过与GPA环比"),
        DataRequirement("dim_student", "legacy", True, "学生院系归属与权限过滤"),
    ]
    data_boundary = DATA_BOUNDARY

    default_config = {
        "level_weight": {"严重": 40, "警告": 20, "提醒": 10},
        "fail_per_required": 8,
        "fail_cap": 24,
        "gpa_drop_mild": 0.3,
        "gpa_drop_severe": 0.5,
        "trend_mild": 10,
        "trend_severe": 15,
        "stall_days": 14,
        "stall_score": 10,
        "stale_days": 30,
        "top_n": 10,
    }
    config_bounds = {
        "fail_per_required": {"type": "int", "min": 1, "max": 30},
        "fail_cap": {"type": "int", "min": 8, "max": 60},
        "gpa_drop_mild": {"type": "float", "min": 0.1, "max": 1.5},
        "gpa_drop_severe": {"type": "float", "min": 0.2, "max": 2.5},
        "trend_mild": {"type": "int", "min": 0, "max": 40},
        "trend_severe": {"type": "int", "min": 0, "max": 60},
        "stall_days": {"type": "int", "min": 3, "max": 90},
        "stall_score": {"type": "int", "min": 0, "max": 40},
        "stale_days": {"type": "int", "min": 7, "max": 180},
        "top_n": {"type": "int", "min": 5, "max": 30},
    }

    # ---------------------------------------------------------------
    def run(self, ctx: SkillContext) -> SkillResult:
        cfg = ctx.config
        legacy = ctx.legacy
        readiness = self.check_readiness(legacy, ctx.v2)
        if not readiness["ready"]:
            return self._unavailable(ctx, readiness)

        scope_sql, scope_params = self._scope(ctx)
        alerts = self._active_alerts(legacy, scope_sql, scope_params)
        if not alerts:
            return self._empty(ctx, readiness)

        fails = self._required_fails(legacy, ctx.semester, scope_sql, scope_params)
        gpa_drop = self._gpa_drops(legacy, scope_sql, scope_params)
        scored = self._score(alerts, fails, gpa_drop, cfg)
        stale = [s for s in scored
                 if s["level"] == "严重" and s["status"] == "new"
                 and s["days_open"] >= int(cfg["stale_days"])]

        signals: list[Signal] = []
        signals += self._queue_signal(scored, cfg, len(alerts))
        signals += self._stale_signal(stale, cfg)

        stats = {
            "active_alerts": len(alerts),
            "by_level": {
                lv: sum(1 for a in alerts if a["level"] == lv)
                for lv in ("严重", "警告", "提醒")
            },
            "queue_size": min(int(cfg["top_n"]), len(scored)),
            "stale_critical": len(stale),
            "unclaimed": sum(1 for a in alerts if a["status"] == "new"),
        }
        exclusions = [{
            "what": f"{len(scored) - stats['queue_size']}条活动预警",
            "why": "综合评分未进入本周优先队列，仍在预警工作台按常规流程处理",
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

    def _active_alerts(self, legacy, scope_sql, scope_params):
        return dbm.query(legacy, f"""
            SELECT a.alert_id, a.student_id, a.level, a.type, a.trigger_detail,
                   a.created_at, s.college_id, s.name student_name,
                   COALESCE(e.workflow_status, 'new') status,
                   COALESCE(e.first_detected_at, a.created_at) opened_at,
                   CAST(julianday('now','localtime')
                        - julianday(COALESCE(e.first_detected_at, a.created_at))
                        AS INTEGER) days_open
            FROM fact_alert a
            JOIN dim_student s ON s.student_id = a.student_id
            LEFT JOIN alert_event e ON e.alert_id = a.alert_id
            WHERE a.is_active = 1
              {scope_sql}
        """, tuple(scope_params))

    def _required_fails(self, legacy, semester, scope_sql, scope_params):
        rows = dbm.query(legacy, f"""
            SELECT g.student_id, COUNT(DISTINCT g.course_id) fails
            FROM fact_grade g
            JOIN dim_student s ON s.student_id = g.student_id
            WHERE g.semester_id = ? AND g.is_pass = 0 AND g.is_required = 1
              {scope_sql}
            GROUP BY g.student_id
        """, tuple([semester] + scope_params))
        return {r["student_id"]: r["fails"] for r in rows}

    def _gpa_drops(self, legacy, scope_sql, scope_params):
        """相邻两个有成绩学期的学分加权GPA差（仅对有活动预警的学生计算）。"""
        rows = dbm.query(legacy, f"""
            WITH alerted AS (
                SELECT DISTINCT a.student_id FROM fact_alert a
                JOIN dim_student s ON s.student_id = a.student_id
                WHERE a.is_active = 1 {scope_sql}
            ),
            sem_gpa AS (
                SELECT g.student_id, g.semester_id,
                       SUM(g.gpa * g.credits) / SUM(g.credits) gpa
                FROM fact_grade g
                JOIN alerted t ON t.student_id = g.student_id
                WHERE g.gpa IS NOT NULL AND g.credits > 0
                GROUP BY g.student_id, g.semester_id
            ),
            ranked AS (
                SELECT student_id, semester_id, gpa,
                       ROW_NUMBER() OVER (PARTITION BY student_id
                                          ORDER BY semester_id DESC) rn
                FROM sem_gpa
            )
            SELECT cur.student_id, cur.gpa - prev.gpa drop_amt
            FROM ranked cur JOIN ranked prev
              ON prev.student_id = cur.student_id AND prev.rn = 2
            WHERE cur.rn = 1
        """, tuple(scope_params))
        return {r["student_id"]: r["drop_amt"] for r in rows}

    def _score(self, alerts, fails, gpa_drop, cfg):
        lw = cfg["level_weight"]
        scored = []
        for a in alerts:
            score = float(lw.get(a["level"], 5))
            reasons = [f"{a['level']}预警"]
            f = fails.get(a["student_id"], 0)
            if f:
                pts = min(f * int(cfg["fail_per_required"]), int(cfg["fail_cap"]))
                score += pts
                reasons.append(f"本学期{f}门必修未通过")
            drop = gpa_drop.get(a["student_id"])
            if drop is not None:
                if drop <= -float(cfg["gpa_drop_severe"]):
                    score += int(cfg["trend_severe"])
                    reasons.append(f"GPA环比下降{abs(drop):.2f}")
                elif drop <= -float(cfg["gpa_drop_mild"]):
                    score += int(cfg["trend_mild"])
                    reasons.append(f"GPA环比下降{abs(drop):.2f}")
            if a["status"] == "new" and a["days_open"] >= int(cfg["stall_days"]):
                score += int(cfg["stall_score"])
                reasons.append(f"生成{a['days_open']}天未认领")
            scored.append({**a, "score": score, "reasons": reasons})
        scored.sort(key=lambda s: (-s["score"], -s["days_open"]))
        return scored

    # ---------------------------------------------------------------
    def _queue_signal(self, scored, cfg, total_active) -> list[Signal]:
        top_n = int(cfg["top_n"])
        queue = scored[:top_n]
        if not queue:
            return []
        critical_n = sum(1 for q in queue if q["level"] == "严重")
        top = queue[0]
        return [Signal(
            signal_id=f"{self.skill_id}:queue",
            skill_id=self.skill_id,
            signal_type="priority_queue",
            severity="high" if critical_n else "medium",
            headline=(f"本周优先介入队列{len(queue)}人（其中严重级{critical_n}人）："
                      f"首位为{top['student_name'] or top['student_id']}（{top['college_id']}），"
                      f"{'；'.join(top['reasons'])}"),
            facts={
                "队列人数": f"{len(queue)}人",
                "其中严重级": f"{critical_n}人",
                "全校活动预警": f"{total_active}条",
            },
            entity={"type": "student_queue", "id": "priority-queue",
                    "name": "本周优先介入队列"},
            action={
                "owner": "学工部统筹 → 学院辅导员",
                "what": "按队列顺序安排本周谈话/介入，优先处理同时带学业证据的严重级预警",
                "when": "本周内",
                "rationale": "评分融合了预警等级、必修未通过、GPA环比与滞留时长，队列头部是干预边际收益最高的对象",
            },
            consequence="若按接收顺序而非优先级处理，有限的人力会先消耗在低风险预警上，高风险学生的干预窗口被错过。",
            confidence="high",
            evidence={
                "table": "fact_alert × alert_event × fact_grade",
                "condition": "is_active=1，按综合评分降序",
                "verify_route": VERIFY_ROUTE,
                "freshness": "预警实时；成绩截至当前学期",
            },
            context={
                "queue": [{
                    "rank": i + 1,
                    "student_id": q["student_id"],
                    "student_name": q["student_name"],
                    "college_id": q["college_id"],
                    "level": q["level"],
                    "score": q["score"],
                    "reasons": q["reasons"],
                    "trigger_detail": q["trigger_detail"],
                    "days_open": q["days_open"],
                } for i, q in enumerate(queue)],
            },
            suggested_questions=[
                "队列首位学生的详细情况？",
                "严重级预警集中在哪些学院？",
                "评分权重是怎么定的？",
            ],
            data_boundary=DATA_BOUNDARY,
        )]

    def _stale_signal(self, stale, cfg) -> list[Signal]:
        if not stale:
            return []
        stale_days = int(cfg["stale_days"])
        worst = max(stale, key=lambda s: s["days_open"])
        by_college: dict[str, int] = {}
        for s in stale:
            by_college[s["college_id"]] = by_college.get(s["college_id"], 0) + 1
        top_college = max(by_college.items(), key=lambda kv: kv[1])
        return [Signal(
            signal_id=f"{self.skill_id}:stale",
            skill_id=self.skill_id,
            signal_type="stale_critical",
            severity="medium",
            headline=(f"{len(stale)}条严重级预警滞留超过{stale_days}天无人认领，"
                      f"最长达{worst['days_open']}天；集中在{top_college[0]}（{top_college[1]}条）"),
            facts={
                "滞留严重预警": f"{len(stale)}条",
                "最长滞留": f"{worst['days_open']}天",
                "集中院系": f"{top_college[0]}（{top_college[1]}条）",
            },
            entity={"type": "alert_set", "id": "stale-critical",
                    "name": "滞留严重预警"},
            action={
                "owner": "学工部预警督办",
                "what": f"对滞留超{stale_days}天的严重级预警逐条督办认领，必要时升级到处级协调",
                "when": "3个工作日内",
                "rationale": "严重级预警的设计前提是快速介入，长期未认领意味着干预机制在这些个案上已失效",
            },
            consequence="滞留每延长一周，学生状态进一步恶化的概率上升，且后续追责时无法说明处置过程。",
            confidence="high",
            evidence={
                "table": "fact_alert × alert_event",
                "condition": f"level='严重' AND workflow_status='new' AND 滞留≥{stale_days}天",
                "verify_route": f"{VERIFY_ROUTE}?tab=monitor",
                "freshness": "实时",
            },
            context={"stale": [{
                "student_id": s["student_id"], "student_name": s["student_name"],
                "college_id": s["college_id"], "days_open": s["days_open"],
                "trigger_detail": s["trigger_detail"],
            } for s in stale[:10]]},
            suggested_questions=[
                "滞留预警为什么没人认领？",
                "哪些学院的认领率最低？",
            ],
            data_boundary=DATA_BOUNDARY,
        )]

    # ---------------------------------------------------------------
    def _empty(self, ctx, readiness):
        return SkillResult(
            skill_id=self.skill_id, skill_name=self.name,
            management_question=self.management_question,
            signals=[], summary_stats={"active_alerts": 0},
            exclusions=[], data_readiness=readiness,
            config_version=ctx.config_version,
            data_boundary=self.data_boundary, run_at=_now(),
        )

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
