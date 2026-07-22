"""AI管理决策 · Skill协议层。

设计约束（与方案评审结论一致）：
- 所有数字、分级、diff 由确定性代码产生；LLM 只允许在此之上做叙事。
- 每个 Skill 是一个自包含分析管道：输入有Schema（配置+权限范围），输出是信号列表。
- 信号是"管理语义单元"：严重度、事实陈述、行动建议、数据锚点全部由代码算好。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

PROTOCOL_VERSION = "decision-skill/1.0"

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ---------------------------------------------------------------------------
# 数据需求声明：部署体检用——表不存在时 Skill 标记不可用，而不是运行时报错
# ---------------------------------------------------------------------------

@dataclass
class DataRequirement:
    table: str
    database: str          # "legacy" | "v2"
    required: bool = True
    purpose: str = ""
    fallback: str = ""     # 非必需表缺失时的降级说明


# ---------------------------------------------------------------------------
# 信号：Skill 的唯一输出单元
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    signal_id: str                 # 确定性ID：{skill}:{type}:{entity}，同数据必同ID
    skill_id: str
    signal_type: str               # 由 Skill 定义的类型枚举
    severity: str                  # critical | high | medium | low
    headline: str                  # 代码生成的事实陈述（可含数字，LLM不得改写事实）
    facts: dict[str, Any]          # 关键数字：label -> value（数字唯一合法来源）
    entity: dict[str, Any]         # {type, id, name} 管理对象
    action: dict[str, Any]         # {owner, what, when, rationale}
    consequence: str               # 不处理的代价（管理判断的灵魂）
    confidence: str                # high | medium | limited
    evidence: dict[str, Any]       # {table, condition, verify_route, freshness}
    context: dict[str, Any] = field(default_factory=dict)   # 代码预计算的辅助判断
    related: list[str] = field(default_factory=list)        # 合并器回填：关联信号ID
    data_boundary: str = ""        # 数据时效/口径边界声明
    # 快照diff由合并器回填：
    change: str = "new"            # new | upgraded | ongoing | resolved
    suggested_questions: list[str] = field(default_factory=list)  # 卡片情境化追问

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint_part(self) -> str:
        """快照指纹只取关键字段，忽略时间戳类噪音。"""
        core = {
            "id": self.signal_id, "sev": self.severity,
            "facts": self.facts, "type": self.signal_type,
        }
        return hashlib.md5(
            json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()


@dataclass
class SkillResult:
    skill_id: str
    skill_name: str
    management_question: str
    signals: list[Signal]
    summary_stats: dict[str, Any]          # 供简报首屏引用的聚合数字
    exclusions: list[dict[str, Any]]       # 显式排除项（建立信任的关键）
    data_readiness: dict[str, Any]         # 数据体检结果
    config_version: str                    # 生效配置版本（product_default 或学校版本号）
    data_boundary: str                     # 本Skill整体口径边界
    run_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        return d


# ---------------------------------------------------------------------------
# Skill 上下文与基类
# ---------------------------------------------------------------------------

@dataclass
class SkillContext:
    user: dict
    legacy: sqlite3.Connection             # analytics.sqlite（只读）
    v2: sqlite3.Connection                 # analytics_v2.sqlite（只读）
    config: dict                           # 产品默认 + 学校覆写合并后的生效配置
    config_version: str
    semester: str                          # 当前学期（legacy口径）


class Skill:
    """Skill 基类。子类只需声明元数据并实现 run()。"""

    skill_id: str = ""
    name: str = ""
    management_question: str = ""
    description: str = ""
    # 简报首屏权重：main=主角，aux=辅助，topic=专题（不进首屏Top判断）
    briefing_tier: str = "aux"
    data_requirements: list[DataRequirement] = []
    default_config: dict[str, Any] = {}
    # 学校可覆写配置的合法范围：{key: {"type": int|float|str|list, "min":, "max":, "options":}}
    config_bounds: dict[str, dict] = {}
    # 数据边界声明（会呈现在每张卡片上）
    data_boundary: str = ""

    def run(self, ctx: SkillContext) -> SkillResult:
        raise NotImplementedError

    # -- 体检 --
    def check_readiness(self, legacy: sqlite3.Connection,
                        v2: sqlite3.Connection) -> dict:
        items, missing = [], []
        for req in self.data_requirements:
            conn = v2 if req.database == "v2" else legacy
            exists = bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
                (req.table,)).fetchone())
            items.append({
                "table": req.table, "database": req.database,
                "required": req.required, "available": exists,
                "purpose": req.purpose,
                "fallback": "" if exists else req.fallback,
            })
            if req.required and not exists:
                missing.append(req.table)
        return {
            "ready": not missing,
            "missing_required": missing,
            "items": items,
        }

    # -- 配置校验（学校覆写时调用） --
    def validate_override(self, override: dict) -> list[str]:
        errors = []
        for key, value in override.items():
            bound = self.config_bounds.get(key)
            if not bound:
                errors.append(f"配置项 {key} 不允许由学校覆写")
                continue
            btype = bound.get("type")
            if btype in ("int", "float"):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"配置项 {key} 必须为数值")
                    continue
                if bound.get("min") is not None and value < bound["min"]:
                    errors.append(f"配置项 {key} 低于下限 {bound['min']}")
                if bound.get("max") is not None and value > bound["max"]:
                    errors.append(f"配置项 {key} 高于上限 {bound['max']}")
            elif btype == "str":
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"配置项 {key} 必须为非空字符串")
            elif btype == "list":
                if not isinstance(value, list) or not value:
                    errors.append(f"配置项 {key} 必须为非空数组")
            if bound.get("options") and value not in bound["options"]:
                errors.append(f"配置项 {key} 不在允许选项中")
        return errors


# ---------------------------------------------------------------------------
# 简报结构（模板引擎版输出，LLM 增强版复用同一结构）
# ---------------------------------------------------------------------------

def empty_briefing() -> dict:
    """简报的固定结构。模板引擎和LLM都必须产出这个形状。"""
    return {
        "topline": "",                    # 一句话总判断（≤80字）
        "urgency": "normal",              # normal | elevated | critical
        "urgency_rationale": "",
        "priority_items": [],             # 排序后的热点信号（含跨Skill标注）
        "skill_sections": [],             # 按Skill分区的信号列表
        "watch_items": [],                # 观察项
        "positive_developments": [],      # 积极变化
        "generated_at": "",
        "data_freshness": {},
        "generation_method": "rule_template",   # rule_template | llm_enhanced
        "snapshot_fingerprint": "",
        "stats": {},
    }


def briefing_fingerprint(signals: list[Signal]) -> str:
    parts = sorted(s.fingerprint_part() for s in signals)
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
