"""幂等创建指标核验及映射专用表；不初始化、不重置学校业务数据。"""
from .config import load_environment
from .database import connection

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS sys_metric_verification_execution (
        execution_id VARCHAR(36) PRIMARY KEY, requirement_id VARCHAR(120) NOT NULL,
        metric_id VARCHAR(120) NOT NULL, query_id VARCHAR(160) NOT NULL,
        query_version VARCHAR(80) NOT NULL, query_checksum CHAR(64) NOT NULL,
        layer_name VARCHAR(20) NOT NULL, actor VARCHAR(120) NOT NULL,
        identity_id VARCHAR(200) NOT NULL, parameters_json LONGTEXT NOT NULL,
        result_json LONGTEXT NOT NULL, executed_at VARCHAR(40) NOT NULL,
        duration_ms BIGINT NOT NULL,
        INDEX idx_mv_execution_requirement (requirement_id, executed_at),
        INDEX idx_mv_execution_actor (actor, identity_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_metric_verification_record (
        record_id VARCHAR(36) PRIMARY KEY, requirement_id VARCHAR(120) NOT NULL,
        metric_id VARCHAR(120), judgment VARCHAR(30) NOT NULL, comment_text TEXT NOT NULL,
        evidence_json LONGTEXT NOT NULL, created_at VARCHAR(40) NOT NULL,
        created_by VARCHAR(120) NOT NULL, identity_id VARCHAR(200) NOT NULL,
        INDEX idx_mv_record_requirement (requirement_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_metric_mapping_revision (
        revision_id VARCHAR(36) PRIMARY KEY,
        project_id VARCHAR(120) NOT NULL,module_id VARCHAR(120) NOT NULL,environment_id VARCHAR(80) NOT NULL,
        package_id VARCHAR(160) NOT NULL,analysis_id VARCHAR(160) NOT NULL,
        base_revision_id VARCHAR(36),schema_version VARCHAR(30) NOT NULL,
        package_hash CHAR(64) NOT NULL,package_json LONGTEXT NOT NULL,
        validation_json LONGTEXT NOT NULL,bindings_json LONGTEXT NOT NULL,
        created_by VARCHAR(120) NOT NULL,created_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_mm_package(project_id,module_id,environment_id,package_id),
        INDEX idx_mm_analysis(project_id,module_id,environment_id,analysis_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_metric_mapping_head (
        project_id VARCHAR(120) NOT NULL,module_id VARCHAR(120) NOT NULL,environment_id VARCHAR(80) NOT NULL,
        revision_id VARCHAR(36),lock_version BIGINT NOT NULL DEFAULT 0,
        updated_by VARCHAR(120) NOT NULL,updated_at VARCHAR(40) NOT NULL,
        PRIMARY KEY(project_id,module_id,environment_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_metric_mapping_question (
        project_id VARCHAR(120) NOT NULL,module_id VARCHAR(120) NOT NULL,environment_id VARCHAR(80) NOT NULL,
        question_id VARCHAR(160) NOT NULL,semantic_key VARCHAR(240) NOT NULL,context_hash CHAR(64) NOT NULL,
        question_json LONGTEXT NOT NULL,answers_json LONGTEXT NOT NULL,status VARCHAR(30) NOT NULL,
        applied_revision_id VARCHAR(36),lock_version BIGINT NOT NULL DEFAULT 0,updated_at VARCHAR(40) NOT NULL,
        PRIMARY KEY(project_id,module_id,environment_id,question_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

EXTRA_COLUMNS = {
    "sys_metric_verification_execution": {"mapping_revision_id": "VARCHAR(36) NULL",
        "evidence_json": "LONGTEXT NULL", "independent_expectation_json": "LONGTEXT NULL"},
    "sys_metric_verification_record": {"mapping_revision_id": "VARCHAR(36) NULL"},
}


def migrate() -> None:
    with connection("application", write=True) as conn, conn.cursor() as cursor:
        for statement in STATEMENTS:
            cursor.execute(statement)
        for table, definitions in EXTRA_COLUMNS.items():
            cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
            existing = {row["COLUMN_NAME"].lower() for row in cursor.fetchall()}
            for column, declaration in definitions.items():
                if column not in existing:
                    cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {declaration}")


if __name__ == "__main__":
    load_environment()
    migrate()
    print("指标核验专用表已就绪；未修改源表或业务事实表。")
