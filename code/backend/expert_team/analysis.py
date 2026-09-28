"""Read-only, reproducible analyses for the independent expert workspace."""
from __future__ import annotations

import json
import re
from collections import defaultdict

from ..api.envelope import ApiError
from ..api.permission_context import v2_student_scope
from .catalog import expert
from . import curriculum

VERSION = "expert-team/1.3"
COMMON_MODULE = re.compile(r"公共|通识|思想政治|体育|军事|大学英语")
# These leaf modules are explicitly under the shared general-education catalogue
# in the 2022 source plans. They must not be treated as professional content.
COMMON_LEAVES = frozenset({"哲学思维、文艺创作和国际语言", "哲学思维与文艺创作", "文艺创作与审美体验",
    "社会素养与创新能力", "工程素养与计算思维", "身心健康与发展", "专业导论课", "专业概论课",
    "新生研讨课", "创新创业课", "学术英语类"})


def original_domains(team, plan_id, course_ids):
    """Use explicit Word hierarchy headings, not semantic model classification."""
    row = team.execute("SELECT content FROM team_document WHERE plan_id=?", (plan_id,)).fetchone()
    domains = defaultdict(set)
    if not row: return domains
    domain = None
    for token in re.split(r"[\r\n\x07]+", row[0]):
        token = token.strip()
        if token in {"通识教育课", "通识必修", "通识选修", "公共实践", "公共实践（必修）"} or re.fullmatch(r"\d{4}级通识选修", token):
            domain = "common"
        elif token in {"专业必修课", "专业选修课", "专业基础课", "专业主干课", "专业实践", "专业实践（必修）", "专业实践（选修）", "第二课堂"}:
            domain = "professional"
        if token in course_ids and domain:
            domains[token].add(domain)
    return domains


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params)]


def scoped_students(v2, user):
    sql, params = v2_student_scope(user["permission_context"], v2, "s")
    return sql or "1=1", params


def plans(v2, user):
    scope, params = scoped_students(v2, user)
    where = "" if scope == "1=1" else f"WHERE p.plan_id IN (SELECT s.plan_id FROM dim_student s WHERE {scope})"
    result = rows(v2, f"""SELECT p.plan_id,p.plan_name,p.major_name,p.grade,p.version,p.source,
        COUNT(pc.plan_course_id) course_rows FROM curriculum_plan p
        LEFT JOIN curriculum_plan_course pc ON pc.plan_id=p.plan_id {where}
        GROUP BY p.plan_id ORDER BY p.major_name,p.plan_name""", params if where else ())
    return [{**p, "training_type": variant(p), "family": family(p)} for p in result]


def assert_plan(v2, user, plan_id):
    plan = next((p for p in plans(v2, user) if p["plan_id"] == plan_id), None)
    if not plan:
        raise ApiError("培养方案不存在或不在当前权限范围", code=404, status_code=404)
    return plan


def courses(v2, team, plan_id):
    raw = rows(team, "SELECT * FROM team_plan_course WHERE plan_id=? ORDER BY source_row", (plan_id,))
    if not raw:
        raw = rows(v2, """SELECT p.course_id,c.name course_name,p.module,p.requirement_type nature,
            p.credits,p.suggested_term term,NULL hours,NULL assessment,NULL source_file
            FROM curriculum_plan_course p LEFT JOIN dim_course c ON c.course_id=p.course_id
            WHERE p.plan_id=? AND p.source='real'""", (plan_id,))
    grouped = {}
    for r in raw:
        cid = r["course_id"]
        if not cid:
            continue
        if cid not in grouped:
            grouped[cid] = {"id": cid, "name": r["course_name"] or cid, "modules": [],
                            "terms": [], "credits": [], "hours": [], "assessments": [],
                            "required": False, "individual_required": False, "required_modules": [],
                            "source": r.get("source_file") or "培养方案课程表"}
        x = grouped[cid]
        for key, value in (("modules", r["module"]), ("terms", r["term"]),
                           ("credits", r["credits"]), ("hours", r["hours"]), ("assessments", r["assessment"])):
            if value is not None and value != "" and value not in x[key]:
                x[key].append(value)
        x["required"] |= (r["nature"] or "") in {"必修", "是"}
        x["individual_required"] |= curriculum.individual_required(r["nature"], r["module"])
        if curriculum.individual_required(r["nature"], r["module"]) and r["module"] not in x["required_modules"]:
            x["required_modules"].append(r["module"] or "")
    domains = original_domains(team, plan_id, set(grouped))
    original = team.execute("SELECT content FROM team_document WHERE plan_id=?", (plan_id,)).fetchone()
    hierarchy = curriculum.original_layers(original[0] if original else "", set(grouped))
    for x in grouped.values():
        x["common"] = domains.get(x["id"]) == {"common"} if x["id"] in domains else (
            bool(x["modules"]) and all(COMMON_MODULE.search(m) or m in COMMON_LEAVES for m in x["modules"]))
        x["classification_basis"] = "原文课程模块层级" if x["id"] in domains else "2022级通识模块名称目录；未明确的保留"
        x["conflict"] = len(x["credits"]) > 1
        curriculum.decorate(x, hierarchy)
    curriculum.apply_original_credit_pools(original[0] if original else "", grouped)
    return grouped


