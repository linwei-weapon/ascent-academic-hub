"""Versioned curriculum facts. No semantic matching or invented prerequisites."""
import re
import unicodedata
from collections import defaultdict

LAYERS = {"common": "公共课程", "foundation": "专业基础", "main": "专业主干",
          "practice": "专业实践", "elective": "专业选修", "professional": "专业其他",
          "mixed": "跨层级记录", "unknown": "层级待明确"}
FOCUSES = {"non_common": "去除公共课程", "foundation": "专业基础", "main": "专业主干",
           "practice": "专业实践", "required": "逐门必修", "all": "全部课程"}
HEADINGS = {
    "通识教育课": "common", "通识必修": "common", "通识选修": "common",
    "公共实践": "common", "公共实践（必修）": "common",
    "专业基础课": "foundation", "专业基础": "foundation", "专业基础选修": "foundation",
    "专业基础选修课": "foundation", "专业主干课": "main", "专业主干": "main",
    "专业主干选修": "main", "专业核心课": "main",
    "专业实践": "practice", "专业实践（必修）": "practice", "专业实践（选修）": "practice",
    "专业选修课": "elective", "专业选修": "elective", "专业应用选修": "elective",
    "专业拓展选修": "elective", "专业必修课": "professional", "第二课堂": "unknown",
}
CHOICE = re.compile(r"[二三四五六七八九十两\d]+选[一二三四五六七八九十\d]+|任选|限选|限定选修|必选课程")


def original_layers(content, course_ids):
    found, current = defaultdict(set), None
    for token in re.split(r"[\r\n\x07]+", content or ""):
        token = token.strip()
        if token in HEADINGS:
            current = HEADINGS[token]
        elif re.fullmatch(r"\d{4}级通识选修", token):
            current = "common"
        if current and token in course_ids:
            found[token].add(current)
    return found


def decorate(course, hierarchy):
    explicit = {HEADINGS[m] for m in course["modules"] if m in HEADINGS}
    # The source-table row has an explicit course-to-module relationship. Word
    # merged cells/flattened reading order can carry a heading past its section,
    # so they must not override an explicit module on the course's own row.
    levels = hierarchy.get(course["id"], set())
    specific = explicit - {"professional", "unknown"}
    if len(specific) == 1:
        layer = next(iter(specific))
        course["common"] = layer == "common"
        course["classification_basis"] = "课程源表明确模块"
    elif len(specific) > 1:
        layer = "mixed"
        course["common"] = False
    elif course["common"]:
        layer = "common"
    elif "common" in levels:
        layer = "mixed"
    else:
        layer = "professional" if (levels or explicit) - {"unknown"} else "unknown"
    course["layer"] = layer
    course["layer_label"] = LAYERS[layer]
    course["choice"] = any(CHOICE.search(m) for m in course["modules"])
    # Each row explicitly says whether it is individually required. A course in
    # an elective/choice pool alone is never counted as an individual obligation.
    course["mandatory"] = course.get("individual_required", False)


def individual_required(nature, module):
    return nature in {"必修", "是"} and not CHOICE.search(module or "") and "选修" not in (module or "")


def apply_original_credit_pools(content, courses):
    """Do not turn a module's alternative required rows into individual debts.

    Only accept an exact module block whose course codes match its source rows.
    A smaller original credit requirement proves that all listed required rows
    cannot be demanded together; it does not determine which course to choose.
    """
    module_ids = defaultdict(set)
    for cid, course in courses.items():
        for module in course["modules"]: module_ids[module].add(cid)
    blocks = defaultdict(list)
    active, seen = None, set()
    tokens = [token.strip() for token in re.split(r"[\r\n\x07]+", content or "") if token.strip()]
    for index, token in enumerate(tokens):
        # A row's nature may itself be named "必修", also a module label.
        # Only a heading immediately followed by one of its course codes opens
        # a module block; a nature cell followed by credits cannot reset it.
        if token in module_ids and index + 1 < len(tokens) and tokens[index + 1] in module_ids[token]:
            active, seen = token, set()
        elif token in courses:
            if active and token in module_ids[active]: seen.add(token)
            else: active, seen = None, set()
        elif match := re.fullmatch(r"要求学分\s*[:：]\s*(\d+(?:\.\d+)?)", token):
            if active and seen == module_ids[active]:
                blocks[active].append(float(match[1]))
            active, seen = None, set()
    pools = {}
    for module, values in blocks.items():
        if len(set(values)) != 1: continue
        required = [courses[cid] for cid in module_ids[module]
                    if module in courses[cid].get("required_modules", [])]
        total = credit_summary(required)
        if len(required) > 1 and total["credits"] is not None and total["credits"] > values[0]:
            pools[module] = (f"原文模块要求 {values[0]:g} 学分，所列必修合计 {total['credits']:g} 学分；"
                             "不能逐门累加，选课规则待确认")
    for course in courses.values():
        required_modules = set(course.get("required_modules", []))
        if required_modules and required_modules <= pools.keys():
            course["mandatory"] = False
            course["choice"] = True
            course["requirement_basis"] = "；".join(pools[m] for m in sorted(required_modules))


