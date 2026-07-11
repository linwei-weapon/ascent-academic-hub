"""一次性幂等迁移：把预警规则全部对齐为"阈值触发"并去掉 AI 措辞。

- 删除 R5「选课异常」（无数据源、原已 disabled）。
- R1「GPA持续下降」/ R6「退学风险」trigger_type ai→threshold，params.text 去 AI 综合评估措辞。
- R2/R3/R4 已是 threshold，仅确保 text 无 AI 字样（与 seed.py ALERT_RULES 一致）。

只动 sys_alert_rule，不重 seed、不碰其他数据。可重复执行。
引擎 alert_engine.py 按 rule_id 分支、从 params 读阈值，不读 trigger_type，
故改 trigger_type 标签不影响已生成预警；阈值数值未变→预警结果不变。

运行：cd 平台管理端-0618 && python -X utf8 scripts/migrate_alert_rules.py
"""
import json
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])  # 让 backend 包可导入

from backend.etl import config
from backend.etl.seed import ALERT_RULES

# 需删除的历史规则（已下线）
OBSOLETE_RULES = ["R5"]


def main() -> None:
    conn = sqlite3.connect(str(config.DB_PATH))
    cur = conn.cursor()

    # 1) 删除下线规则
    for rid in OBSOLETE_RULES:
        cur.execute("DELETE FROM sys_alert_rule WHERE rule_id=?", (rid,))

    # 2) 按 seed.ALERT_RULES UPSERT（trigger_type/params/text/enabled 全部对齐）
    for r in ALERT_RULES:
        cur.execute("""
            INSERT INTO sys_alert_rule (rule_id, name, level, trigger_type, params, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                name=excluded.name, level=excluded.level,
                trigger_type=excluded.trigger_type, params=excluded.params,
                enabled=excluded.enabled
        """, (r["rule_id"], r["name"], r["level"], r["trigger_type"],
              json.dumps(r["params"], ensure_ascii=False), r["enabled"]))

    conn.commit()

    print("== 迁移后 sys_alert_rule ==")
    for r in conn.execute(
            "SELECT rule_id, name, level, trigger_type, enabled FROM sys_alert_rule ORDER BY rule_id"):
        print(f"  {r[0]}  {r[1]:<12} {r[2]:<4} {r[3]:<10} enabled={r[4]}")
    n = conn.execute("SELECT COUNT(*) FROM sys_alert_rule").fetchone()[0]
    ai = conn.execute("SELECT COUNT(*) FROM sys_alert_rule WHERE trigger_type='ai'").fetchone()[0]
    print(f"== 规则总数: {n} · AI 触发数: {ai}（应为 0）")
    conn.close()
    print("迁移完成。")


if __name__ == "__main__":
    main()