def percent(a, b):
    return round(100 * a / b, 1) if b else None


def variant(plan):
    name = plan["plan_name"]
    return next((t for t in ("预科", "留学生", "全英文", "未来班", "创新班", "实验班") if t in name), "普通")


def family(plan):
    return re.split(r"[（(]", plan.get("major_name") or plan["plan_name"])[0].strip()


def compare_sets(a, b, transfer=False, focus="non_common"):
    full_shared = set(a) & set(b)
    aa, bb = {i for i, c in a.items() if not c["common"]}, {i for i, c in b.items() if not c["common"]}
    shared, union = aa & bb, aa | bb
    required = {i for i, c in b.items() if c.get("mandatory", c["required"])}
    fa, fb = ({i for i, c in side.items() if curriculum.in_focus(c, focus)} for side in (a, b))
    # Transfer ranking is potential curriculum coverage, never actual recognition.
    rank = len(required & set(a)) / len(required) if transfer and required else (
        len(fa & fb) / len(fa | fb) if fa and fb and not transfer else None)
    return {"rank": rank, "shared": len(full_shared), "a_count": len(a), "b_count": len(b),
            "a_coverage": percent(len(full_shared), len(a)), "b_coverage": percent(len(full_shared), len(b)),
            "professional_shared": len(shared), "professional_union": len(union),
            "structural_similarity": percent(len(shared), len(union)) if aa and bb else None,
            "target_required": len(required), "potential_required": len(required & set(a)),
            "required_coverage": percent(len(required & set(a)), len(required)),
            "additional_required": len(required - set(a)),
            "choice_required": sum(c["required"] and not c.get("mandatory", c["required"]) for c in b.values()),
            "focus_shared": len(fa & fb), "focus_union": len(fa | fb),
            "focus_similarity": percent(len(fa & fb), len(fa | fb)) if fa and fb else None}


def nearest(v2, team, user, selected, transfer=False, focus="non_common", eligible_plan_ids=None):
    source = courses(v2, team, selected["plan_id"])
    options, seen = [], set()
    for p in plans(v2, user):
        if eligible_plan_ids is not None and p['plan_id'] not in eligible_plan_ids:
            continue
        if (p["plan_id"] == selected["plan_id"] or p["grade"] != selected["grade"]
                or variant(p) != variant(selected) or family(p) == family(selected) or p["source"] != "real"):
            continue
        values = compare_sets(source, courses(v2, team, p["plan_id"]), transfer, focus)
        if values["rank"] is not None and values["rank"] > 0:
            options.append({**p, **values})
    tie_key=('potential_required' if transfer else 'focus_shared') if eligible_plan_ids is not None else 'professional_shared'
    options.sort(key=lambda p: (-p["rank"], -p[tie_key], p["plan_name"], p["plan_id"]))
    picked = []
    for p in options:
        if family(p) not in seen:
            seen.add(family(p))
            picked.append(p)
        if len(picked) == 3:
            break
    return picked


