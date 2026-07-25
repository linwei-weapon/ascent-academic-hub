"""数据采集监控的声明式数据源目录与运行—批次关联治理。

目录属于平台接入配置，不是学校业务主数据。原型以版本化代码清单交付，生产系统
可等价映射到数据中台的数据源注册接口。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable


CATALOG_VERSION = "2026.07-v1"


def _source(code: str, name: str, domain_code: str, domain_name: str,
            source_system: str, update_cycle: str, freshness_days: int,
            required_fields: str, downstream: list[str], management_use: str,
            sort_order: int, delivery_mode: str = "文件或API") -> dict:
    return {
        "source_code": code,
        "source_name": name,
        "domain_code": domain_code,
        "domain_name": domain_name,
        "source_system": source_system,
        "delivery_mode": delivery_mode,
        "update_cycle": update_cycle,
        "freshness_days": freshness_days,
        "required_fields": required_fields,
        "downstream_modules": downstream,
        "management_use": management_use,
        "sort_order": sort_order,
    }


SOURCE_DEFINITIONS = [
    _source("organization", "组织机构", "master", "基础主数据", "教务系统",
            "按学期或组织变化后", 180, "组织代码、组织名称、组织层级、有效期",
            ["教学数据总览", "培养质量分析", "师资保障分析"],
            "保证学院、专业和开课单位能够统一归属。", 10),
    _source("semester", "学年学期代码", "master", "基础主数据", "教务系统",
            "每学期", 180, "学期代码、学年、学期序号、起止日期",
            ["全部教学管理分析"], "统一时间窗口和学期排序。", 20),
    _source("building", "楼宇信息", "master", "基础主数据", "教务系统/房产系统",
            "按学期或楼宇变化后", 180, "楼宇代码、楼宇名称、校区、状态",
            ["教学运行分析"], "支持教室占用按楼宇归集和核查。", 30),
    _source("room", "教室信息", "master", "基础主数据", "教务系统/房产系统",
            "按学期或教室变化后", 180, "教室代码、名称、楼宇、座位数、状态",
            ["教学运行分析"], "提供教室资源和占用分析的基础空间维度。", 40),
    _source("period", "课表时间", "master", "基础主数据", "教务系统",
            "每学期", 180, "节次、开始时间、结束时间、时间段",
            ["教学运行分析"], "统一早中晚和节次热力图的时间切分。", 50),
    _source("course", "课程信息", "master", "基础主数据", "教务系统",
            "每学期", 180, "课程代码、名称、类别、学分、管理院系",
            ["教学运行分析", "培养质量分析", "学生成长与学业分析"],
            "保证成绩、方案和开课事实能够关联到同一课程。", 60),
    _source("student_current", "当前学籍与方案绑定", "student", "学籍与培养方案",
            "学籍系统", "每月或学籍变化后", 45,
            "学号、年级、学院、专业、行政班、学籍状态、培养方案",
            ["教学数据总览", "学业预警监控", "培养质量分析", "学生成长与学业分析"],
            "确定当前在校学生范围、组织归属和培养方案。", 110),
    _source("plan_course", "培养方案课程", "student", "学籍与培养方案",
            "教务系统", "方案发布或修订后", 365,
            "方案、课程、模块、必选属性、学分、建议学期",
            ["培养质量分析", "毕业准备核查"],
            "支撑学生应修课程、模块要求和毕业准备判断。", 120),
    _source("student_history", "历史学籍与毕业结果", "student", "学籍与培养方案",
            "学籍系统", "每学期", 180,
            "学号、历史专业、学籍状态、毕业结论、学位结果",
            ["学生成长与学业分析", "培养质量分析"],
            "支撑历史成长、毕业结果和同类群体分析。", 130),
    _source("student_change", "学籍异动", "student", "学籍与培养方案",
            "学籍系统", "每月或异动生效后", 45,
            "学号、异动类型、生效时间、异动前后组织与状态",
            ["学生成长与学业分析", "学业预警监控"],
            "解释学生组织、专业和学籍状态变化。", 140),
    _source("grade", "成绩明细", "achievement", "成绩与课程结果", "教务系统",
            "成绩发布后", 45,
            "学号、课程、学期、成绩、通过状态、修读类型、发布状态",
            ["教学数据总览", "学业预警监控", "培养质量分析", "学生成长与学业分析"],
            "形成课程结果、挂科、GPA和预警分析事实。", 210),
    _source("legacy_grade", "历史成绩桥接", "achievement", "成绩与课程结果",
            "历史分析库", "基线建设或历史库更新后", 365,
            "学生、课程、学期、成绩、通过状态、修读类型",
            ["培养质量分析", "学生成长与学业分析"],
            "补充当前结构化方案学生的历史修读证据。", 220),
    _source("substitution", "课程替代", "achievement", "成绩与课程结果",
            "教务系统", "每月或流程完成后", 45,
            "学号、原课程、替代课程、审核结果、完成时间",
            ["培养质量分析", "毕业准备核查"],
            "避免课程替代后重复计算缺修和学分缺口。", 230),
    _source("teacher", "教师基本信息", "teaching", "教学任务与师资",
            "人事系统/教务系统", "每学期或人员变化后", 180,
            "工号、姓名、所属部门、职称、教师类型、在职状态",
            ["师资保障分析", "教学运行分析"],
            "支撑课程团队结构、教师负荷和授课资源核查。", 310),
    _source("class_adviser", "行政班班主任关系", "teaching", "教学任务与师资",
            "学工或教务系统", "每学期或带班关系变化后", 180,
            "行政班、班主任、所属院系、关系有效期",
            ["学业预警监控", "学生成长与学业分析"],
            "确定班主任能够核查的学生范围。", 320),
    _source("student_adviser", "学生导师关系", "teaching", "教学任务与师资",
            "导师管理系统", "每学期或指导关系变化后", 180,
            "学号、导师工号、导师类型、有效期、发布状态",
            ["学业预警监控", "学生成长与学业分析"],
            "确定导师能够核查的学生范围。", 330),
    _source("lesson", "教学任务与排课", "teaching", "教学任务与师资",
            "教务系统", "每学期及调课后", 180,
            "教学班、课程、开课单位、授课教师、人数、学时、上课时空",
            ["教学运行分析", "师资保障分析"],
            "支撑开课供给、排课分布、教师负荷和课程团队分析。", 340),
    _source("room_occupancy", "实际教室占用", "resource", "教室占用",
            "教室预约/排课系统", "每学期或每日增量", 180,
            "教室、日期、起止时间、活动类型、学期",
            ["教学运行分析", "排课策略与资源优化"],
            "识别已观测教室的时段负荷、晚间占用和空间冲突。", 410),
]


TASK_SOURCE_CODES = {
    "v2_master_loader": (
        "organization", "semester", "building", "room", "period", "course",
    ),
    "v2_student_plan_loader": ("student_current", "plan_course"),
    "v2_history_loader": ("student_history", "student_change"),
    "v2_grade_loader": ("grade", "substitution"),
    "v2_legacy_grade_bridge": ("legacy_grade",),
    "v2_teaching_loader": (
        "teacher", "class_adviser", "student_adviser", "lesson",
    ),
    "room_occupancy_loader": ("room_occupancy",),
    "v2_course_pass_builder": ("grade", "legacy_grade", "substitution"),
}


CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS data_source_definition (
    source_code TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    domain_code TEXT NOT NULL,
    domain_name TEXT NOT NULL,
    source_system TEXT NOT NULL,
    delivery_mode TEXT NOT NULL,
    update_cycle TEXT NOT NULL,
    freshness_days INTEGER NOT NULL,
    required_fields TEXT NOT NULL,
    downstream_modules_json TEXT NOT NULL,
    management_use TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    catalog_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS etl_run_batch (
    run_id INTEGER NOT NULL,
    batch_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'input',
    PRIMARY KEY(run_id,batch_id,relation_type)
);
CREATE INDEX IF NOT EXISTS idx_data_batch_source_ingested
ON data_batch(source_code,ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_batch_quality
ON data_batch(quality_status,ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_etl_run_batch_batch
ON etl_run_batch(batch_id,run_id DESC);
"""


