"""模板简报引擎：把合并后的信号装配成固定结构简报（LLM增强版复用同一结构）。

稳定性防线第1层：所有判断（紧急度、排序、topline数字）由代码产生；
LLM 关闭或失败时，本引擎的输出即是完整可用的最终产品。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import config_store, llm_config, narrative, store
from .merger import (diff_signals, merge_signals, scope_key, signal_digest)
from .protocol import (SEVERITY_ORDER, Signal, SkillContext, SkillResult,
                       briefing_fingerprint, empty_briefing)
from .registry import get_skill, list_skills

POSITIVE_TYPES = {"improving"}

# 快照结构版本：卡片/context 结构发生不兼容变化时递增，
# 旧快照自动失效重建，避免升级后长期消费旧结构缓存。
BRIEFING_SCHEMA_VERSION = 3


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 模板装配（纯函数，可单测）
# ---------------------------------------------------------------------------

def _topline(priority: list[Signal], counts: dict[str, int]) -> str:
    if not priority:
        return "今日无新增重点事项，各项管理指标处于常规区间。"
    top = priority[0]
    parts = []
    if counts.get("critical"):
        parts.append(f"{counts['critical']}项紧急")
    if counts.get("high"):
        parts.append(f"{counts['high']}项重点")
    total = counts.get("critical", 0) + counts.get("high", 0)
    head = f"今日{total}项需处置事项" if parts else "今日事项以常规跟进为主"
    name = (top.entity or {}).get("name") or top.headline[:16]
    return (f"{head}（{'、'.join(parts)}），首要：{name}——"
            f"{top.action.get('owner', '')}，{top.action.get('when', '尽快')}。")


def _urgency(counts: dict[str, int]) -> tuple[str, str]:
    critical, high = counts.get("critical", 0), counts.get("high", 0)
    if critical or high >= 3:
        return "critical", (
            f"存在{critical}项紧急事项与{high}项重点事项，"
            f"需要今日内明确责任人与时限。")
    if high:
        return "elevated", f"存在{high}项重点事项，建议本周内完成处置安排。"
    return "normal", "无紧急/重点事项，按常规节奏推进即可。"


def drillable_facts_of(skill_id: str, signal_type: str) -> list[str]:
    """该信号可下钻明细的 facts 标签列表（来自 Skill.detail_specs 契约）。"""
    skill = get_skill(skill_id)
    if not skill:
        return []
    return sorted((skill.detail_specs.get(signal_type) or {}).keys())


def _signal_card(sig: Signal, hotspot_ids: set[str]) -> dict:
    """信号 → 前端卡片载荷（五要素结构完整）。不含任何追踪/交办状态。"""
    card = sig.to_dict()
    card["hotspot"] = sig.signal_id in hotspot_ids
    card["drillable_facts"] = drillable_facts_of(sig.skill_id, sig.signal_type)
    return card


def build_briefing(merged: dict, results: list[SkillResult],
                   resolved: list[dict],
                   semester: str, fingerprint: str) -> dict:
    """合并结果 + diff → 固定结构简报（模板版）。不含追踪/交办状态。"""
    briefing = empty_briefing()
    all_signals: list[Signal] = merged["all_signals"]
    priority: list[Signal] = merged["priority_items"]
    hotspot_ids = set(merged["hotspots"].keys())

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for sig in all_signals:
        counts[sig.severity] = counts.get(sig.severity, 0) + 1

    briefing["topline"] = _topline(priority, counts)
    urgency, rationale = _urgency(counts)
    briefing["urgency"] = urgency
    briefing["urgency_rationale"] = rationale
    briefing["priority_items"] = [
        _signal_card(s, hotspot_ids) for s in priority]
    briefing["skill_sections"] = [{
        "skill_id": r.skill_id,
        "skill_name": r.skill_name,
        "management_question": r.management_question,
        "summary_stats": r.summary_stats,
        "exclusions": r.exclusions,
        "data_readiness": r.data_readiness,
        "data_boundary": r.data_boundary,
        "config_version": r.config_version,
        "signals": [
            _signal_card(s, hotspot_ids)
            for s in sorted(r.signals,
                            key=lambda x: (SEVERITY_ORDER.get(x.severity, 9),
                                           x.signal_id))
        ],
    } for r in results]
    briefing["watch_items"] = [
        _signal_card(s, hotspot_ids)
        for s in all_signals if s.severity == "low"
        and s.signal_type not in POSITIVE_TYPES]
    briefing["positive_developments"] = [
        _signal_card(s, hotspot_ids)
        for s in all_signals if s.signal_type in POSITIVE_TYPES]
    briefing["resolved_since_last"] = resolved
    briefing["generated_at"] = _now()
    briefing["data_freshness"] = {
        r.skill_id: r.summary_stats.get("snapshot_semester") or semester
        for r in results
    }
    briefing["stats"] = {r.skill_id: r.summary_stats for r in results}
    briefing["snapshot_fingerprint"] = fingerprint
    briefing["semester"] = semester
    briefing["schema_version"] = BRIEFING_SCHEMA_VERSION
    return briefing


def _iter_cards(briefing: dict):
    """遍历简报内全部信号卡片及其所属Skill分区。"""
    skill_names = {s.get("skill_id"): s for s in briefing.get("skill_sections", [])}
    for card in briefing.get("priority_items", []):
        yield card, skill_names.get(card.get("skill_id"), {})
    for section in briefing.get("skill_sections", []):
        for card in section.get("signals", []):
            yield card, section
    for card in briefing.get("watch_items", []):
        yield card, skill_names.get(card.get("skill_id"), {})
    for card in briefing.get("positive_developments", []):
        yield card, skill_names.get(card.get("skill_id"), {})


def build_signal_evidence(briefing: dict, signal_id: str) -> dict | None:
    """单信号完整证据包（查证窗口数据源）。

    找不到（不存在或不在当前用户数据范围内）返回 None——
    两种情形对外都是404，不泄露范围外信号的存在性。
    """
    for card, section in _iter_cards(briefing):
        if card.get("signal_id") != signal_id:
            continue
        return {
            "signal": card,
            "skill": {
                "skill_id": section.get("skill_id") or card.get("skill_id"),
                "skill_name": section.get("skill_name", ""),
                "management_question": section.get("management_question", ""),
                "config_version": section.get("config_version", ""),
                "data_boundary": section.get("data_boundary", ""),
                "data_readiness": section.get("data_readiness", {}),
                "exclusions": section.get("exclusions", []),
            },
            "semester": briefing.get("semester", ""),
            "generated_at": briefing.get("generated_at", ""),
            "generation_method": briefing.get("generation_method", "rule_template"),
            "data_freshness": (briefing.get("data_freshness") or {}).get(
                card.get("skill_id"), ""),
            "summary_stats": (briefing.get("stats") or {}).get(
                card.get("skill_id"), {}),
        }
    return None


# ---------------------------------------------------------------------------
# 明细下钻：数据要素数字 → 该数字代表的业务明细清单
# ---------------------------------------------------------------------------

DETAIL_ROW_CAP = 200    # 明细行数硬上限，超出提示前往专题工作区


def build_signal_detail(briefing: dict, signal_id: str, fact: str) -> dict | None:
    """单信号单数据要素的明细清单。

    返回 None：信号不存在/越权（对外 404）。
    返回 {"drillable": False}：该数据要素是聚合/判定值，无明细语义（对外 400）。
    明细行取自信号 context（Skill 按当前身份数据范围预计算），
    本函数不做任何客户端传入的筛选，天然继承权限边界。
    """
    for card, section in _iter_cards(briefing):
        if card.get("signal_id") != signal_id:
            continue
        skill = get_skill(card.get("skill_id", ""))
        spec = ((skill.detail_specs.get(card.get("signal_type", "")) or {})
                .get(fact) if skill else None)
        if not spec:
            return {"drillable": False, "signal_id": signal_id, "fact": fact}
        context = card.get("context") or {}
        rows = list(context.get(spec["context_key"]) or [])
        filt = spec.get("filter")
        if filt:
            rows = [r for r in rows if r.get(filt["key"]) == filt["equals"]]
        total = context.get(spec.get("total_key") or "") or len(rows)
        total = max(int(total), len(rows))
        capped = rows[:DETAIL_ROW_CAP]
        return {
            "drillable": True,
            "signal_id": signal_id,
            "fact": fact,
            "fact_value": (card.get("facts") or {}).get(fact, ""),
            "title": spec.get("title") or fact,
            "headline": card.get("headline", ""),
            "columns": spec.get("columns") or [],
            "rows": capped,
            "total": total,
            "truncated": total > len(capped),
            "skill": {
                "skill_id": card.get("skill_id"),
                "skill_name": section.get("skill_name", ""),
            },
            "semester": briefing.get("semester", ""),
            "generated_at": briefing.get("generated_at", ""),
            "data_boundary": card.get("data_boundary", "")
            or section.get("data_boundary", ""),
            "verify_route": (card.get("evidence") or {}).get("verify_route", ""),
        }
    return None


# ---------------------------------------------------------------------------
# 编排：运行Skills → 合并 → 指纹缓存 → diff → 装配 → 落库
# ---------------------------------------------------------------------------

def run_all_skills(user: dict, legacy: sqlite3.Connection,
                   v2: sqlite3.Connection, rw_conn: sqlite3.Connection,
                   semester: str) -> tuple[list[SkillResult], dict[str, str]]:
    results: list[SkillResult] = []
    tier_map: dict[str, str] = {}
    for skill in list_skills():
        config, version = config_store.resolve_config(rw_conn, skill)
        ctx = SkillContext(user=user, legacy=legacy, v2=v2, config=config,
                           config_version=version, semester=semester)
        results.append(skill.run(ctx))
        tier_map[skill.skill_id] = skill.briefing_tier
    return results, tier_map


def generate_briefing(user: dict, legacy: sqlite3.Connection,
                      v2: sqlite3.Connection, rw_conn: sqlite3.Connection,
                      semester: str, force: bool = False) -> dict:
    """生成-or-缓存简报。指纹未变时直接返回上次快照（含原有变化标记）。"""
    skey = scope_key(user)
    results, tier_map = run_all_skills(user, legacy, v2, rw_conn, semester)
    merged = merge_signals(results, tier_map)
    fingerprint = briefing_fingerprint(merged["all_signals"])

    if not force:
        cached = store.latest_snapshot(rw_conn, skey)
        # 快照结构版本不一致（如明细下钻 context 扩容）时弃用缓存重建
        if (cached and cached["fingerprint"] == fingerprint
                and cached["briefing"].get("schema_version") == BRIEFING_SCHEMA_VERSION):
            briefing = cached["briefing"]
            # 旧快照结构向后兼容：新增字段补默认值，退役字段清理
            briefing.setdefault("llm_status", "disabled")
            briefing.pop("previous_followup", None)
            # 旧快照卡片中可能嵌有已退役的追踪字段，统一清理
            for section in ("priority_items", "watch_items",
                            "positive_developments"):
                for item in briefing.get(section, []):
                    item.pop("tracking", None)
                    item["drillable_facts"] = drillable_facts_of(
                        item.get("skill_id", ""), item.get("signal_type", ""))
            for sec in briefing.get("skill_sections", []):
                for item in sec.get("signals", []):
                    item.pop("tracking", None)
                    item["drillable_facts"] = drillable_facts_of(
                        item.get("skill_id", ""), item.get("signal_type", ""))
            briefing["cache_hit"] = True
            return briefing

    previous = []
    cached = store.latest_snapshot(rw_conn, skey)
    if cached:
        previous = cached["signals"]
    _, resolved = diff_signals(merged["all_signals"], previous)

    briefing = build_briefing(merged, results, resolved,
                              semester, fingerprint)
    # 叙事增强（阶段4.2）：LLM 只改文字，失败回退模板版；增强结果随快照缓存
    try:
        briefing = narrative.enhance_briefing(
            briefing, llm_config.load_config(rw_conn))
    except Exception:
        briefing["generation_method"] = "rule_template"
        briefing["llm_status"] = "failed:internal"
    digests = [signal_digest(s) for s in merged["all_signals"]]
    store.save_snapshot(rw_conn, skey, semester, fingerprint,
                        briefing["generation_method"], briefing, digests,
                        user.get("username", "system"))
    briefing["cache_hit"] = False
    return briefing