def table(key, title, columns, data, note=""):
    return {"id": key, "title": title, "columns": [{"key": k, "label": n} for k, n in columns],
            "rows": data, "note": note}


def document(team, v2, plan):
    found = team.execute("SELECT * FROM team_document WHERE plan_id=?", (plan["plan_id"],)).fetchone()
    if found:
        d = dict(found)
        return {"plan": plan["plan_name"], "file": d["file_name"], "hash": d["file_hash"],
                "status": d["status"], "issues": json.loads(d["issues_json"]),
                "sections": json.loads(d["sections_json"]), "basis": "培养方案原文提取，非学校新增认定"}
    goals = rows(v2, "SELECT goal_text text,source_file FROM curriculum_plan_goal WHERE plan_id=?", (plan["plan_id"],))
    reqs = rows(v2, "SELECT requirement_text text,source_file FROM curriculum_graduation_requirement WHERE plan_id=?", (plan["plan_id"],))
    return {"plan": plan["plan_name"], "file": goals[0]["source_file"] if goals else "尚未接入方案原文",
            "status": "pending", "issues": ["尚未完成完整原文提取与归属检查，以下为已有提取内容"],
            "sections": [{"title": "培养目标", "text": "\n".join(r["text"] for r in goals)},
                         {"title": "毕业要求", "text": "\n".join(r["text"] for r in reqs)}],
            "basis": "已有结构化原文；不得据此推断课程支撑关系"}


def course_row(c, side):
    return {"id": c["id"], "name": c["name"], "side": side,
            "domain": c.get("layer_label", "公共课程" if c["common"] else "去除公共课程后的部分"),
            "module": " / ".join(c["modules"]), "term": " / ".join(c["terms"]),
            "credits": " / ".join(str(v) for v in c["credits"]),
            "hours": " / ".join(str(v) for v in c["hours"]),
            "assessment": " / ".join(c["assessments"]),
            "basis": "同代码课程；不等于内容等价或可认定" if side == "共同课程" else "当前方案课程记录",
            "warning": "同代码有不同学分记录，不能直接合计" if c["conflict"] else ""}


