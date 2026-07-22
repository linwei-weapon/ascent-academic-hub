"""专家问策编排（产品终稿 R4）：每个 Skill 专家一个对话入口。

设计约束：
- 问策是纯对话：不产生任何办理动作，答案的终点是建议+依据+核查入口。
- 材料边界：专家只回答本领域问题；越界问题拒答并指路（目标专家或专题路由）。
- 证据引用：[n] 编号与 signal_id 一一映射，前端点击开查证窗口（R2）。
- 数字防线复用 chat.py：查证类不调LLM；LLM输出全部经数字字面量校验。
"""
from __future__ import annotations

from . import chat as decision_chat
from .registry import get_skill, list_skills

# ---------------------------------------------------------------------------
# 专家档案：示例问法（≥6类）与领域关键词（越界识别用）
# ---------------------------------------------------------------------------

EXPERT_PROFILES: dict[str, dict] = {
    "graduation-gap": {
        "icon": "🎓",
        "title": "毕业与学位专家",
        "example_questions": [
            "本届有多少学生存在毕业缺口？",
            "体质测试为什么会影响毕业？",
            "哪个课程的毕业缺口最严重？",
            "这些缺口学生应该在什么时限前处理？",
            "不处理这些缺口会有什么后果？",
            "毕业缺口数据和上学期相比有什么变化？",
        ],
        "boundary": "只回答毕业、学位、学分缺口相关问题；课程教学、预警干预、师资排课问题请找对应专家。",
    },
    "course-quality": {
        "icon": "📚",
        "title": "课程质量专家",
        "example_questions": [
            "哪些课程通过率异常？",
            "通过率低的课程有什么共同特征？",
            "某门课为什么通过率这么低？",
            "哪些课程适合优先整改？",
            "课程质量问题和去年相比如何？",
            "通过率数据是哪个学期的？",
        ],
        "boundary": "只回答课程通过率、课程教学质量问题；毕业缺口、预警干预、师资问题请找对应专家。",
    },
    "alert-priority": {
        "icon": "⚠️",
        "title": "预警干预专家",
        "example_questions": [
            "当前有多少学生处于预警状态？",
            "哪些预警滞留时间最长？",
            "本周应该优先干预哪些学生？",
            "预警为什么会产生滞留？",
            "预警规则和上学期相比有变化吗？",
            "严重预警的学生分布在哪些班级？",
        ],
        "boundary": "只回答学业预警、干预队列相关问题；毕业、课程、师资问题请找对应专家。",
    },
    "faculty-structure": {
        "icon": "👥",
        "title": "师资保障专家",
        "example_questions": [
            "哪些课程只有一名教师承担？",
            "单人授课规模过大的课程有哪些？",
            "师资结构存在什么风险？",
            "某门课为什么算师资风险？",
            "教师负荷分布是否均衡？",
            "排课数据覆盖哪个学期？",
        ],
        "boundary": "只回答师资结构、授课承担、排课保障问题；毕业、课程质量、预警问题请找对应专家。",
    },
}


def expert_list(briefing: dict) -> list[dict]:
    """专家库首页数据：档案 + 今日最关键一条 + 信号计数（取自当前用户简报）。"""
    sections = {s.get("skill_id"): s for s in briefing.get("skill_sections", [])}
    items = []
    for skill in list_skills():
        profile = EXPERT_PROFILES.get(skill.skill_id, {})
        sec = sections.get(skill.skill_id, {})
        signals = sec.get("signals", [])
        top = None
        # 今日最关键：优先取简报优先区中本专家的第一条，否则取分区第一条
        for card in briefing.get("priority_items", []):
            if card.get("skill_id") == skill.skill_id:
                top = card
                break
        if top is None and signals:
            top = signals[0]
        items.append({
            "skill_id": skill.skill_id,
            "name": skill.name,
            "title": profile.get("title") or skill.name,
            "icon": profile.get("icon", "🧭"),
            "management_question": skill.management_question,
            "description": skill.description,
            "boundary": profile.get("boundary", ""),
            "example_questions": profile.get("example_questions", []),
            "data_readiness": sec.get("data_readiness", {"ready": True}),
            "signal_count": len(signals),
            "top_signal": ({
                "signal_id": top.get("signal_id"),
                "severity": top.get("severity"),
                "headline": top.get("headline"),
            } if top else None),
        })
    return items


