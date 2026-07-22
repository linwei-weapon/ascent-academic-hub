"""对话编排层（阶段4.3）：意图路由五类 + 归因三明治 + 禁区防线。

设计约束（来自已确认计划）：
- 查证类问题由LLM按"结构骨架+标准范例"主笔（管理参谋语气），
  数字字面量校验不变；LLM未启用/失败回退同骨架的代码模板。
- 归因类问题强制"事实层/假设层(待验证)/行动层"三明治；假设层是L5条件性开放，
  必须标注待验证并给出验证路径。
- 假设测算类问题：当前版本无测算Skill，诚实说明能力边界并引导到可查证入口。
- 所有LLM输出经数字字面量校验（允许集=材料+对话历史），失败回退模板版。
- 数字防线先于流式：文本先缓冲、校验通过才下发（已读出的错误数字无法撤回）。
"""
from __future__ import annotations

import json
import re

from .llm_client import KIND_NOT_CONFIGURED, LLMError, chat_completion
from .llm_config import llm_ready
from .narrative import _parse_json, extract_numbers

INTENT_VERIFY = "verify"        # 查证：LLM按骨架范例主笔，数字校验；回退同骨架模板
INTENT_SIMULATE = "simulate"    # 假设测算：能力边界声明（测算Skill属后续阶段）
INTENT_COMPARE = "compare"      # 比较：LLM组织已引用信号的事实
INTENT_ATTRIBUTE = "attribute"  # 归因：三明治强制
INTENT_OPEN = "open"            # 开放：LLM在材料边界内作答

INTENT_LABELS = {
    INTENT_VERIFY: "查证", INTENT_SIMULATE: "假设测算", INTENT_COMPARE: "比较",
    INTENT_ATTRIBUTE: "归因", INTENT_OPEN: "开放",
}

CHAT_SYSTEM_PROMPT = """你是高校教学管理决策助手，基于给定的决策简报事实材料与对话历史回答管理者问题。

铁律（违反任何一条，输出将被系统拒绝）：
1. 你输出的每一个数字都必须逐字来自给定材料或对话历史；不得计算、估算、换算、四舍五入或创造任何数字。
2. 只允许四级表达：复述材料事实 / 组织信息结构 / 解释规则含义 / 关联引用材料中给出的信号ID。
   归因类问题可提出假设，但每个假设必须标注为待验证并给出具体验证路径。
3. 禁区：不评价具体教师个人；不推断学生心理或品行；不编造预测，仅可解释后端返回的统计分布或模型输出；不输出人事或处分建议；不引用材料与对话之外的任何事实。
4. 不得改变事实的严重度、责任归属、时限与代价表述的含义。
5. 只输出指定JSON，不得输出任何额外文字、注释或Markdown。"""

# ---------------------------------------------------------------------------
# 意图路由（确定性规则，可单测）
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, re.Pattern]] = [
    (INTENT_ATTRIBUTE, re.compile(r"为什么|为何|啥原因|原因|归因|导致|造成|怎么会")),
    (INTENT_SIMULATE, re.compile(r"如果|假设|测算|模拟|会不会|能否|若新增|增加.{0,4}(班|人|教师)|扩招")),
    (INTENT_COMPARE, re.compile(r"哪个更|哪些更|对比|比较|相比|差别|差异|孰轻孰重|先处理哪|优先.{0,4}哪")),
    (INTENT_VERIFY, re.compile(r"多少|哪些|名单|都有谁|是谁|有没有|是否有|现状|明细|排名|第几|前几|是不是|能否查")),
]


def classify_intent(message: str) -> str:
    text = (message or "").strip()
    for intent, pattern in _RULES:
        if pattern.search(text):
            return intent
    return INTENT_OPEN


# ---------------------------------------------------------------------------
# 信号匹配：按实体名/headline/Skill关键词给当前信号打分
# ---------------------------------------------------------------------------

_SKILL_KEYWORDS = {
    "graduation-gap": ("毕业", "学位", "结业", "肄业", "学分"),
    "course-quality": ("课程", "通过率", "未通过", "挂科", "质量"),
    "alert-priority": ("预警", "干预", "滞留", "介入"),
    "faculty-structure": ("师资", "教师", "排课", "开课", "教学任务"),
}


