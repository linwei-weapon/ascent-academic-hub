"""受控数据库读取。业务 SQL 仅来自仓库登记模板，客户端不能提交 SQL。"""
from contextlib import contextmanager
from decimal import Decimal
from datetime import date, datetime
import re

from backend.api.envelope import ApiError
from .config import database_config, query_timeout


@contextmanager
def connection(layer: str, *, write: bool = False, consistent: bool = False):
    config = database_config(layer)
    if not config.configured:
        raise ApiError("请先填写测试数据库连接配置", code=503, status_code=503)
    if write and layer == "source":
        raise ApiError("贴源连接禁止写入", code=403, status_code=403)
    conn = None
    try:
        if config.engine == "mysql":
            import pymysql
            kwargs = dict(host=config.host, port=config.port, user=config.user,
                          password=config.password, database=config.database, charset="utf8mb4",
                          connect_timeout=5, read_timeout=query_timeout() + 3,
                          write_timeout=5, autocommit=False,
                          cursorclass=pymysql.cursors.DictCursor)
            if config.ssl_ca:
                kwargs["ssl"] = {"ca": config.ssl_ca, "check_hostname": True}
            conn = pymysql.connect(**kwargs)
            with conn.cursor() as cursor:
                if not write:
                    cursor.execute("SET SESSION MAX_EXECUTION_TIME = %s", (query_timeout() * 1000,))
                    if consistent:
                        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                    else:
                        cursor.execute("START TRANSACTION READ ONLY")
        elif config.engine == "oracle" and not write:
            import oracledb
            conn = oracledb.connect(user=config.user, password=config.password,
                                   dsn=oracledb.makedsn(config.host, config.port, service_name=config.service_name))
            conn.call_timeout = query_timeout() * 1000
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
        else:
            raise ApiError("不支持的数据库类型；核验记录需要MySQL业务库", status_code=503)
        yield conn
        if write:
            conn.commit()
    finally:
        if conn is not None:
            if not write:
                conn.rollback()
            conn.close()


def json_value(value, *, precise: bool = False):
    if isinstance(value, Decimal):
        return str(value) if precise else float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def validate_sql(sql: str) -> str:
    clean = re.sub(r"--[^\n]*|/\*[\s\S]*?\*/", "", sql).strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", clean, re.I) or ";" in clean:
        raise ApiError("SQL登记必须是单条SELECT或只读CTE", status_code=422)
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|CALL|LOAD_FILE|SLEEP|BENCHMARK|INTO\s+(?:OUTFILE|DUMPFILE))\b", clean, re.I):
        raise ApiError("SQL登记包含不允许的操作", status_code=422)
    if re.search(r"\bFOR\s+(UPDATE|SHARE)\b|\bLOCK\s+IN\b", clean, re.I):
        raise ApiError("核验查询不能锁定业务记录", status_code=422)
    return clean


def bind_parameters(query: dict, supplied: dict) -> dict:
    definitions = {p["name"]: p for p in query.get("parameters", [])}
    extra = set(supplied) - set(definitions)
    if extra:
        raise ApiError("出现未登记的查询参数：" + "、".join(sorted(extra)), status_code=422)
    result = {}
    for name, definition in definitions.items():
        value = supplied.get(name)
        if value == "":
            value = None
        if definition.get("required") and value is None:
            raise ApiError("请填写参数：" + definition.get("label", name), status_code=422)
        if value is not None:
            kind = definition.get("type", "string")
            if kind == "integer":
                if isinstance(value, bool) or not re.fullmatch(r"-?\d+", str(value)):
                    raise ApiError("参数必须为整数：" + name, status_code=422)
                value = int(value)
            elif kind == "number":
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    raise ApiError("参数必须为数值：" + name, status_code=422) from None
                if value != value or abs(value) == float("inf"):
                    raise ApiError("数值参数无效：" + name, status_code=422)
            elif not isinstance(value, (str, int, float)) or len(str(value)) > 200:
                raise ApiError("参数类型或长度无效：" + name, status_code=422)
            else:
                value = str(value)
        result[name] = value
    sql_parameters = set(re.findall(r"(?<!:):([A-Za-z_][A-Za-z_0-9]*)", validate_sql(query["sql"])))
    if sql_parameters != set(definitions):
        raise ApiError("SQL占位符与参数登记不一致，暂不能执行", status_code=422)
    return result


def schema_mapping(conn, query: dict, engine: str) -> dict:
    expected = query.get("requiredColumns") or {}
    if not expected:
        raise ApiError("SQL缺少字段依赖登记，暂不能执行", status_code=422)
    if engine == "mysql":
        with conn.cursor() as cursor:
            cursor.execute("SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()")
            metadata = cursor.fetchall()
        columns = {}
        for row in metadata:
            columns.setdefault(row["TABLE_NAME"], set()).add(row["COLUMN_NAME"].lower())
    else:
        with conn.cursor() as cursor:
            cursor.execute("SELECT TABLE_NAME, COLUMN_NAME FROM USER_TAB_COLUMNS")
            metadata = cursor.fetchall()
        columns = {}
        for table, column in metadata:
            columns.setdefault(table, set()).add(column.lower())
    mapping, missing = {}, []
    for table, fields in expected.items():
        matches = [actual for actual in columns if actual.lower() == table.lower()]
        if len(matches) != 1:
            missing.append(table + "（表缺失或大小写不唯一）")
            continue
        actual = matches[0]
        mapping[table] = actual
        missing.extend(table + "." + col for col in fields if col.lower() not in columns[actual])
    if missing:
        raise ApiError("文档与当前数据库结构不一致：" + "、".join(missing[:20]), status_code=409)
    return mapping


def execute_read(conn, query: dict, parameters: dict, engine: str, limit: int, *, precise: bool = False) -> dict:
    sql = validate_sql(query["sql"])
    mapping = schema_mapping(conn, query, engine)
    quote = "`" if engine == "mysql" else '"'
    for registered, actual in sorted(mapping.items(), key=lambda item: -len(item[0])):
        sql = re.sub(r"(?i)(\b(?:FROM|JOIN)\s+)" + re.escape(registered) + r"\b",
                     lambda m: m.group(1) + quote + actual + quote, sql)
    if engine == "mysql":
        # Escape literal percent signs before creating PyMySQL's named bindings.
        sql = re.sub(r"(?<!:):([A-Za-z_][A-Za-z_0-9]*)", r"%(\1)s", sql.replace("%", "%%"))
    with conn.cursor() as cursor:
        cursor.execute(sql, parameters)
        columns = [str(d[0]) for d in cursor.description] if cursor.description else []
        raw = cursor.fetchmany(limit + 1)
        rows = [dict(row) if isinstance(row, dict) else dict(zip(columns, row)) for row in raw[:limit]]
    rows = [{k: json_value(v, precise=precise) for k, v in row.items()} for row in rows]
    metrics = rows[0] if query["kind"] in {"count", "calculate"} and len(rows) == 1 else {}
    count = next((value for key, value in metrics.items() if key.lower() == "matched_records"), None)
    registered_cap = re.search(r"(?:\bLIMIT\s+(\d+)|\bFETCH\s+FIRST\s+(\d+)\s+ROWS\s+ONLY)\s*$", sql, re.I)
    cap = int(next(value for value in registered_cap.groups() if value)) if registered_cap else None
    reached_cap = query["kind"] == "detail" and cap is not None and len(raw) >= cap
    return {"columns": columns, "rows": rows, "metrics": metrics,
            "recordCount": int(count) if count is not None else None,
            "truncated": len(raw) > limit or reached_cap, "returnedRows": len(rows)}