# ---------------------------------------------------------------------------
# 越界识别：问题明显属于其他专家领域时拒答并指路
# ---------------------------------------------------------------------------

def detect_out_of_domain(message: str, skill_id: str) -> str | None:
    """返回应指向的 skill_id；未越界返回 None。

    规则：本专家关键词零命中，且另一专家关键词有命中。
    通用问题（无任何关键词）不视为越界——专家可在本领域内作答。
    """
    text = message or ""
    own_hits = sum(1 for kw in decision_chat._SKILL_KEYWORDS.get(skill_id, ())
                   if kw in text)
    if own_hits:
        return None
    best, best_hits = None, 0
    for other, keywords in decision_chat._SKILL_KEYWORDS.items():
        if other == skill_id:
            continue
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_hits:
            best, best_hits = other, hits
    return best if best_hits >= 1 else None


def refusal_payload(message: str, from_skill: str, to_skill: str) -> dict:
    target_skill = get_skill(to_skill)
    target_name = target_skill.name if target_skill else to_skill
    profile = EXPERT_PROFILES.get(to_skill, {})
    return {
        "intent": "out_of_domain",
        "intent_label": "越界拒答",
        "text": (f"这个问题属于「{target_name}」的领域，我作为"
                 f"「{EXPERT_PROFILES.get(from_skill, {}).get('title', from_skill)}」"
                 "不便越界作答，以免给出没有数据支撑的判断。"),
        "blocks": [],
        "evidence_refs": [],
        "suggested_questions": (profile.get("example_questions") or [])[:3],
        "redirect": {"skill_id": to_skill, "name": target_name},
        "boundary": EXPERT_PROFILES.get(from_skill, {}).get("boundary", ""),
        "llm_status": "not_used",
    }


# ---------------------------------------------------------------------------
# 证据引用：[n] 编号 → signal_id 映射
# ---------------------------------------------------------------------------

def build_evidence_refs(cited: list[dict]) -> list[dict]:
    refs = []
    for i, card in enumerate(cited, 1):
        refs.append({
            "n": i,
            "signal_id": card.get("signal_id"),
            "severity": card.get("severity"),
            "headline": card.get("headline"),
            "facts": card.get("facts") or {},
            "drillable_facts": card.get("drillable_facts") or [],
            "entity": (card.get("entity") or {}).get("name")
            if isinstance(card.get("entity"), dict) else card.get("entity"),
        })
    return refs


# ---------------------------------------------------------------------------
# 编排：单专家问答
# ---------------------------------------------------------------------------

def ask(message: str, skill_id: str, signal_id: str,
        history: list[dict], briefing: dict, cfg: dict) -> dict:
    """专家问策主流程：越界识别 → 领域材料裁剪 → 意图路由 → 回答 → 证据编号。"""
    redirect = detect_out_of_domain(message, skill_id)
    if redirect:
        return refusal_payload(message, skill_id, redirect)

    # 材料裁剪：只保留本专家的信号，防止跨领域引用
    scoped = dict(briefing)
    scoped["priority_items"] = [c for c in briefing.get("priority_items", [])
                                if c.get("skill_id") == skill_id]
    scoped["skill_sections"] = [s for s in briefing.get("skill_sections", [])
                                if s.get("skill_id") == skill_id]
    scoped["watch_items"] = [c for c in briefing.get("watch_items", [])
                             if c.get("skill_id") == skill_id]
    scoped["positive_developments"] = [
        c for c in briefing.get("positive_developments", [])
        if c.get("skill_id") == skill_id]

    routed = decision_chat.route(message, signal_id, scoped)
    result = decision_chat.answer(message, history, routed, scoped, cfg)

    # 越界兜底：领域内没有匹配信号且问题仍像查证时，诚实说明而非硬答
    cited = routed["cited"]
    result["intent"] = routed["intent"]
    result["intent_label"] = decision_chat.INTENT_LABELS.get(routed["intent"], "")
    result["evidence_refs"] = build_evidence_refs(cited)
    result["suggested_questions"] = result.pop("followups", [])[:3]
    if not result["suggested_questions"]:
        result["suggested_questions"] = \
            (EXPERT_PROFILES.get(skill_id, {}).get("example_questions") or [])[:3]
    result["boundary"] = EXPERT_PROFILES.get(skill_id, {}).get("boundary", "")
    result["redirect"] = None
    return result