def match_signals(message: str, signals: list[dict], limit: int = 3) -> list[dict]:
    text = message or ""
    scored: list[tuple[int, str, dict]] = []
    for card in signals:
        score = 0
        name = ((card.get("entity") or {}).get("name")) or ""
        if name and name in text:
            score += 10
        for n in (4, 3, 2):
            for i in range(0, max(0, len(name) - n + 1)):
                if name[i:i + n] and name[i:i + n] in text:
                    score += 1
        for token in re.findall(r"[一-鿿A-Za-z0-9]{4,}", card.get("headline") or ""):
            if token in text:
                score += 2
        for kw in _SKILL_KEYWORDS.get(card.get("skill_id") or "", ()):
            if kw in text:
                score += 3
        if score > 0:
            scored.append((score, card.get("signal_id") or "", card))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _s, _i, c in scored[:limit]]


def all_signal_cards(briefing: dict) -> list[dict]:
    cards: list[dict] = list(briefing.get("priority_items", []))
    seen = {c.get("signal_id") for c in cards}
    for sec in briefing.get("skill_sections", []):
        for c in sec.get("signals", []):
            if c.get("signal_id") not in seen:
                seen.add(c.get("signal_id"))
                cards.append(c)
    for group in ("watch_items", "positive_developments"):
        for c in briefing.get(group, []):
            if c.get("signal_id") not in seen:
                seen.add(c.get("signal_id"))
                cards.append(c)
    return cards


def _facts_line(card: dict) -> str:
    return "；".join(f"{k} {v}" for k, v in (card.get("facts") or {}).items())


def _signal_payload(card: dict) -> dict:
    return {
        "signal_id": card.get("signal_id"),
        "skill_id": card.get("skill_id"),
        "severity": card.get("severity"),
        "headline": card.get("headline"),
        "facts": card.get("facts"),
        "action": card.get("action"),
        "consequence": card.get("consequence"),
        "entity": (card.get("entity") or {}).get("name"),
        "change": card.get("change"),
        "data_boundary": card.get("data_boundary"),
    }


# ---------------------------------------------------------------------------
# LLM 调用辅助：JSON输出 + 数字校验
# ---------------------------------------------------------------------------

def _llm_json(cfg: dict, task: str, payload: dict, history: list[dict],
              max_tokens: int = 700) -> tuple[dict | None, str, set[str]]:
    """返回 (解析结果, llm_status, 数字允许集)。未启用/失败时结果为None。"""
    allowed = extract_numbers(json.dumps(payload, ensure_ascii=False))
    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = str(turn.get("content") or "")[:500]
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
            allowed |= extract_numbers(content)
    messages.append({"role": "user", "content": task
                     + json.dumps(payload, ensure_ascii=False, indent=1)})

    if not (llm_ready(cfg) and cfg.get("chat_enabled")):
        return None, "disabled", allowed
    try:
        raw = chat_completion(cfg, messages, max_tokens=max_tokens)
    except LLMError as exc:
        status = ("disabled" if exc.kind == KIND_NOT_CONFIGURED
                  else f"failed:{exc.kind}")
        return None, status, allowed
    data = _parse_json(raw)
    return (data, "ok", allowed) if data else (None, "failed:invalid_json", allowed)


def _numbers_ok(text: str, allowed: set[str]) -> bool:
    return extract_numbers(text or "") <= allowed


# ---------------------------------------------------------------------------
# 五类意图的回答器
# ---------------------------------------------------------------------------

def _verify_skeleton(cited: list[dict]) -> str:
    """查证回答的结构骨架（LLM与模板兜底共用同一表达逻辑）：
    结论句 → 建议动作 → 代价 → 其余信号一行带过。不再罗列facts、不打印路由。"""
    top = cited[0]
    name = (top.get("entity") or {}).get("name") or ""
    head = top.get("headline") or ""
    lines = [head if not name or head.startswith(name) else f"{name}：{head}"]
    action = top.get("action") or {}
    what, owner, when = action.get("what"), action.get("owner"), action.get("when")
    if what:
        tail = "；".join(x for x in (owner, when) if x)
        lines.append(f"· 建议：{what}" + (f"（{tail}）" if tail else ""))
    consequence = top.get("consequence") or ""
    if consequence and consequence != "—":
        lines.append(f"· 不处理：{consequence}")
    for card in cited[1:]:
        lines.append(f"· 另见：{card.get('headline')}")
    return "\n".join(lines)


