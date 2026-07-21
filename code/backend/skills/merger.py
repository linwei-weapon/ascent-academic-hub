"""信号合并器：去重、跨Skill热点识别、Top-N 优先级排序、快照diff。

所有排序与diff均为确定性代码——同一输入必得同一输出（稳定性第1层防线）。
"""
from __future__ import annotations

import hashlib
import json

from .protocol import SEVERITY_ORDER, Signal, SkillResult

TIER_ORDER = {"main": 0, "aux": 1, "topic": 2}


def scope_key(user: dict) -> str:
    """用户数据范围指纹：同范围用户共享同一份简报快照与diff基线。"""
    context = user.get("permission_context") or {}
    detail = context.get("detailScope") or {}
    core = {
        "role": context.get("activeRole") or user.get("role_id"),
        "type": detail.get("type"),
        "ids": sorted(detail.get("sourceScopeIds") or []),
    }
    return hashlib.md5(
        json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def find_hotspots(results: list[SkillResult]) -> dict[str, list[str]]:
    """跨Skill实体热点：同一管理对象(类型+ID)被≥2个Skill命中 → signal_id列表。"""
    by_entity: dict[tuple, list[tuple[str, str]]] = {}
    for result in results:
        for sig in result.signals:
            entity = sig.entity or {}
            key = (entity.get("type"), entity.get("id"))
            if not key[0] or not key[1]:
                continue
            by_entity.setdefault(key, []).append((result.skill_id, sig.signal_id))
    hotspots: dict[str, list[str]] = {}
    for _entity, hits in by_entity.items():
        skills = {skill_id for skill_id, _ in hits}
        if len(skills) >= 2:
            for _skill_id, signal_id in hits:
                hotspots.setdefault(signal_id, [])
            for skill_id, signal_id in hits:
                others = [sid for sk, sid in hits if sk != skill_id]
                hotspots[signal_id] = sorted(set(hotspots[signal_id] + others))
    return hotspots


def merge_signals(results: list[SkillResult], tier_map: dict[str, str] | None = None,
                  top_n: int = 8) -> dict:
    """合并全部Skill信号 → {priority_items, hotspots, all_signals}。

    排序键：严重度 → 是否跨Skill热点 → Skill层级 → signal_id（稳定次序）。
    回填：signal.related（热点关联）。
    tier_map: {skill_id: "main"|"aux"|"topic"}，由服务层从 registry 注入。
    """
    tiers = tier_map or {}
    hotspots = find_hotspots(results)

    all_signals: list[Signal] = []
    seen: set[str] = set()
    for result in results:
        for sig in result.signals:
            if sig.signal_id in seen:
                continue
            seen.add(sig.signal_id)
            sig.related = hotspots.get(sig.signal_id, [])
            all_signals.append(sig)

    def key(sig: Signal):
        return (
            SEVERITY_ORDER.get(sig.severity, 9),
            0 if sig.signal_id in hotspots else 1,
            TIER_ORDER.get(tiers.get(sig.skill_id), 1),
            sig.signal_id,
        )

    ordered = sorted(all_signals, key=key)
    return {
        "priority_items": ordered[:top_n],
        "all_signals": ordered,
        "hotspots": hotspots,
    }


def diff_signals(current: list[Signal],
                 previous: list[dict]) -> tuple[list[Signal], list[dict]]:
    """与上次快照比对，回填 signal.change，并返回已消除信号列表。

    previous: 上次快照的信号摘要 [{signal_id, severity, fingerprint_part, headline}]
    change: new(新出现) | upgraded(严重度升级) | ongoing(持续) | resolved(已消除，仅出现在返回值)
    """
    prev_by_id = {p["signal_id"]: p for p in previous}
    resolved: list[dict] = []
    current_ids = set()

    for sig in current:
        current_ids.add(sig.signal_id)
        prev = prev_by_id.get(sig.signal_id)
        if prev is None:
            sig.change = "new"
        elif SEVERITY_ORDER.get(sig.severity, 9) < SEVERITY_ORDER.get(
                prev.get("severity", ""), 9):
            sig.change = "upgraded"
        else:
            sig.change = "ongoing"

    for pid, prev in prev_by_id.items():
        if pid not in current_ids:
            resolved.append({
                "signal_id": pid,
                "severity": prev.get("severity"),
                "headline": prev.get("headline", ""),
                "change": "resolved",
            })
    return current, resolved


def signal_digest(sig: Signal) -> dict:
    """存入快照的信号摘要（diff基线所需的最小字段）。"""
    return {
        "signal_id": sig.signal_id,
        "skill_id": sig.skill_id,
        "signal_type": sig.signal_type,
        "severity": sig.severity,
        "headline": sig.headline,
        "fingerprint_part": sig.fingerprint_part(),
    }