def program_analysis(v2, team, user, req, result):
    selected = assert_plan(v2, user, req["plan_id"])
    transfer = req["expert_id"] == "transfer"
    focus = req.get("focus", "non_common")
    candidates = nearest(v2, team, user, selected, transfer, focus, req.get('_eligible_plan_ids'))
    result["focus_label"] = "目标逐门必修" if transfer else curriculum.FOCUSES[focus]
    target_id = req.get("target_plan_id") or (candidates[0]["plan_id"] if candidates else "")
    result["candidates"] = candidates
    result["selected_plan"] = selected
    result["documents"] = [document(team, v2, selected)]
    result["title"] = selected["major_name"] + (" · 培养衔接比较" if transfer else " · 专业比较")
    result["methods"] += [
        "候选限定当前权限内、相同年级和培养类型；同专业方案变体不重复占位，最多三个，不足不补齐。",
        "课程按代码去重；共同课程占双方的比例分别计算。名称相同不自动建立对应或认定关系。",
        "明确层级优先采用课程源表的逐行模块；通识教育、通识选修和公共实践等上级归属由原文补充，无完整原文时采用2022级通识模块名称目录。原文合并表格展开顺序不能覆盖明确模块；混合和未明确的课程单列，不自动认定为专业核心。",
        "转专业候选按目标方案逐门必修课程中与来源方案同代码的比例排序；二选一、限选等组合项另列。候选排序不使用学生成绩，不代表已修、已通过或已获认定。" if transfer else
        f"本次排序口径：{curriculum.FOCUSES[focus]}。比例＝该范围双方共同课程代码数÷并集数；同分按非公共共同课程数、名称、方案ID稳定排序。双方有一方无该层课程时不计算比例，不计算语义相似分。"]
    result["limitations"] += ["课程池包含选修备选项，不能把全部课程学分相加当作毕业要求。",
        "同代码对应不证明教学内容相同；是否重复建设或特色不足，需要结合培养目标、大纲及实践判断。"]
    if transfer:
        result["limitations"] += ["未接入当年度申请与接收规则、名额和未来开课安排；以下是衔接比较对象，不是推荐录取名单。"]
    if target_id:
        target = assert_plan(v2, user, target_id)
        if target["plan_id"] == selected["plan_id"] or target["grade"] != selected["grade"] or variant(target) != variant(selected):
            raise ApiError("请选择另一份相同年级、相同培养类型的方案", code=422, status_code=422)
        a, b = courses(v2, team, selected["plan_id"]), courses(v2, team, target_id)
        values = compare_sets(a, b, transfer, focus)
        values.pop("rank")
        result["comparison"] = {"source": selected, "target": target, **values}
        result["documents"].append(document(team, v2, target))
        result["headline"] = (f"目标方案有{values['target_required']}门逐门必修，其中{values['potential_required']}门与来源方案同代码；另有{values['choice_required']}门组合或选修要求候选，尚不能视作已认定。" if transfer else
                              f"按“{curriculum.FOCUSES[focus]}”比较，与{target['major_name']}共有{values['focus_shared']}门课程；需结合各自定位判断是否存在重复建设。")
        result["tables"].append(table("comparison", "培养方案对照", [("item", "比较内容"), ("a", selected["major_name"]), ("b", target["major_name"])], [
            {"item": "去重课程数", "a": len(a), "b": len(b)},
            {"item": "共同课程数", "a": values["shared"], "b": values["shared"]},
            {"item": "共同课程占本方案比例", "a": f"{values['a_coverage']}%" if a else "不可计算", "b": f"{values['b_coverage']}%" if b else "不可计算"},
            {"item": "非公共基础共同课程", "a": values["professional_shared"], "b": values["professional_shared"]},
            {"item": "本方案独有课程", "a": len(set(a)-set(b)), "b": len(set(b)-set(a))}],
            "门数按课程代码去重；比例分母分别为双方方案去重课程数，不是学生已修课程数。"))
        shared_order = sorted(set(a) & set(b), key=lambda i:(a[i]["common"] or b[i]["common"],i))
        details = [course_row(a[i], "共同课程") for i in shared_order]
        details += [course_row(a[i], "来源方案独有") for i in sorted(set(a) - set(b),key=lambda i:(a[i]["common"],i))]
        details += [course_row(b[i], "目标方案独有") for i in sorted(set(b) - set(a),key=lambda i:(b[i]["common"],i))]
        result["tables"].append(table("courses", "课程对应明细", [("name", "课程"), ("id", "课程代码"), ("side", "归属"),
            ("domain", "范围"), ("module", "模块"), ("credits", "记录学分"), ("term", "建议学期"), ("warning", "说明")], details,
            "共同课程在本表显示来源方案字段；双方课程安排在下表分别列出，不能据此认定可互相替代。"))
        paired = [{"id": i, "name": a[i]["name"], "a_credits": " / ".join(map(str,a[i]["credits"])),
                   "b_credits": " / ".join(map(str,b[i]["credits"])), "a_term": " / ".join(a[i]["terms"]),
                   "b_term": " / ".join(b[i]["terms"])} for i in shared_order]
        result["tables"].append(table("paired", "共同课程双方安排", [("name","课程"),("id","代码"),
            ("a_credits","来源学分"),("b_credits","目标学分"),("a_term","来源学期"),("b_term","目标学期")], paired))
    else:
        result["headline"] = "当前可比范围没有找到具有共同专业课程的其他专业，可以检查范围或手动选择比较对象。"
        result["status"] = "partial"
    if req["scenario"] in {"features", "sequence", "options"}:
        result["headline"] = {"features": "先对照原文中的培养定位，不把结构接近直接解释为特色不足。",
            "sequence": "可以查看课程安排；先修关系未确认前，不能把先后学期等同于先修要求。",
            "options": "先明确需要保留的培养差异，再讨论共同内容建设或课程调整。"}[req["scenario"]]
        result["limitations"].append("本期未将原文之外的课程支撑、先修关系或教学内容等价自动补入正式数据。")
        if req["scenario"] == "features":
            excerpts = []
            for doc in result["documents"]:
                for section in doc["sections"]:
                    if any(k in section["title"] for k in ("培养目标", "主要课程", "知识和能力", "修读要求")):
                        excerpts.append({"plan":doc["plan"], "item":section["title"], "text":section["text"][:240]+("…" if len(section["text"])>240 else ""),
                                         "source":doc["file"], "notice":"；".join(doc["issues"]) or "原文摘录，非达成评价"})
            result["tables"].insert(0, table("positioning", "培养定位原文对照", [("plan","方案"),("item","项目"),("text","原文摘录"),("notice","说明")], excerpts,
                "完整章节可在右侧依据中展开。原文冲突保留提示；定位文字和独有课程仅供讨论，不据此给出特色充分或不足的自动结论。"))
        if req["scenario"] == "sequence":
            schedule = [course_row(c,"所选方案") for c in courses(v2,team,selected["plan_id"]).values() if focus=='all' or not c["common"]]
            schedule.sort(key=lambda r:(r['term'],r['id']))
            result["tables"] = [table("schedule", "所选专业课程安排", [("name","课程"),("id","代码"),("module","模块"),("term","建议学期"),("credits","学分"),("warning","说明")], schedule,
                "春秋、多个学期均按原文保留，不补出先修关系，也不合计备选课程为学期负担。")]
            result["candidates"] = []
        if req["scenario"] == "options" and target_id:
            result["tables"].insert(0, table("options", "可讨论的调整方向", [("option","方向"),("basis","本次数据"),("condition","实施前需明确")], [
                {"option":"保留专业安排，明确定位差异","basis":f"双方共有{values['shared']}门同代码课程，仍有各自独有课程。","condition":"对照培养目标、主要课程与实践安排，不能只看比例。"},
                {"option":"研究共同课程的协同建设","basis":f"去除公共课程后共有{values['professional_shared']}门同代码课程可进一步查看。","condition":"先确认大纲、学时与考核要求是否一致，再讨论协同方式。"},
                {"option":"研究专业特有内容的加强","basis":"以本次课程差异明细和定位原文作为讨论清单。","condition":"缺少需求和资源资料，暂不估算调整成效或建议撤并。"}], "以下是讨论方向，不是经过效果测算的实施方案。"))
    if transfer and req["scenario"] == "conditions":
        result["status"] = "blocked"
        result["headline"] = "尚不能判断本年度转专业申请资格；需要先接入已确认的申请与接收规则。"
        result["missing"] += ["当年度申请条件、接收专业及名额", "考核规则、时间安排及例外规定"]
    if transfer and req["scenario"] in {"recognition", "capacity"}:
        result["missing"] += ["具体学生或申请群体的已确认修读与认定记录", "未来补修安排与接收容量"]
        result["headline"] = "方案差异可供衔接讨论；尚不能把方案共有课程计为学生已获认定的课程。"
        if target_id:
            additional = [course_row(c,"目标逐门必修，来源方案未列出") for cid,c in b.items() if c["mandatory"] and cid not in a]
            result["tables"].insert(0,table("additional", "目标方案新增必修课程清单", [("name","课程"),("id","代码"),("credits","学分"),("term","建议学期")],additional,
                "这只是方案层面的差异，不等于具体学生补修清单；未检查选修、替代或已经完成的认定记录。"))
    if target_id:
        enrich_comparison(v2, team, user, req, result, a, b)