def in_focus(course, focus):
    if focus == "all": return True
    if focus == "non_common": return not course["common"]
    if focus == "required": return course.get("mandatory", course["required"])
    return course.get("layer") == focus


def credit_summary(courses):
    items = list(courses)
    known = [c["credits"][0] for c in items if len(c["credits"]) == 1 and c["credits"][0] >= 0]
    missing = len(items) - len(known)
    return {"count": len(items), "known_credits": round(sum(known), 2), "unresolved": missing,
            "credits": round(sum(known), 2) if not missing else None}


def credit_text(items):
    value = credit_summary(items)
    if value["unresolved"]:
        return f"已知 {value['known_credits']:g}；另 {value['unresolved']} 门待确认"
    return f"{value['credits']:g}"


def layer_comparison(a, b):
    data = []
    for key, label in LAYERS.items():
        left = {cid for cid, c in a.items() if c["layer"] == key}
        right = {cid for cid, c in b.items() if c["layer"] == key}
        data.append({"layer": label, "a": len(left), "b": len(right), "shared": len(left & right),
                     "a_only": len(left - right), "b_only": len(right - left)})
    return data


def reading_requirements(doc):
    text = "\n".join(s["text"] for s in doc["sections"] if "修读要求" in s["title"])
    output = []
    for label in ("最低总学分", "必修课", "选修课", "单独设置的实践教学环节"):
        values = set(re.findall(re.escape(label) + r"\s*([0-9]+(?:\.[0-9]+)?)", text))
        output.append({"plan": doc["plan"], "item": label,
                       "value": next(iter(values)) + " 学分" if len(values) == 1 else "原文未明确提取或存在多个值",
                       "source": doc["file"]})
    return output


def named_courses(doc, own, other):
    def normalize(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
    names = defaultdict(list)
    for cid, c in own.items(): names[normalize(c["name"])].append(cid)
    result, seen = [], set()
    for section in doc["sections"]:
        if "主要课程" not in section["title"]: continue
        for name in re.split(r"[、，,；;\r\n]+", section["text"]):
            name = re.sub(r"等[。.]?$|[。.]$", "", name.strip())
            if not name or name in seen: continue
            seen.add(name)
            matches = names.get(normalize(name), [])
            cid = matches[0] if len(matches) == 1 else None
            result.append({"plan": doc["plan"], "name": name, "id": cid or "未唯一对应",
                           "comparison": ("对方方案也列有同代码课程" if cid in other else "本方案有记录，对方未列出同代码课程")
                           if cid else "需确认名称或版本，不自动按近似名称匹配",
                           "source": doc["file"]})
    return result


def term_groups(items):
    grouped = defaultdict(list)
    for c in items:
        terms = c["terms"]
        # Multiple terms and seasonal offerings remain unresolved alternatives;
        # do not assign them to the earliest semester or duplicate their credits.
        key = terms[0] if len(terms) == 1 and re.fullmatch(r"[1-8]", terms[0]) else "安排待明确"
        grouped[key].append(c)
    return [{"term": "第 " + key + " 学期" if key.isdigit() else key,
             "count": len(cs), "credits": credit_text(cs), "courses": "、".join(c["name"] for c in cs)}
            for key, cs in sorted(grouped.items())]
