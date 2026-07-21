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
from .registry import list_skills

POSITIVE_TYPES = {"improving"}


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


def _signal_card(sig: Signal, hotspot_ids: set[str],
                 tracked: dict[str, dict]) -> dict:
    """信号 → 前端卡片载荷（五要素结构完整）。"""
    card = sig.to_dict()
    card["hotspot"] = sig.signal_id in hotspot_ids
    track = tracked.get(sig.signal_id)
    card["tracking"] = (
        {"status": track["status"], "assignee": track.get("assignee"),
         "note": track.get("note"), "updated_at": track.get("updated_at")}
        if track else None)
    return card


def _followups(tracking_rows: list[dict], current_ids: set[str]) -> list[dict]:
    """上次建议追踪：追踪状态 × 信号是否仍存在，四种组合如实呈现。"""
    out = []
    for row in tracking_rows:
        present = row["signal_id"] in current_ids
        status = row["status"]
        if status in ("open", "in_progress") and present:
            state, state_note = "active", "信号仍有效"
        elif status in ("open", "in_progress") and not present:
            state, state_note = "signal_gone", "信号已消失，待确认是否完成"
        elif status == "done" and present:
            state, state_note = "recheck", "已标记完成但信号仍存在，需复核"
        elif status == "done" and not present:
            state, state_note = "closed", "已完成且信号消除"
        else:  # dismissed
            state, state_note = "dismissed", "已忽略"
        out.append({
            "signal_id": row["signal_id"], "skill_id": row["skill_id"],
            "headline": row["headline"], "entity": row["entity"],
            "action": row["action"], "status": status,
            "assignee": row.get("assignee"), "note": row.get("note"),
            "updated_at": row.get("updated_at"),
            "state": state, "state_note": state_note,
        })
    order = {"recheck": 0, "active": 1, "signal_gone": 2, "closed": 3, "dismissed": 4}
    out.sort(key=lambda x: (order.get(x["state"], 9), x["signal_id"]))
    return out[:5]


def build_briefing(merged: dict, results: list[SkillResult],
                   resolved: list[dict], tracking_rows: list[dict],
                   semester: str, fingerprint: str) -> dict:
    """合并结果 + diff + 追踪 → 固定结构简报（模板版）。"""
    briefing = empty_briefing()
    all_signals: list[Signal] = merged["all_signals"]
    priority: list[Signal] = merged["priority_items"]
    hotspot_ids = set(merged["hotspots"].keys())
    tracked = {t["signal_id"]: t for t in tracking_rows}

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for sig in all_signals:
        counts[sig.severity] = counts.get(sig.severity, 0) + 1

    briefing["topline"] = _topline(priority, counts)
    urgency, rationale = _urgency(counts)
    briefing["urgency"] = urgency
    briefing["urgency_rationale"] = rationale
    briefing["priority_items"] = [
        _signal_card(s, hotspot_ids, tracked) for s in priority]
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
            _signal_card(s, hotspot_ids, tracked)
            for s in sorted(r.signals,
                            key=lambda x: (SEVERITY_ORDER.get(x.severity, 9),
                                           x.signal_id))
        ],
    } for r in results]
    briefing["watch_items"] = [
        _signal_card(s, hotspot_ids, tracked)
        for s in all_signals if s.severity == "low"
        and s.signal_type not in POSITIVE_TYPES]
    briefing["positive_developments"] = [
        _signal_card(s, hotspot_ids, tracked)
        for s in all_signals if s.signal_type in POSITIVE_TYPES]
    briefing["previous_followup"] = _followups(
        tracking_rows, {s.signal_id for s in all_signals})
    briefing["resolved_since_last"] = resolved
    briefing["generated_at"] = _now()
    briefing["data_freshness"] = {
        r.skill_id: r.summary_stats.get("snapshot_semester") or semester
        for r in results
    }
    briefing["stats"] = {r.skill_id: r.summary_stats for r in results}
    briefing["snapshot_fingerprint"] = fingerprint
    briefing["semester"] = semester
    return briefing


# ---------------------------------------------------------------------------
# 编排：运行Skills → 合并 → 指纹缓存 → diff → 装配 → 落库
# ---------------------------------------------------------------------------

def _embed_tracking(briefing: dict, tracking_rows: list[dict]) -> None:
    """缓存命中时把最新追踪状态嵌回卡片与followup（追踪不进指纹，必须现取）。"""
    tracked = {t["signal_id"]: t for t in tracking_rows}

    def card_track(signal_id: str):
        row = tracked.get(signal_id)
        if not row:
            return None
        return {"status": row["status"], "assignee": row.get("assignee"),
                "note": row.get("note"), "updated_at": row.get("updated_at")}

    current_ids: set[str] = set()
    for section in ("priority_items", "watch_items", "positive_developments"):
        for item in briefing.get(section, []):
            item["tracking"] = card_track(item["signal_id"])
            current_ids.add(item["signal_id"])
    for sec in briefing.get("skill_sections", []):
        for item in sec.get("signals", []):
            item["tracking"] = card_track(item["signal_id"])
            current_ids.add(item["signal_id"])
    briefing["previous_followup"] = _followups(tracking_rows, current_ids)


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
        if cached and cached["fingerprint"] == fingerprint:
            briefing = cached["briefing"]
            # 旧快照结构向后兼容：新增字段补默认值
            briefing.setdefault("llm_status", "disabled")
            tracking_rows = store.list_tracking(
                rw_conn, skey, statuses=("open", "in_progress", "done"))
            _embed_tracking(briefing, tracking_rows)
            briefing["cache_hit"] = True
            return briefing

    previous = []
    cached = store.latest_snapshot(rw_conn, skey)
    if cached:
        previous = cached["signals"]
    _, resolved = diff_signals(merged["all_signals"], previous)

    tracking_rows = store.list_tracking(
        rw_conn, skey, statuses=("open", "in_progress", "done"))
    briefing = build_briefing(merged, results, resolved, tracking_rows,
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