def enrich_comparison(v2, team, user, req, result, a, b):
    if req["expert_id"] == "program":
        if req["scenario"] != "sequence":
            result["tables"].insert(0, table("layers", "不同层级分别比较",
                [("layer","课程层级"),("a","来源课程数"),("b","比较方课程数"),("shared","同层同代码"),
                 ("a_only","仅来源该层列出"),("b_only","仅比较方该层列出")], curriculum.layer_comparison(a,b),
                "每门课程只归入一层；无法明确或跨层级的单列。双方同代码课程可能处于不同层级，不能把各层共同数直接当作全部共同课程数。专业主干不自动等同于认证核心课程。"))
        if req["scenario"] == "features":
            data = curriculum.named_courses(result["documents"][0], a, b) + curriculum.named_courses(result["documents"][1], b, a)
            result["tables"].insert(1, table("named_courses", "原文主要课程与课程表对应",
                [("plan","方案"),("name","原文主要课程"),("id","对应代码"),("comparison","对照情况")], data,
                "只按统一全半角和空白后的完整名称匹配；不合并近似名称或不同语言版本。原文主要课程是培养定位线索，不代表已建立毕业要求支撑关系。"))
            result["tables"].insert(2, table("reading_requirements", "原文修读要求对照",
                [("plan","方案"),("item","项目"),("value","原文要求"),("source","来源")],
                [r for d in result["documents"] for r in curriculum.reading_requirements(d)],
                "直接提取原文，课程池学分不作为毕业学分；原文有冲突时保留提示，不自动修正。"))
    elif req["scenario"] not in {"conditions", "history"}:
        additional = [c for cid,c in b.items() if c["mandatory"] and cid not in a]
        result["tables"].insert(0, table("transition_summary", "衔接内容先分清",
            [("item","比较内容"),("count","课程数"),("credits","目标课程记录学分")], [
                {"item":"目标逐门必修、来源也列出同代码", "count":sum(c["mandatory"] and cid in a for cid,c in b.items()),
                 "credits":curriculum.credit_text(c for cid,c in b.items() if c["mandatory"] and cid in a)},
                {"item":"目标逐门必修、来源未列出同代码", "count":len(additional),"credits":curriculum.credit_text(additional)},
                {"item":"标为必修但属于组合或选修要求候选", "count":sum(c["required"] and not c["mandatory"] for c in b.values()),"credits":"不逐门合计"}],
            "按源表明确的逐门必修统计，二选一、限选及选修模块候选不计入分母；原文模块学分低于所列必修合计的也按组合要求单列。学分冲突或缺失分开显示；不是个人已认定学分或正式补修负担。"))
        result["tables"].insert(1, table("transition_schedule", "新增逐门必修的原定安排",
            [("term","建议学期"),("count","课程数"),("credits","记录学分"),("courses","课程")], curriculum.term_groups(additional),
            "仅按目标培养方案的单一数字学期分组；多学期、春秋、暑期和空缺单列。不推断未来课程供给。"))
        choice = [{**course_row(c,"组合或选修要求候选"),
                   "basis":c.get("requirement_basis", "源模块为组合或选修要求，需确认选课规则")}
                  for c in b.values() if c["required"] and not c["mandatory"]]
        result["tables"].append(table("choice_courses", "需按组合要求确认的课程",
            [("name","课程"),("id","代码"),("module","原文模块"),("term","建议学期"),("basis","单列原因")], choice,
            "不能要求学生修完本清单全部课程；须结合模块选课数量、最低学分和适用规则确认。"))
        if req.get("student_id"):
            from .transfer import student_analysis
            result["missing"] = [m for m in result["missing"] if m != "具体学生或申请群体的已确认修读与认定记录"]
            student_analysis(v2,user,req,result,a,b)