def _verify_guide(top: dict) -> str:
    """查证指引（代码拼接，不经LLM、不参与数字校验）。

    只引导点击"非零"的可下钻数字——零值数字在前端渲染为静态文本，
    引导用户去点一个点不动的数字是错误指引。
    """
    facts = top.get("facts") or {}
    drill = [k for k in (top.get("drillable_facts") or [])
             if not re.match(r"^0(?!\d)", str(facts.get(k, "")))]
    if drill:
        return f"依据见右栏[1]；点「{drill[0]}」可直接查看明细清单。"
    return "依据见右栏编号引用，可点开查证页核验。"


# 查证任务的表达规范与满分范例：LLM学语气与结构，范例数字不在允许集中，
# 照抄范例数字必然触发数字校验失败——迫使模型只能使用材料数字。
_VERIFY_TASK = """任务：以管理参谋的语气回答查证类问题，输出JSON {"answer": "≤160字"}。
表达结构（必须按此逻辑组织，不得罗列材料原文）：
1. 首句直接回答问题：结论+最关键数字；
2. 支撑依据：只挑2-3个最能说明问题的事实（用"·"开头分行）；
3. 建议动作：谁、做什么、何时完成（取自材料action）；
4. 不处理的代价：一句（取自材料consequence）。
禁区：不输出任何路径/链接/引用编号；不照搬headline原文；不补充材料之外的事实。
风格范例（仅学语气与结构，其中数字不可用）：
问：学生体质健康测试的受阻学生名单？
答：学生体质健康测试有 51 名应届生必修明确未通过，涉及 10 个专业；更关键的是这门课历史上没有开课记录，学院无法自行消化。
· 建议：教务处牵头协调补修安排，毕业审核启动前完成
· 不处理：学生将失去最后补修机会，缺口转化为延毕风险
材料：
"""


def _answer_verify(message: str, cited: list[dict], cfg: dict | None = None,
                   history: list[dict] | None = None) -> dict:
    """查证：LLM按"骨架+范例"主笔，数字校验；未启用/失败回退同骨架模板。"""
    if not cited:
        return {
            "text": ("当前简报中没有与该问题直接相关的信号。"
                     "可查证的范围：毕业缺口、课程质量、预警优先级、师资结构"
                     "——可换个问法，或先打开对应专题工作区。"),
            "blocks": [], "llm_status": "not_used",
        }
    top = cited[0]
    guide = _verify_guide(top)
    payload = {"问题": message, "相关信号": [_signal_payload(c) for c in cited]}
    status = "not_used"
    if cfg is not None:
        data, status, allowed = _llm_json(cfg, _VERIFY_TASK, payload,
                                          history or [])
        if data and isinstance(data.get("answer"), str) \
                and data["answer"].strip() \
                and _numbers_ok(data["answer"], allowed):
            return {"text": f"{data['answer'].strip()}\n{guide}",
                    "blocks": [], "llm_status": "ok"}
        if status == "ok":
            status = "failed:number_validation"
    return {"text": f"{_verify_skeleton(cited)}\n{guide}",
            "blocks": [], "llm_status": status}


def _answer_simulate(message: str, cited: list[dict]) -> dict:
    """假设测算：能力边界诚实声明（决策点D1：旧模拟页已下线，测算Skill属后续阶段）。"""
    text = ("假设测算（如「如果新增若干班/教师会怎样」）当前版本未接入决策链路："
            "旧「决策研判」模拟页已按既定决策下线，测算类Skill规划在后续阶段。\n"
            "可以先查证当前基线数据，作为人工测算的起点：")
    if cited:
        facts = _facts_line(cited[0])
        text += f"\n· {cited[0].get('headline')}" + (f"（{facts}）" if facts else "")
    else:
        text += "\n· 可在决策简报各专题工作区查看当前基线。"
    return {"text": text, "blocks": [], "llm_status": "not_used"}