def link_run_batches(conn: sqlite3.Connection, run_id: int,
                     batch_ids: Iterable[str],
                     relation_type: str = "input") -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO etl_run_batch(run_id,batch_id,relation_type)"
        " VALUES(?,?,?)",
        [(run_id, batch_id, relation_type)
         for batch_id in dict.fromkeys(batch_ids) if batch_id],
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone())


def _mirror_room_occupancy(v2: sqlite3.Connection,
                           legacy: sqlite3.Connection | None) -> int:
    if legacy is None or not _table_exists(legacy, "etl_room_occupancy_batch"):
        return 0
    rows = legacy.execute("""
        SELECT import_batch_id,source_file,source_sha256,imported_at,
               source_rows,loaded_rows,invalid_rows,pending_building_rows
        FROM etl_room_occupancy_batch
    """).fetchall()
    for row in rows:
        values = tuple(row)
        status = "warning" if int(values[7] or 0) or int(values[6] or 0) else "accepted"
        v2.execute("""
            INSERT INTO data_batch(
              batch_id,source_code,source_file,file_hash,ingested_at,row_count,
              accepted_count,rejected_count,quality_status
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(batch_id) DO UPDATE SET
              source_file=excluded.source_file,file_hash=excluded.file_hash,
              ingested_at=excluded.ingested_at,row_count=excluded.row_count,
              accepted_count=excluded.accepted_count,
              rejected_count=excluded.rejected_count,
              quality_status=excluded.quality_status
        """, (
            values[0], "room_occupancy", values[1], values[2], values[3],
            values[4], values[5], values[6], status,
        ))
    return len(rows)