def graduation_analysis(v2, team, user, req, result):
    from . import graduation
    graduation.analyze(v2, team, user, req, result)


def course_analysis(v2, team, user, req, result):
    from . import course_quality
    course_quality.analyze(v2, team, user, req, result)


def analyze(v2, team, user, req):
    ex = expert(req["expert_id"])
    if not ex or req["scenario"] not in {s["id"] for s in ex["scenarios"]}:
        raise ApiError("专家或场景不存在", code=404, status_code=404)
    if req.get("focus", "non_common") not in curriculum.FOCUSES:
        raise ApiError("比较口径不存在", code=422, status_code=422)
    if req.get("student_id"):
        if ex["id"] != "transfer" or req["scenario"] not in {"paths","recognition","capacity"}:
            raise ApiError("该场景不使用个人修读对照", code=422, status_code=422)
        from .transfer import assert_student
        assert_student(v2,user,req["plan_id"],req["student_id"])
    result = {"expert_id":ex["id"],"scenario":req["scenario"],"title":ex["name"],"headline":"",
              "status":"partial","tables":[],"documents":[],"candidates":[],"missing":[],
              "limitations":[],"methods":[],"version":VERSION,
              "scope_label":"全校授权范围" if user["permission_context"]["detailScope"]["type"]=="all" else "本学院授权范围"}
    if ex["id"] in {"program","transfer"}:
        program_analysis(v2,team,user,req,result)
        if ex["id"]=="transfer" and req["scenario"]=="history":
            scope,params=scoped_students(v2,user)
            data=rows(v2,f"""SELECT e.before_major_name before_major,e.after_major_name after_major,COUNT(*) events,
                COUNT(DISTINCT e.student_id) students FROM student_status_event e JOIN dim_student s ON s.student_id=e.student_id
                WHERE e.event_type='转专业' AND e.source='real' AND s.plan_id=? AND {scope}
                GROUP BY e.before_major_name,e.after_major_name ORDER BY events DESC""",(req["plan_id"],*params))
            result["tables"]=[table("transfers","历史转专业记录",[("before_major","原专业"),("after_major","转入专业"),("events","异动记录"),("students","去重学生")],data,
                "按当前绑定所选方案且在权限内的学生回看，非全校历史申请或录取情况。")]
            result["headline"]="这里展示已发生的转专业记录，不据此推断本年度接收政策。"
    elif ex["id"]=="graduation":
        graduation_analysis(v2,team,user,req,result)
    elif ex["id"]=="course":
        course_analysis(v2,team,user,req,result)
    else:
        assert_plan(v2,user,req["plan_id"])
        result.update(status="blocked",headline="尚未接入已确认的年度推免规则，不能据成绩直接判断推免资格或排名。")
        result["missing"]=["适用年度推免办法与名额","排名课程范围、重修及并列处理","专项条件及相关有效记录"]
        if req["scenario"]=="targets": result["missing"].append("目标院校当年度接收要求")
        result["tables"]=[table("requirements","需要明确的条件",[("item","资料"),("purpose","用途")],
            [{"item":x,"purpose":"接入并确认后才能开展该项判断"} for x in result["missing"]])]
        result["limitations"]=["不使用旧库模拟处分或模拟毕业结果，不给出录取概率。"]
    result["data_time"] = v2.execute("SELECT MAX(ingested_at) FROM data_batch").fetchone()[0]
    result["data_time_note"]="此为资料导入时间，不是业务截至时间；具体适用年级和学期以所选对象为准。"
    result["suggestions"]=["解释这次比较的计算口径", "有哪些资料还需要补充？", "帮我整理讨论意见"]
    if ex["id"]=="program": result["suggestions"]=["只看专业基础课", "只看专业主干课", "比较第二个专业", "帮我整理讨论意见"]
    if ex["id"]=="transfer": result["suggestions"]=["查看认定与补修", "比较第二个专业", "解释计算口径", "帮我整理讨论意见"]
    if ex["id"]=="course": result["suggestions"]=["查看问题分析", "比较建设做法", "查看学期变化", "帮我整理讨论意见"]
    if ex["id"]=="graduation": result["suggestions"]=["查看共同课程", "查看资料问题", "比较阶段记录", "帮我整理讨论意见"]
    if len(result["candidates"]) < 2:
        result["suggestions"] = [s for s in result["suggestions"] if s != "比较第二个专业"]
    for doc in result["documents"]:
        result["missing"] += [doc["plan"]+"："+issue for issue in doc["issues"]]
    source_plans = [req["plan_id"]] + ([result["comparison"]["target"]["plan_id"]] if result.get("comparison") else [])
    result["sources"] = rows(team, f"SELECT DISTINCT source_file file,source_hash hash FROM team_plan_course WHERE plan_id IN ({','.join('?' for _ in source_plans)})", source_plans)
    result["sources"].append({"file":"V2 教务分析库 / 当前权限范围", "hash":"",
                             "detail":"真实导入事实与既有计算结果；本次分析不改写源表。"})
    from .conversation import draft_text
    result["draft_text"] = draft_text(result)
    return result
