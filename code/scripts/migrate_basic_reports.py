"""注册基础报表菜单、默认授权、参数和指标绑定（幂等、仅控制数据）。

运行：python -X utf8 code/scripts/migrate_basic_reports.py [数据库路径] [--dry-run]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.api.basic_reports.catalog import REPORTS
from backend.api.basic_reports.rule_registry import REPORT_RULES, RULE_VERSION, RULES
from backend.etl import config
from scripts.migrate_menu import migrate as migrate_menu

PARAMETERS = (
    ("basic_reports.rule_version", "基础报表", "基础报表口径版本", json.dumps(RULE_VERSION, ensure_ascii=False), "string", "九张基础报表查询时计算规则版本。", 0),
    ("basic_reports.cet4_source_mode", "基础报表", "四级报表来源模式", json.dumps("cumulative_as_of_semester", ensure_ascii=False), "string", "查询时读取截至所选学期的 external_exams 明细，按通过学生去重动态累计；不生成或保存统计快照。", 0),
    ("basic_reports.official_warning_source", "基础报表", "校级学业警示名单来源", json.dumps("source_unavailable", ensure_ascii=False), "string", "未接入正式名单时禁止使用系统推导预警冒充。", 0),
)


def _metric_id(rule_id: str) -> str:
    return "BR-" + rule_id.removeprefix("BR-")

def _remove_stale_bindings(conn: sqlite3.Connection) -> int:
    """删除本迁移管理范围内已不再声明的历史规则—报表绑定。"""
    managed_metrics = {_metric_id(rule_id) for rule_id in RULES}
    managed_pages = {report.menu_path for report in REPORTS.values()}
    desired = {
        (_metric_id(rule_id), REPORTS[report_id].menu_path)
        for report_id, rule_ids in REPORT_RULES.items()
        for rule_id in rule_ids
    }
    stale = conn.execute(
        "SELECT metric_id,page_path FROM sys_metric_page_binding "
        "WHERE page_path LIKE '/admin/basic-reports/%'"
    ).fetchall()
    stale = [(row[0], row[1]) for row in stale
             if row[0] in managed_metrics and row[1] in managed_pages and (row[0], row[1]) not in desired]
    conn.executemany("DELETE FROM sys_metric_page_binding WHERE metric_id=? AND page_path=?", stale)
    return len(stale)



def migrate(conn: sqlite3.Connection) -> dict:
    migrate_menu(conn)
    for parameter in PARAMETERS:
        conn.execute("""INSERT INTO sys_system_parameter(
          parameter_key,category,name,value_json,value_type,description,editable,options_json)
          VALUES(?,?,?,?,?,?,?,'[]')
          ON CONFLICT(parameter_key) DO UPDATE SET category=excluded.category,name=excluded.name,
            value_json=excluded.value_json,value_type=excluded.value_type,description=excluded.description,
            editable=excluded.editable,version=sys_system_parameter.version+1,
            updated_at=datetime('now','localtime')
          WHERE sys_system_parameter.category<>excluded.category OR sys_system_parameter.name<>excluded.name
             OR sys_system_parameter.value_json<>excluded.value_json OR sys_system_parameter.value_type<>excluded.value_type
             OR sys_system_parameter.description<>excluded.description OR sys_system_parameter.editable<>excluded.editable""", parameter)
    _remove_stale_bindings(conn)
    for rule_id, rule in RULES.items():
        metric_id = _metric_id(rule_id)
        pages = [report.menu_path for report in REPORTS.values() if rule_id in REPORT_RULES[report.report_id]]
        conn.execute("""INSERT INTO sys_metric_definition(
          metric_id,technical_kpi_id,domain,name,formula,boundary,management_value,
          definition_status,implementation_status,data_source,grain,update_cycle,
          version,source_kind,definition_source,page_refs)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(metric_id) DO UPDATE SET name=excluded.name,formula=excluded.formula,
            boundary=excluded.boundary,implementation_status=excluded.implementation_status,
            data_source=excluded.data_source,version=excluded.version,page_refs=excluded.page_refs,
            updated_at=datetime('now','localtime')""",
          (metric_id, None, "基础报表", rule_id, rule["formula"], rule["boundary"],
           "支撑固定格式基础统计、核查和导出", "confirmed" if rule["provenance"] != "unavailable" else "pending_confirmation",
           "implemented" if rule["provenance"] != "unavailable" else "source_unavailable",
           rule["source"], "授权学生/学生-课程/组织汇总", "查询时", RULE_VERSION,
           rule["provenance"], "docs/0728基础报表需求.md", json.dumps(pages, ensure_ascii=False)))
        for page in pages:
            report = next(item for item in REPORTS.values() if item.menu_path == page)
            conn.execute("""INSERT INTO sys_metric_page_binding(
              metric_id,page_path,display_name,definition_version,implementation_version,
              verification_status,evidence_note)
              VALUES(?,?,?,?,?,?,?)
              ON CONFLICT(metric_id,page_path) DO UPDATE SET display_name=excluded.display_name,
                definition_version=excluded.definition_version,implementation_version=excluded.implementation_version,
                verification_status=excluded.verification_status,evidence_note=excluded.evidence_note,
                updated_at=datetime('now','localtime')""",
              (metric_id, page, report.title, RULE_VERSION, RULE_VERSION,
               "pending_verification", f"基础报表 {report.report_id} 自动化与人工验收后更新"))
    conn.commit()
    return {"reports": len(REPORTS), "parameters": len(PARAMETERS), "rules": len(RULES),
            "bindings": conn.execute("SELECT COUNT(*) FROM sys_metric_page_binding WHERE page_path LIKE '/admin/basic-reports/%'").fetchone()[0]}


def main() -> None:
    args = [arg for arg in sys.argv[1:] if arg != "--dry-run"]
    path = Path(args[0]) if args else Path(config.DB_PATH)
    dry_run = "--dry-run" in sys.argv
    conn = sqlite3.connect(str(path)); conn.row_factory = sqlite3.Row
    if dry_run:
        clone = sqlite3.connect(":memory:"); conn.backup(clone); conn.close(); conn = clone
    result = migrate(conn)
    print(json.dumps({"database": str(path), "dryRun": dry_run, **result}, ensure_ascii=False, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