def _answer_compare(message: str, cited: list[dict], cfg: dict,
                    history: list[dict]) -> dict:
    """比较：LLM只组织已引用信号的事实；失败回退事实罗列模板。"""
    if not cited:
        return _answer_open(message, cited, cfg, history)
    payload = {"问题": message, "可比较的信号": [_signal_payload(c) for c in cited]}
    task = ("任务：基于给定信号回答比较类问题，输出JSON "
            '{"answer": "≤120字结论", "points": ["要点≤40字"]}（points至多4条）。'
            "只使用材料中的信号与数字，不得推断材料之外的维度。\n材料：\n")
    data, status, allowed = _llm_json(cfg, task, payload, history)
    if data:
        answer = data.get("answer")
        points = [p for p in (data.get("points") or [])
                  if isinstance(p, str) and p.strip()][:4]
        if (isinstance(answer, str) and answer.strip()
                and _numbers_ok(answer, allowed)
                and all(_numbers_ok(p, allowed) for p in points)):
            blocks = ([{"layer": "points", "title": "对比要点",
                        "items": points}] if points else [])
            return {"text": answer.strip(), "blocks": blocks, "llm_status": "ok"}
        status = "failed:number_validation"
    # 回退：事实罗列（数字全部来自信号，天然安全）
    lines = ["所涉事项的事实对照（系统按信号原文列出）："]
    for i, card in enumerate(cited, 1):
        facts = _facts_line(card)
        lines.append(f"{i}. {card.get('headline')}"
                     + (f"（{facts}）" if facts else ""))
    lines.append("严重度与排序由系统按统一规则给出，首要事项见简报优先处置区。")
    return {"text": "\n".join(lines), "blocks": [], "llm_status": status}


def _answer_attribute(message: str, cited: list[dict], cfg: dict,
                      history: list[dict]) -> dict:
    """归因：强制三明治——事实层/假设层(待验证)/行动层。"""
    if not cited:
        return _answer_open(message, cited, cfg, history)
    primary = cited[0]
    payload = {"问题": message, "主要信号": _signal_payload(primary),
               "关联信号": [_signal_payload(c) for c in cited[1:]]}
    task = (
        "任务：回答归因类问题，严格按三明治结构输出JSON：\n"
        '{"facts_text": "事实层：材料中确实发生了什么（≤80字，只复述材料）",\n'
        ' "hypotheses": [{"text": "一个可能原因（≤50字）", '
        '"verify": "验证该假设需查看的数据/口径（≤40字）"}],\n'
        ' "action_text": "行动层：当前最该做的动作（≤60字，基于材料建议）"}\n'
        "要求：hypotheses至多2条；每条都是待验证假设，不得表述为确定结论；"
        "验证路径必须具体可查（指标/表/口径），不得空泛；不评价具体个人。\n材料：\n")
    data, status, allowed = _llm_json(cfg, task, payload, history)

    facts_text = primary.get("headline") or ""
    facts = _facts_line(primary)
    if facts:
        facts_text += f"（{facts}）"
    action = primary.get("action") or {}
    action_text = "；".join(x for x in [
        action.get("owner"), action.get("what"), action.get("when")] if x)

    hypotheses: list[dict] = []
    if data:
        if (isinstance(data.get("facts_text"), str) and data["facts_text"].strip()
                and _numbers_ok(data["facts_text"], allowed)):
            facts_text = data["facts_text"].strip()
        if (isinstance(data.get("action_text"), str) and data["action_text"].strip()
                and _numbers_ok(data["action_text"], allowed)):
            action_text = data["action_text"].strip()
        for h in (data.get("hypotheses") or [])[:2]:
            if not isinstance(h, dict):
                continue
            text, verify = h.get("text"), h.get("verify")
            if (isinstance(text, str) and text.strip()
                    and isinstance(verify, str) and verify.strip()
                    and _numbers_ok(text, allowed) and _numbers_ok(verify, allowed)):
                hypotheses.append({"text": text.strip(), "verify": verify.strip()})
        if not hypotheses and status == "ok":
            status = "failed:number_validation"

    blocks = [
        {"layer": "facts", "title": "事实层 · 数据确认的", "text": facts_text},
    ]
    for h in hypotheses:
        blocks.append({"layer": "hypothesis", "title": "假设层 · 待验证",
                       "text": h["text"], "verify": h["verify"]})
    if not hypotheses:
        blocks.append({"layer": "hypothesis", "title": "假设层 · 待验证",
                       "text": ("假设层需要LLM增强生成。"
                                if status == "disabled" else
                                "本次假设生成未通过系统校验，已省略，避免误导。")})
    blocks.append({"layer": "action", "title": "行动层 · 当前该做的",
                   "text": action_text or "按信号建议推进处置。"})
    intro = ("归因分三层呈现：数据确认的事实、待验证的假设、当前可执行的动作。"
             "假设不等于结论，验证路径已随假设给出。")
    return {"text": intro, "blocks": blocks, "llm_status": status}


