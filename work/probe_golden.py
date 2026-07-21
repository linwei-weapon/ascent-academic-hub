# -*- coding: utf-8 -*-
"""黄金集探测：对真实库运行全部Skill，输出信号清单与简报Top1（供编写评估用例）。"""
import json
import sqlite3
import sys

sys.path.insert(0, "code")

from backend.etl import config as etl_config
from backend.skills import config_store
from backend.skills.merger import merge_signals
from backend.skills.protocol import SkillContext
from backend.skills.registry import list_skills
from backend.api.settings import CURRENT_SEMESTER

ADMIN = {"username": "admin", "role_id": "admin",
         "permission_context": {"authorized": True,
                                "detailScope": {"type": "all"},
                                "activeRole": "admin"}}


def main():
    legacy = sqlite3.connect(f"file:{etl_config.DB_PATH}?mode=ro", uri=True)
    legacy.row_factory = sqlite3.Row
    v2 = sqlite3.connect(f"file:{etl_config.V2_DB_PATH}?mode=ro", uri=True)
    v2.row_factory = sqlite3.Row
    rw = sqlite3.connect(str(etl_config.DB_PATH))
    rw.row_factory = sqlite3.Row

    results, tier_map = [], {}
    for skill in list_skills():
        config, version = config_store.resolve_config(rw, skill)
        ctx = SkillContext(user=ADMIN, legacy=legacy, v2=v2, config=config,
                           config_version=version, semester=CURRENT_SEMESTER)
        r = skill.run(ctx)
        results.append(r)
        tier_map[skill.skill_id] = skill.briefing_tier

    merged = merge_signals(results, tier_map)

    print("=== SKILLS ===")
    for r in results:
        print(f"\n## {r.skill_id} ({tier_map[r.skill_id]}) 信号{len(r.signals)}条")
        for s in r.signals:
            print(json.dumps({
                "id": s.signal_id, "sev": s.severity, "type": s.signal_type,
                "headline": s.headline[:60], "facts": s.facts,
                "questions": s.suggested_questions,
            }, ensure_ascii=False))

    print("\n=== TOP1 ===")
    top = merged["priority_items"][0] if merged["priority_items"] else None
    print(json.dumps({"signal_id": top.signal_id, "severity": top.severity,
                      "headline": top.headline[:80]} if top else None,
                     ensure_ascii=False))
    print("hotspots:", json.dumps(merged["hotspots"], ensure_ascii=False))


if __name__ == "__main__":
    main()