def _backfill_run_batches(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "etl_run"):
        return 0
    before = conn.execute("SELECT COUNT(*) FROM etl_run_batch").fetchone()[0]
    for run_id, task in conn.execute("SELECT run_id,task FROM etl_run"):
        for source_code in TASK_SOURCE_CODES.get(task, ()):
            row = conn.execute("""
                SELECT batch_id FROM data_batch WHERE source_code=?
                ORDER BY ingested_at DESC,batch_id DESC LIMIT 1
            """, (source_code,)).fetchone()
            if row:
                link_run_batches(conn, int(run_id), [row[0]])
    after = conn.execute("SELECT COUNT(*) FROM etl_run_batch").fetchone()[0]
    return int(after - before)


def ensure_data_collection_catalog(
        conn: sqlite3.Connection,
        legacy_conn: sqlite3.Connection | None = None) -> dict:
    conn.executescript(CATALOG_DDL)
    for item in SOURCE_DEFINITIONS:
        conn.execute("""
            INSERT INTO data_source_definition(
              source_code,source_name,domain_code,domain_name,source_system,
              delivery_mode,update_cycle,freshness_days,required_fields,
              downstream_modules_json,management_use,sort_order,active,
              catalog_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?)
            ON CONFLICT(source_code) DO UPDATE SET
              source_name=excluded.source_name,
              domain_code=excluded.domain_code,
              domain_name=excluded.domain_name,
              source_system=excluded.source_system,
              delivery_mode=excluded.delivery_mode,
              update_cycle=excluded.update_cycle,
              freshness_days=excluded.freshness_days,
              required_fields=excluded.required_fields,
              downstream_modules_json=excluded.downstream_modules_json,
              management_use=excluded.management_use,
              sort_order=excluded.sort_order,
              active=1,catalog_version=excluded.catalog_version
        """, (
            item["source_code"], item["source_name"], item["domain_code"],
            item["domain_name"], item["source_system"], item["delivery_mode"],
            item["update_cycle"], item["freshness_days"],
            item["required_fields"],
            json.dumps(item["downstream_modules"], ensure_ascii=False),
            item["management_use"], item["sort_order"], CATALOG_VERSION,
        ))
    source_codes = [item["source_code"] for item in SOURCE_DEFINITIONS]
    placeholders = ",".join("?" for _ in source_codes)
    conn.execute(
        f"UPDATE data_source_definition SET active=0 "
        f"WHERE source_code NOT IN ({placeholders})",
        tuple(source_codes),
    )
    mirrored = _mirror_room_occupancy(conn, legacy_conn)
    links_added = _backfill_run_batches(conn)
    conn.commit()
    return {
        "catalogVersion": CATALOG_VERSION,
        "sourceDefinitions": conn.execute(
            "SELECT COUNT(*) FROM data_source_definition WHERE active=1"
        ).fetchone()[0],
        "mirroredRoomBatches": mirrored,
        "runBatchLinks": conn.execute(
            "SELECT COUNT(*) FROM etl_run_batch"
        ).fetchone()[0],
        "linksAdded": links_added,
    }
