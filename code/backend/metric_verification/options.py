"""Read parameter choices from the physical columns used by a registered query."""
import re

from .config import database_config
from .database import connection, schema_mapping, validate_sql

# Student identifiers are deliberately never enumerated. This endpoint only
# helps select dimensions and snapshot/rule versions already used by the SQL.
CHOICES = {
    "semester_id", "previous_semester_id", "organization_id", "college_id",
    "major_id", "course_id", "grade", "student_batch_id", "grade_batch_id",
    "course_batch_id", "alert_batch_id", "result_batch_id", "lesson_batch_id",
    "teacher_batch_id", "event_batch_id", "rule_version", "base_metric_id",
    "has_xue_ji_flag", "in_school_flag",
}

LABELS = {
    "source": {"semester_id": ("SEMESTER", "ID", "NAME_ZH"),
               "previous_semester_id": ("SEMESTER", "ID", "NAME_ZH"),
               "major_id": ("MAJOR", "ID", "NAME_ZH"),
               "course_id": ("COURSE", "ID", "NAME_ZH")},
    "analytics": {"semester_id": ("ACT_SEMESTER", "semester_id", "name_zh"),
                  "previous_semester_id": ("ACT_SEMESTER", "semester_id", "name_zh"),
                  "organization_id": ("ACT_ORGANIZATION", "organization_id", "name"),
                  "major_id": ("ACT_MAJOR", "major_id", "name_zh"),
                  "course_id": ("ACT_COURSE", "course_id", "name_zh")},
}


def choice_labels(conn, layer: str, name: str, values: list, engine: str) -> dict:
    definition = LABELS["source" if layer == "source" else "analytics"].get(name)
    if not values or not definition:
        return {}
    table, key, label = definition
    quote = "`" if engine == "mysql" else '"'
    try:
        mapping = schema_mapping(conn, {"requiredColumns": {table: [key, label]}}, engine)
        placeholders = ",".join("%s" if engine == "mysql" else f":v{i}" for i in range(len(values)))
        sql = (f"SELECT DISTINCT {quote}{key}{quote} AS option_key,{quote}{label}{quote} AS option_label "
               f"FROM {quote}{mapping[table]}{quote} WHERE {quote}{key}{quote} IN ({placeholders})")
        params = tuple(values) if engine == "mysql" else {f"v{i}": value for i, value in enumerate(values)}
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchmany(500)
        labels = {}
        for row in rows:
            value, title = list(row.values()) if isinstance(row, dict) else row
            if title:
                labels.setdefault(str(value), set()).add(str(title))
        return {value: " / ".join(sorted(titles)) for value, titles in labels.items()}
    except Exception:
        # Names are optional aids, never a substitute for the actual key.
        return {}


def parameter_columns(query: dict) -> dict:
    sql = validate_sql(query["sql"])
    required = {table.lower(): (table, {c.lower(): c for c in columns})
                for table, columns in query.get("requiredColumns", {}).items()}
    aliases = {}
    for table, alias in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)\s+(\w+)", sql, re.I):
        if table.lower() in required:
            aliases.setdefault(alias.lower(), []).append(required[table.lower()])
    found = {}
    for alias, column, name in re.findall(r"\b(\w+)\.(\w+)\s*=\s*:(\w+)\b", sql):
        if name not in CHOICES:
            continue
        candidates = [(table, columns[column.lower()]) for table, columns in aliases.get(alias.lower(), [])
                      if column.lower() in columns]
        if len(set(candidates)) == 1:
            found.setdefault(name, candidates[0])
    # Numeric business keys in mixed-schema environments are explicitly cast by
    # the registered SQL. Only inspect those same declared aliases and columns.
    for alias, column, name in re.findall(r"\bCAST\(\s*(\w+)\.(\w+)\s+AS\s+\w+(?:\s*\([0-9, ]+\))?\s*\)\s*=\s*:(\w+)\b", sql, re.I):
        if name not in CHOICES:
            continue
        candidates = [(table, columns[column.lower()]) for table, columns in aliases.get(alias.lower(), [])
                      if column.lower() in columns]
        if len(set(candidates)) == 1:
            found.setdefault(name, candidates[0])
    return {p["name"]: found[p["name"]] for p in query.get("parameters", []) if p["name"] in found}


def parameter_options(query: dict) -> dict:
    fields = parameter_columns(query)
    result = {}
    if not fields:
        return {"parameters": result}
    engine = database_config(query["layer"]).engine
    quote = "`" if engine == "mysql" else '"'
    with connection(query["layer"]) as conn:
        mapping = schema_mapping(conn, query, engine)
        for name, (table, column) in fields.items():
            # Both identifiers originate in the registered dependency manifest,
            # and the table name has just been checked against DB metadata.
            if not all(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value) for value in (mapping[table], column)):
                continue
            identifier = f"{quote}{column}{quote}"
            suffix = "LIMIT 101" if engine == "mysql" else "FETCH FIRST 101 ROWS ONLY"
            sql = (f"SELECT DISTINCT {identifier} AS option_value FROM {quote}{mapping[table]}{quote} "
                   f"WHERE {identifier} IS NOT NULL ORDER BY {identifier} DESC {suffix}")
            item = {"items": [], "truncated": False, "source": f"{table}.{column}（字段可选值，非已确认统计范围）"}
            try:
                with conn.cursor() as cursor:
                    cursor.execute(sql)
                    rows = cursor.fetchmany(101)
                values = [next(iter(row.values())) if isinstance(row, dict) else row[0] for row in rows]
                labels = choice_labels(conn, query["layer"], name, values[:100], engine)
                item["items"] = [{"value": str(value), "label": f"{labels[str(value)]} · {value}" if str(value) in labels else str(value)} for value in values[:100]]
                item["truncated"] = len(values) > 100
            except Exception:
                item["error"] = "可选值读取失败或超时，可手工填写已知参数。"
            result[name] = item
    return {"parameters": result}
