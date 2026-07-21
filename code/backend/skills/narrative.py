"""简报叙事增强（阶段4.1/4.2）：LLM 只改写叙事文字，不产生数字。

稳定性防线：
1. 允许集 = 发给 LLM 的材料中出现的全部数字字面量（阿拉伯数字 + 中文数字量词）。
2. LLM 输出逐字段校验：出现允许集之外的数字 → 该字段回退模板版。
3. JSON 解析失败 / 调用失败 → 整体回退模板版，generation_method 保持 rule_template，
   前端角标如实显示"规则生成"（决策点 D3）。
4. 增强结果随快照缓存：同数据 → 同指纹 → 同叙事，保证"同数据100%一致"。
"""
from __future__ import annotations

import json
import re

from .llm_client import KIND_NOT_CONFIGURED, LLMError, chat_completion
from .llm_config import llm_ready

# ---------------------------------------------------------------------------
# SystemPrompt（阶段4.1）：角色 + 七级泛化光谱(L1-4) + 禁区清单
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是高校教学管理决策简报的叙事助手。给定由确定性代码计算出的管理事实，你的唯一任务是把它们改写为流畅、克制的管理语言。

铁律（违反任何一条，输出将被系统拒绝）：
1. 你输出的每一个数字都必须逐字来自给定材料；不得计算、估算、换算、四舍五入或创造任何数字。
2. 只允许四级表达：复述材料事实 / 组织信息结构 / 解释规则含义 / 关联引用材料中给出的信号ID。
3. 禁区：不评价具体教师个人；不推断学生心理或品行；不预测未来数据；不输出人事或处分建议；不引用材料之外的任何事实。
4. 不得改变事实的严重度、责任归属、时限与代价表述的含义。
5. 只输出指定JSON，不得输出任何额外文字、注释或Markdown。"""

_TASK_PROMPT = """请把以下决策简报材料改写为叙事版，输出JSON：
{
  "topline": "一句话总判断（≤80字，含材料中的关键数字）",
  "urgency_rationale": "紧急度说明（≤60字）",
  "item_narratives": {"信号ID": "该优先事项的一句话叙事（≤70字，串起事实→动作→代价）"}
}
item_narratives 只覆盖材料中列出的优先事项信号ID，不得新增键。

材料：
"""

# ---------------------------------------------------------------------------
# 数字校验：阿拉伯数字 + 紧邻量词的中文数字
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?%?")
_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_CN_NUM_RE = re.compile(r"[零一二两三四五六七八九十](?=[项门人个名条次所届堂项起])")


def extract_numbers(text: str) -> set[str]:
    """提取文本中的数字字面量并归一化（去千分位、去百分号、中文数字转阿拉伯）。"""
    out: set[str] = set()
    for m in _NUM_RE.findall(text or ""):
        token = m.replace(",", "").rstrip("%")
        out.add(token)
        if token.endswith(".0"):
            out.add(token[:-2])
    for m in _CN_NUM_RE.findall(text or ""):
        out.add(str(_CN_NUM[m]))
    return out


def _validate_text(text: str, allowed: set[str]) -> bool:
    """输出文本的所有数字必须落在允许集内。"""
    return extract_numbers(text) <= allowed


def _parse_json(text: str) -> dict | None:
    """容错解析LLM输出的JSON对象（剥离代码围栏，截取首尾花括号）。"""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# 增强入口
# ---------------------------------------------------------------------------

def _facts_payload(briefing: dict) -> dict:
    """发给LLM的材料：数字唯一合法来源。允许集即从本载荷提取。"""
    items = []
    for card in briefing.get("priority_items", [])[:5]:
        items.append({
            "signal_id": card.get("signal_id"),
            "severity": card.get("severity"),
            "headline": card.get("headline"),
            "facts": card.get("facts"),
            "action": card.get("action"),
            "consequence": card.get("consequence"),
            "entity": (card.get("entity") or {}).get("name"),
        })
    return {
        "模板topline": briefing.get("topline"),
        "模板紧急度说明": briefing.get("urgency_rationale"),
        "紧急度": briefing.get("urgency"),
        "优先事项": items,
        "观察项数量": len(briefing.get("watch_items", [])),
        "积极变化数量": len(briefing.get("positive_developments", [])),
    }


def enhance_briefing(briefing: dict, cfg: dict) -> dict:
    """对模板简报做叙事增强；任何失败都回退模板版并诚实标注。

    幂等安全性：增强在快照落库前执行一次，随快照缓存。
    """
    briefing["llm_status"] = "disabled"
    if not briefing.get("priority_items"):
        return briefing  # 无优先事项时模板topline已足够，不花LLM调用
    if not (llm_ready(cfg) and cfg.get("narrative_enabled")):
        return briefing

    payload = _facts_payload(briefing)
    allowed = extract_numbers(json.dumps(payload, ensure_ascii=False))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _TASK_PROMPT
         + json.dumps(payload, ensure_ascii=False, indent=1)},
    ]
    try:
        raw = chat_completion(cfg, messages, max_tokens=900, temperature=0.2)
    except LLMError as exc:
        briefing["llm_status"] = (
            "disabled" if exc.kind == KIND_NOT_CONFIGURED else f"failed:{exc.kind}")
        return briefing

    data = _parse_json(raw)
    if data is None:
        briefing["llm_status"] = "failed:invalid_json"
        return briefing

    enhanced_any = False
    topline = data.get("topline")
    if (isinstance(topline, str) and topline.strip()
            and len(topline) <= 120 and _validate_text(topline, allowed)):
        briefing["topline"] = topline.strip()
        enhanced_any = True

    rationale = data.get("urgency_rationale")
    if (isinstance(rationale, str) and rationale.strip()
            and len(rationale) <= 120 and _validate_text(rationale, allowed)):
        briefing["urgency_rationale"] = rationale.strip()
        enhanced_any = True

    narratives = data.get("item_narratives")
    valid_ids = {c.get("signal_id") for c in briefing.get("priority_items", [])}
    if isinstance(narratives, dict):
        for card in briefing.get("priority_items", []):
            text = narratives.get(card.get("signal_id"))
            if (isinstance(text, str) and text.strip() and len(text) <= 140
                    and card.get("signal_id") in valid_ids
                    and _validate_text(text, allowed)):
                card["narrative"] = text.strip()
                enhanced_any = True

    if enhanced_any:
        briefing["generation_method"] = "llm_enhanced"
        briefing["llm_status"] = "ok"
    else:
        briefing["llm_status"] = "failed:number_validation"
    return briefing
