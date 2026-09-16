"""Student-level curriculum transition, reusing the existing effective-grade rule."""
from ..api.envelope import ApiError
from .curriculum import credit_text, term_groups


def students(v2, user, plan_id, query=""):
    from .analysis import assert_plan, scoped_students, rows
    assert_plan(v2, user, plan_id)
    scope, params = scoped_students(v2, user)
    return rows(v2, f"""SELECT s.student_id,s.display_name,s.entry_grade,s.major_name
        FROM dim_student s WHERE s.plan_id=? AND {scope} AND s.student_status='在校'
        AND s.source IN ('real','real_legacy')
        AND (?='' OR instr(s.student_id,?)>0 OR instr(COALESCE(s.display_name,''),?)>0)
        ORDER BY s.student_id LIMIT 20""", (plan_id, *params, query, query, query))


def assert_student(v2, user, plan_id, student_id):
    from .analysis import assert_plan, scoped_students
    assert_plan(v2, user, plan_id)
    scope, params = scoped_students(v2, user)
    row = v2.execute(f"""SELECT s.student_id,s.display_name,s.entry_grade,s.major_name
        FROM dim_student s WHERE s.student_id=? AND s.plan_id=? AND {scope}
        AND s.student_status='在校' AND s.source IN ('real','real_legacy')""", (student_id, plan_id, *params)).fetchone()
    if not row:
        raise ApiError("学生不存在、不属于所选方案或不在当前权限范围", code=404, status_code=404)
    return dict(row)


def student_analysis(v2, user, req, result, source, target):
    from .analysis import table
    from ..etl.v2_grade_loader import RULE_VERSION
    student = assert_student(v2, user, req["plan_id"], req["student_id"])
    result["student"] = student
    source_plan = result["comparison"]["source"]
    if (str(student["entry_grade"]) != str(source_plan["grade"])
            or (student["major_name"] or "").strip() != source_plan["major_name"].strip()):
        result["status"] = "blocked"
        result["headline"] = "学生年级或专业与来源方案不一致，需要先确认适用方案，暂不计算个人衔接情况。"
        result["missing"].append("学生与培养方案的适用关系")
        return
    effective = {r["course_id"]: dict(r) for r in v2.execute("""SELECT r.course_id,r.is_pass,r.rule_version,
        r.calculated_at,g.attempt_id,g.semester_id,g.credits,g.score
        FROM student_course_result r JOIN grade_attempt g ON g.attempt_id=r.effective_attempt_id
        AND g.student_id=r.student_id AND g.course_id=r.course_id
        WHERE r.student_id=? AND r.rule_version=? AND g.is_published=1 AND g.is_void=0
        AND g.source IN ('real','real_legacy') AND r.is_pass IS g.is_pass""", (student["student_id"], RULE_VERSION))}
    approved = {r[0] for r in v2.execute("""SELECT original_course_id FROM student_course_substitution
        WHERE student_id=? AND approval_status='通过' AND workflow_status='流程已结束'
        AND source IN ('real','real_legacy')""", (student["student_id"],))}
    labels = {"passed": "已有同代码通过记录", "recognition": "已有替代记录，适用待确认",
              "failed": "有效结果未通过", "unknown": "有效结果待明确", "missing": "尚无有效修读结果"}
    groups = {key: [] for key in labels}
    details = []
    for cid, course in sorted(target.items()):
        if not course["mandatory"]: continue
        outcome = effective.get(cid, {})
        state = "passed" if outcome.get("is_pass") == 1 else "recognition" if cid in approved else (
            "failed" if outcome.get("is_pass") == 0 else "unknown" if outcome else "missing")
        groups[state].append(course)
        details.append({"id": cid, "name": course["name"], "state": labels[state],
                        "target_credits": credit_text([course]), "record_credits": outcome.get("credits"),
                        "semester": outcome.get("semester_id"), "term": " / ".join(course["terms"]),
                        "source": outcome.get("attempt_id") or ("已通过且流程结束的替代记录" if cid in approved else "未找到有效记录"),
                        "rule": outcome.get("rule_version") or "—"})
    result["tables"].insert(0, table("student_transition", "学生修读与目标必修对照",
        [("state", "情况"), ("count", "课程数"), ("credits", "对应目标方案学分")],
        [{"state": labels[key], "count": len(items), "credits": credit_text(items)} for key, items in groups.items()],
        "学分是所对应目标课程的记录学分，不是已认定学分。已有同代码通过记录和替代记录仍需确认在目标方案中的适用性。"))
    result["tables"].insert(1, table("student_courses", "逐门查看修读依据",
        [("name", "课程"), ("id", "代码"), ("state", "修读情况"), ("target_credits", "目标学分"),
         ("record_credits", "有效成绩记录学分"), ("semester", "成绩学期"), ("term", "目标建议学期"), ("source", "来源记录")], details))
    pending = groups["failed"] + groups["unknown"] + groups["missing"]
    result["tables"].insert(2, table("student_schedule", "待进一步安排的课程",
        [("term", "目标方案建议学期"), ("count", "课程数"), ("credits", "目标方案学分"), ("courses", "课程")], term_groups(pending),
        "这是尚未找到通过或已结束替代记录的目标逐门必修课程；不是正式补修通知。多学期、春秋或空缺安排单列，不推断未来开课、学期负担或延毕。"))
    result["headline"] = (f"{student['display_name'] or student['student_id']}的有效记录中，"
        f"{len(groups['passed'])}门已通过课程与目标逐门必修同代码；"
        f"另有{len(groups['recognition'])}门涉及替代记录，{len(pending)}门需要进一步明确修读安排。")
    result["methods"].append(f"个人修读复用 {RULE_VERSION} 有效结果：已发布、未作废，通过优先最高分，否则最新记录；再次检查关联成绩来源。只读当前授权学生。")
    result["limitations"].append("本次不是学校课程认定：同代码通过、原有替代关系以及成绩学分均不能自动转为目标方案认可学分。没有结果不等于从未修读。")
    result["methods"].append(
        "个人来源：V2 student_course_result、grade_attempt、student_course_substitution；所选学生的有效记录。")
