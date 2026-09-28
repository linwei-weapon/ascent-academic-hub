"""Small, explicit conversation commands backed by recalculation, never an LLM."""
import re
from ..api.envelope import ApiError


def resolve_change(result, message):
    text = re.sub(r"[。！？?!]+$", "", message.strip())
    text = re.sub(r"^请", "", text)
    focuses = {"只看专业基础课": "foundation", "只看专业主干课": "main", "只看专业实践": "practice",
               "只看逐门必修": "required", "查看全部课程": "all", "去除公共课程再比较": "non_common"}
    if text in focuses:
        if result["expert_id"] != "program":
            raise ApiError("转专业仍按目标逐门必修比较；课程分层比较请使用专业建设专家", code=422, status_code=422)
        return {"focus": focuses[text]}
    ordinal = re.fullmatch(r"(?:比较|看看|换成)(?:第)?([一二三123])个专业", text)
    if ordinal:
        index = {"一": 0, "二": 1, "三": 2, "1": 0, "2": 1, "3": 2}[ordinal[1]]
        candidates = result.get("candidates", [])
        if index >= len(candidates):
            raise ApiError("当前范围没有这个比较对象，请从已有候选中选择", code=422, status_code=422)
        return {"target_plan_id": candidates[index]["plan_id"]}
    for candidate in result.get("candidates", []):
        for name in {candidate["major_name"], candidate["plan_name"]}:
            if text in {f"和{name}比较", f"与{name}比较", f"换成{name}", f"比较{name}"}:
                return {"target_plan_id": candidate["plan_id"]}
    scenes = {"program": {"查看课程重复": "overlap", "查看特色支撑": "features", "查看调整方向": "options"},
              "transfer": {"查看认定与补修": "recognition", "查看接收影响": "capacity", "查看衔接专业": "paths"},
              "course": {"查看问题分析":"diagnosis","比较建设做法":"options","查看学期变化":"outcomes","查看目标与考核":"alignment"},
              "graduation": {"查看共同课程":"bottlenecks","查看资料问题":"records","比较阶段记录":"changes","查看条件说明":"conditions"}}
    scenario = scenes.get(result["expert_id"], {}).get(text)
    return {"scenario": scenario} if scenario else None


def draft_text(result):
    if result["status"] == "blocked":
        recommendation = "现有资料不足以形成该项认定意见，先明确以下条件。"
    elif result["expert_id"] == "program":
        recommendation = "建议先对共同的专业课程逐项比较培养目标、大纲与考核要求，再讨论协同建设或保留差异；不直接依据重合比例作出撤并判断。"
    elif result["expert_id"] == "transfer":
        recommendation = "建议先确认目标方案适用性及课程认定规则，再逐项讨论修读衔接和安排；资格、名额和开课条件另行明确。"
    elif result["expert_id"] == "course":
        recommendation = "建议结合本次课程表现，先了解具体学习困难和教学考核安排，再选择建设做法；不直接把成绩差异归因于教师或建设措施。"
    elif result["expert_id"] == "graduation":
        recommendation = "建议分别处理课程问题、资料问题和方案适用问题；以学校确认的毕业及学位条件组织审核，不把准备情况当作正式资格结论。"
    else:
        recommendation = "建议围绕本次已知情况组织讨论，资料不足的事项暂不作认定。"
    facts = []
    for t in result.get("tables", []):
        if t["id"] in {"layers", "transition_summary", "student_transition", "course_current", "course_options", "readiness", "graduation_changes"}:
            facts.extend("；".join(f"{c['label']}：{row.get(c['key']) if row.get(c['key']) is not None else '—'}" for c in t["columns"]) for row in t["rows"][:12])
    boundaries = list(dict.fromkeys(result["missing"] + result["limitations"]))
    return (f"{result['title']} · 讨论意见稿\n\n一、初步意见\n{recommendation}\n\n"
            f"二、本次情况\n{result['headline']}\n" + "\n".join(facts) +
            "\n\n三、需进一步明确\n" + "\n".join(f"{i+1}. {text}" for i, text in enumerate(boundaries)) +
            f"\n\n四、分析范围与来源\n{result['scope_label']}；口径：{result.get('focus_label','本场景口径')}；版本：{result['version']}。"
            f"\n资料导入：{result.get('data_time') or '未提供'}（不是业务截至时间）。"
            "\n" + "；".join(d["file"] for d in result.get("documents", [])) +
            "\n\n本稿供修改讨论，不是审批、课程认定或办理结果。")