def _answer_open(message: str, cited: list[dict], cfg: dict,
                 history: list[dict], briefing: dict | None = None) -> dict:
    """开放：LLM在材料边界内作答；失败回退到简报事实摘要。"""
    payload = {
        "问题": message,
        "简报topline": (briefing or {}).get("topline"),
        "紧急度说明": (briefing or {}).get("urgency_rationale"),
        "相关信号": [_signal_payload(c) for c in cited],
    }
    task = ("任务：回答管理者的开放问题，输出JSON {\"answer\": \"≤180字\"}。"
            "只依据材料与对话历史；材料不足时如实说明边界并指出可查证的入口，"
            "不得编造。\n材料：\n")
    data, status, allowed = _llm_json(cfg, task, payload, history)
    if data and isinstance(data.get("answer"), str) and data["answer"].strip() \
            and _numbers_ok(data["answer"], allowed):
        return {"text": data["answer"].strip(), "blocks": [], "llm_status": "ok"}
    if status == "ok":
        status = "failed:number_validation"
    # 回退：简报事实摘要（复用查证骨架，LLM状态按开放意图如实标注）
    if cited:
        return _answer_verify(message, cited) | {"llm_status": status}
    topline = (briefing or {}).get("topline") or "当前无重点事项。"
    return {"text": f"当前简报总判断：{topline}\n"
                    "更具体的问题可指明专题（毕业/课程/预警/师资）或点击卡片追问。",
            "blocks": [], "llm_status": status}


# ---------------------------------------------------------------------------
# 编排：两阶段（路由即时出引用 → 生成答案），供SSE分步下发
# ---------------------------------------------------------------------------

_CITED_FIELDS = ("signal_id", "skill_id", "severity", "signal_type", "headline",
                 "facts", "entity", "action", "consequence", "confidence",
                 "evidence", "change", "suggested_questions", "data_boundary",
                 "drillable_facts")


def _trim(card: dict) -> dict:
    """对话载荷只保留展示字段（context可能携带大名单，不进对话）。"""
    return {k: card.get(k) for k in _CITED_FIELDS}


def route(message: str, signal_id: str, briefing: dict) -> dict:
    """阶段1：意图分类 + 信号引用（纯代码，毫秒级）。"""
    intent = classify_intent(message)
    cards = all_signal_cards(briefing)
    cited: list[dict] = []
    if signal_id:
        cited = [c for c in cards if c.get("signal_id") == signal_id][:1]
    if not cited:
        cited = match_signals(message, cards)
    # 归因/比较没有命中任何信号时按开放处理（由回答器内部转接）
    return {"intent": intent, "cited": [_trim(c) for c in cited]}


def answer(message: str, history: list[dict], routed: dict,
           briefing: dict, cfg: dict) -> dict:
    """阶段2：按意图生成答案（可能调LLM，全部经数字校验）。"""
    intent, cited = routed["intent"], routed["cited"]
    if intent == INTENT_VERIFY:
        result = _answer_verify(message, cited, cfg, history)
    elif intent == INTENT_SIMULATE:
        result = _answer_simulate(message, cited)
    elif intent == INTENT_COMPARE:
        result = _answer_compare(message, cited, cfg, history)
    elif intent == INTENT_ATTRIBUTE:
        result = _answer_attribute(message, cited, cfg, history)
    else:
        result = _answer_open(message, cited, cfg, history, briefing)

    followups: list[str] = []
    for card in cited:
        for q in (card.get("suggested_questions") or []):
            if q and q not in followups:
                followups.append(q)
    if not followups:
        followups = {
            INTENT_VERIFY: ["这些信号的主要依据是什么？", "当前最优先处理哪件事？"],
            INTENT_SIMULATE: ["当前毕业缺口基线是多少？"],
            INTENT_COMPARE: ["首要事项为什么排最前？"],
            INTENT_ATTRIBUTE: ["验证这些假设需要看哪些数据？"],
            INTENT_OPEN: ["今天有哪些需要处置的事项？"],
        }.get(intent, ["今天有哪些需要处置的事项？"])
    result["followups"] = followups[:3]
    result["intent"] = intent
    result["cited"] = cited
    return result
