"""系统设置组：预警规则 + 角色权限。算自 sys_alert_rule / sys_role / sys_user /
sys_role_menu+sys_menu。

预警规则参数为结构化阈值：每条规则对外暴露的「变量」即引擎 alert_engine.py 实际
消费的阈值字段（见 RULE_PARAM_CATALOG），运算符与引擎逻辑绑定（只读展示），仅数值
可改。规则集固定为引擎内置的 5 条（R1~R4、R6），不支持任意增删——避免"参数可填但
引擎不认"的假配置。阈值修改持久化到 sys_alert_rule.params，下次数据重算时生效。
"""
import json
import sqlite3
import hashlib
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from .. import db as dbm
from ..deps import get_db, get_db_rw, get_current_user, require_admin
from ..envelope import ok, ApiError
from ..permission_context import has_action

router = APIRouter(prefix="/api/admin", tags=["settings"])

# 每条规则对外暴露的可编辑阈值（key 必须是 alert_engine.py 真正读取的字段）。
# op 为引擎固定的比较方向，仅展示不可改；value 由 sys_alert_rule.params 现取。
RULE_PARAM_CATALOG = {
    "R1": [{"key": "gpa_drop", "label": "近2~3学期GPA累计降幅", "op": ">",
            "unit": "", "min": 0.1, "max": 2.0, "step": 0.1}],
    "R2": [{"key": "fail_courses", "label": "近2学期累计挂科(含重修)", "op": "≥",
            "unit": "门", "min": 1, "max": 20, "step": 1}],
    "R3": [{"key": "credit_gap", "label": "已修较期望进度学分缺口", "op": ">",
            "unit": "学分", "min": 1, "max": 60, "step": 1}],
    "R4": [{"key": "core_fail", "label": "专业必修(核心)课近2学期挂科", "op": "≥",
            "unit": "门", "min": 1, "max": 10, "step": 1}],
    "R6": [{"key": "gpa_below", "label": "本学期GPA", "op": "<",
            "unit": "", "min": 0.5, "max": 5.0, "step": 0.1},
           {"key": "fail_courses", "label": "近2学期挂科", "op": "≥",
            "unit": "门", "min": 1, "max": 20, "step": 1}],
}

GOVERNANCE_DDL = """
CREATE TABLE IF NOT EXISTS alert_rule_change (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    base_params TEXT NOT NULL,
    proposed_params TEXT NOT NULL,
    base_enabled INTEGER NOT NULL,
    proposed_enabled INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    reason TEXT NOT NULL,
    impact_json TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_comment TEXT,
    published_by TEXT,
    published_at TEXT,
    previous_snapshot TEXT
);
CREATE INDEX IF NOT EXISTS idx_rule_change_status
ON alert_rule_change(status, created_at);
CREATE TABLE IF NOT EXISTS alert_rule_change_candidate (
    change_id INTEGER NOT NULL,
    student_id TEXT NOT NULL,
    action TEXT NOT NULL,
    level TEXT,
    trigger_detail TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (change_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_rule_change_candidate_action
ON alert_rule_change_candidate(change_id, action);
CREATE TABLE IF NOT EXISTS alert_rule_change_activation (
    activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id INTEGER NOT NULL UNIQUE,
    rule_id TEXT NOT NULL,
    retained_count INTEGER NOT NULL,
    new_count INTEGER NOT NULL,
    exited_count INTEGER NOT NULL,
    activated_by TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS sys_rule_governance_permission (
    role_id TEXT NOT NULL,
    permission TEXT NOT NULL,
    PRIMARY KEY (role_id, permission)
);
"""


def _ensure_governance(conn: sqlite3.Connection) -> None:
    conn.executescript(GOVERNANCE_DDL)
    conn.executemany("""INSERT OR IGNORE INTO sys_rule_governance_permission
        (role_id,permission) VALUES (?,?)""", [
        ("dean", "edit"), ("dean", "publish"), ("dean", "audit"),
        ("quality_office", "review"), ("quality_office", "audit"),
        ("school_leader", "activate"), ("school_leader", "audit"),
    ])
    event_cols = {r["name"] if isinstance(r, sqlite3.Row) else r[1]
                  for r in conn.execute("PRAGMA table_info(alert_event)")}
    for name, definition in {
        "cycle_no": "INTEGER NOT NULL DEFAULT 1",
        "recurrence_of_event_id": "INTEGER",
        "cycle_reason": "TEXT",
    }.items():
        if name not in event_cols:
            conn.execute(f"ALTER TABLE alert_event ADD COLUMN {name} {definition}")


def _rule_permissions(conn: sqlite3.Connection, user: dict) -> set[str]:
    _ensure_governance(conn)
    return {r["permission"] for r in dbm.query(conn, """SELECT permission
        FROM sys_rule_governance_permission WHERE role_id=?""", (user["role_id"],))}


def _require_rule_permission(conn: sqlite3.Connection, user: dict, permission: str) -> None:
    if permission not in _rule_permissions(conn, user):
        raise ApiError(f"当前角色缺少规则治理权限：{permission}", code=403, status_code=403)


def _validate_values(rule_id: str, current: dict, values: dict | None) -> dict:
    params = dict(current)
    if values:
        catalog = {c["key"]: c for c in RULE_PARAM_CATALOG[rule_id]}
        for key, value in values.items():
            spec = catalog.get(key)
            if not spec:
                raise ApiError(f"无效的规则参数：{key}", code=400, status_code=400)
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ApiError(f"参数 {key} 必须为数值", code=400, status_code=400)
            if number < float(spec["min"]) or number > float(spec["max"]):
                raise ApiError(
                    f"参数 {key} 必须在 {spec['min']}~{spec['max']} 之间",
                    code=400, status_code=400)
            params[key] = int(number) if float(spec["step"]).is_integer() else round(number, 2)
    params["text"] = _gen_text(rule_id, params)
    return params


def _data_snapshot(conn: sqlite3.Connection) -> dict:
    """生成规则试算所依赖数据的轻量、确定性快照。"""
    grade = dbm.query_one(conn, """SELECT COUNT(*) rows,
        COALESCE(SUM(CASE WHEN score IS NOT NULL THEN CAST(score*100 AS INTEGER) ELSE 0 END),0) score_sum,
        COALESCE(SUM(CASE WHEN is_pass=1 THEN 1 ELSE 0 END),0) pass_rows,
        COALESCE(MAX(semester_id),'') max_semester FROM fact_grade""") or {}
    plan = dbm.query_one(conn, """SELECT COUNT(*) rows,
        COALESCE(SUM(CAST(COALESCE(credits,0)*100 AS INTEGER)),0) credit_sum,
        COALESCE(SUM(CASE WHEN is_core=1 THEN 1 ELSE 0 END),0) core_rows
        FROM fact_plan_course""") or {}
    snapshot = {
        "currentSemester": dbm.scalar(conn,
            "SELECT semester_id FROM dim_semester ORDER BY semester_id DESC LIMIT 1") or "",
        "gradeRows": grade.get("rows", 0), "gradeScoreChecksum": grade.get("score_sum", 0),
        "gradePassRows": grade.get("pass_rows", 0), "gradeMaxSemester": grade.get("max_semester", ""),
        "studentRows": dbm.scalar(conn, "SELECT COUNT(*) FROM dim_student") or 0,
        "planRows": plan.get("rows", 0), "planCreditChecksum": plan.get("credit_sum", 0),
        "planCoreRows": plan.get("core_rows", 0),
    }
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot["fingerprint"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return snapshot


def _require_fresh_impact(conn: sqlite3.Connection, row: dict) -> dict:
    try:
        impact = json.loads(row["impact_json"] or "{}")
    except Exception:
        impact = {}
    if impact.get("candidateStatus") != "evaluated":
        raise ApiError("缺少有效的规则影响试算结果", code=400, status_code=400)
    expected = impact.get("dataFingerprint")
    current = _data_snapshot(conn)
    if not expected or expected != current["fingerprint"]:
        raise ApiError("试算使用的基础数据已经变化，请重新执行影响试算",
                       code=409, status_code=409)
    return impact


def _fmt_value(v: float) -> str:
    """整数去小数尾巴，浮点保留原样。"""
    return str(int(v)) if float(v).is_integer() else str(v)


def _build_conditions(rule_id: str, params: dict) -> list[dict]:
    """按 catalog 取每个可编辑变量的当前值，补全展示元信息。"""
    out = []
    for c in RULE_PARAM_CATALOG.get(rule_id, []):
        out.append({**c, "value": params.get(c["key"])})
    return out


def _discovered_conditions(conn: sqlite3.Connection, rule_id: str) -> list[dict]:
    """从自发现建议保留原始运算符，避免只凭参数符号猜测展示口径。"""
    if not rule_id.startswith("DR") or not rule_id[2:].isdigit():
        return []
    raw = dbm.scalar(conn, "SELECT conditions FROM sys_discovered_rule WHERE id=?",
                     (int(rule_id[2:]),))
    try:
        return json.loads(raw or "[]")
    except Exception:
        return []


def _gen_text(rule_id: str, params: dict) -> str:
    """由阈值现拼展示文案，与引擎实际判定一致。"""
    parts = []
    for c in RULE_PARAM_CATALOG.get(rule_id, []):
        v = params.get(c["key"])
        if v is None:
            continue
        parts.append(f"{c['label']}{c['op']}{_fmt_value(v)}{c['unit']}")
    joiner = " 且 " if rule_id == "R6" else "·"
    return joiner.join(parts) if parts else (params.get("text", "") or "")


@router.get("/settings")
def settings(conn: sqlite3.Connection = Depends(get_db),
            user: dict = Depends(get_current_user)):
    # 预警规则（结构化阈值）
    rules = []
    for r in dbm.query(conn, """
        SELECT rule_id, name, level, trigger_type, params, enabled
        FROM sys_alert_rule ORDER BY rule_id"""):
        try:
            params = json.loads(r["params"]) if r["params"] else {}
        except Exception:
            params = {}
        conditions = (_discovered_conditions(conn, r["rule_id"])
                      if r["trigger_type"] == "discovered"
                      else _build_conditions(r["rule_id"], params))
        rules.append({
            "id": r["rule_id"], "name": r["name"], "level": r["level"],
            "triggerType": r["trigger_type"],
            "conditions": conditions,
            "params": _gen_text(r["rule_id"], params),
            "editable": r["rule_id"] in RULE_PARAM_CATALOG,
            "enabled": bool(r["enabled"])})

    # 角色权限：账号数 + 可访问页面（角色可见菜单标题）
    cnt_by_role = {r["role_id"]: r["n"] for r in dbm.query(
        conn, "SELECT role_id, COUNT(*) n FROM sys_user GROUP BY role_id")}
    pages_by_role: dict = {}
    for r in dbm.query(conn, """
        SELECT rm.role_id, m.title FROM sys_role_menu rm
        JOIN sys_menu m ON rm.menu_id=m.menu_id ORDER BY m.sort_order"""):
        pages_by_role.setdefault(r["role_id"], []).append(r["title"])
    scope_label = {"all": "全校全部数据", "college": "本院数据",
                   "major": "本专业数据", "grade": "本年级数据", "class": "本班级数据"}
    roleData = []
    for r in dbm.query(conn,
                       "SELECT role_id, name, data_scope_type FROM sys_role ORDER BY role_id"):
        roleData.append({
            "role": r["name"], "count": cnt_by_role.get(r["role_id"], 0),
            "dataScope": scope_label.get(r["data_scope_type"], r["data_scope_type"] or "—"),
            "pages": "·".join(pages_by_role.get(r["role_id"], [])) or "—"})

    return ok({"rules": rules, "roleData": roleData})


class RuleUpdateIn(BaseModel):
    enabled: bool | None = None
    values: dict[str, float] | None = None  # {param_key: 新阈值}


@router.put("/settings/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleUpdateIn,
                _: dict = Depends(require_admin),
                conn: sqlite3.Connection = Depends(get_db_rw)):
    """更新单条预警规则的阈值/启用状态。仅接受 catalog 内的变量键，按 min/max 夹取。
    阈值改后下次数据重算（ETL）时由引擎按新值判定。"""
    raise ApiError(
        "直接更新规则接口已停用，请通过规则变更单完成试算、审核和发布",
        code=410, status_code=410)
    row = dbm.query_one(conn,
                        "SELECT params, enabled FROM sys_alert_rule WHERE rule_id=?", (rule_id,))
    if not row:
        raise ApiError("规则不存在", code=404, status_code=404)
    if rule_id not in RULE_PARAM_CATALOG:
        raise ApiError("该规则不支持配置", code=400, status_code=400)

    try:
        params = json.loads(row["params"]) if row["params"] else {}
    except Exception:
        params = {}

    if body.values:
        catalog = {c["key"]: c for c in RULE_PARAM_CATALOG[rule_id]}
        for k, v in body.values.items():
            c = catalog.get(k)
            if not c:
                raise ApiError(f"无效的规则参数：{k}", code=400, status_code=400)
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ApiError(f"参数 {k} 必须为数值", code=400, status_code=400)
            fv = max(float(c["min"]), min(float(c["max"]), fv))
            params[k] = int(fv) if float(c["step"]).is_integer() else round(fv, 2)

    params["text"] = _gen_text(rule_id, params)
    enabled = row["enabled"] if body.enabled is None else int(body.enabled)
    dbm.execute(conn, "UPDATE sys_alert_rule SET params=?, enabled=? WHERE rule_id=?",
                (json.dumps(params, ensure_ascii=False), enabled, rule_id))
    return ok({"id": rule_id,
               "conditions": _build_conditions(rule_id, params),
               "params": _gen_text(rule_id, params),
               "enabled": bool(enabled)},
              msg="规则已更新，下次数据重算时生效")


class RuleChangeCreateIn(BaseModel):
    enabled: bool | None = None
    values: dict[str, float] | None = None
    reason: str


class RuleChangeReviewIn(BaseModel):
    action: str
    comment: str | None = None


def _change_item(row: dict) -> dict:
    def load(value, fallback):
        try:
            return json.loads(value) if value else fallback
        except Exception:
            return fallback
    return {
        "changeId": row["change_id"], "ruleId": row["rule_id"],
        "status": row["status"], "reason": row["reason"],
        "baseParams": load(row["base_params"], {}),
        "proposedParams": load(row["proposed_params"], {}),
        "baseEnabled": bool(row["base_enabled"]),
        "proposedEnabled": bool(row["proposed_enabled"]),
        "impact": load(row.get("impact_json"), {}),
        "createdBy": row["created_by"], "createdAt": row["created_at"],
        "submittedAt": row.get("submitted_at"),
        "reviewedBy": row.get("reviewed_by"),
        "reviewedAt": row.get("reviewed_at"),
        "reviewComment": row.get("review_comment"),
        "publishedBy": row.get("published_by"),
        "publishedAt": row.get("published_at"),
    }


@router.post("/settings/rules/{rule_id}/changes")
def create_rule_change(rule_id: str, body: RuleChangeCreateIn,
                       user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db_rw)):
    """创建规则变更草稿；不修改生产规则。"""
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "edit")
    if rule_id not in RULE_PARAM_CATALOG:
        raise ApiError("该规则不支持配置治理", code=400, status_code=400)
    row = dbm.query_one(conn, "SELECT * FROM sys_alert_rule WHERE rule_id=?", (rule_id,))
    if not row:
        raise ApiError("规则不存在", code=404, status_code=404)
    reason = body.reason.strip()
    if len(reason) < 5:
        raise ApiError("变更原因至少填写5个字符", code=400, status_code=400)
    try:
        current = json.loads(row["params"] or "{}")
    except Exception:
        current = {}
    proposed = _validate_values(rule_id, current, body.values)
    proposed_enabled = row["enabled"] if body.enabled is None else int(body.enabled)
    if proposed == current and proposed_enabled == row["enabled"]:
        raise ApiError("变更内容与当前生产规则相同", code=400, status_code=400)
    open_change = dbm.query_one(conn, """SELECT change_id FROM alert_rule_change
        WHERE rule_id=? AND status IN ('draft','submitted','approved')""", (rule_id,))
    if open_change:
        raise ApiError("该规则已有未完成的变更单", code=409, status_code=409)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    current_hits = dbm.scalar(conn, """SELECT COUNT(DISTINCT student_id) FROM fact_alert
        WHERE rule_id=? AND COALESCE(is_active,1)=1""", (rule_id,)) or 0
    impact = {"currentStudents": current_hits, "candidateStatus": "pending",
              "note": "发布前必须完成候选试算"}
    cur = dbm.execute(conn, """INSERT INTO alert_rule_change
        (rule_id,base_params,proposed_params,base_enabled,proposed_enabled,status,
         reason,impact_json,created_by,created_at)
        VALUES (?,?,?,?,?,'draft',?,?,?,?)""",
        (rule_id, json.dumps(current, ensure_ascii=False),
         json.dumps(proposed, ensure_ascii=False), row["enabled"], proposed_enabled,
         reason, json.dumps(impact, ensure_ascii=False), user["username"], now))
    created = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?",
                            (cur.lastrowid,))
    return ok(_change_item(created), msg="规则变更草稿已创建，生产规则未改变")


@router.get("/settings/rule-changes")
def list_rule_changes(status: str | None = None,
                      user: dict = Depends(get_current_user),
                      conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "audit")
    if status:
        rows = dbm.query(conn, """SELECT * FROM alert_rule_change WHERE status=?
            ORDER BY change_id DESC""", (status,))
    else:
        rows = dbm.query(conn, "SELECT * FROM alert_rule_change ORDER BY change_id DESC")
    current_fp = _data_snapshot(conn)["fingerprint"]
    items = []
    for row in rows:
        item = _change_item(row)
        item["isFresh"] = bool(item["impact"].get("dataFingerprint") == current_fp)
        items.append(item)
    return ok(items)


@router.get("/settings/rule-permissions/me")
def my_rule_permissions(user: dict = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db_rw)):
    permissions = sorted(_rule_permissions(conn, user))
    return ok({"roleId": user["role_id"], "permissions": permissions})


@router.post("/settings/rule-changes/{change_id}/evaluate")
def evaluate_rule_change(change_id: int, user: dict = Depends(get_current_user),
                         conn: sqlite3.Connection = Depends(get_db_rw)):
    """使用生产规则引擎在内存中试算拟调整参数，不写入事实预警表。"""
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "edit")
    row = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?", (change_id,))
    if not row or row["status"] != "draft":
        raise ApiError("仅草稿状态可以执行影响试算", code=400, status_code=400)
    try:
        import pandas as pd
        from backend.etl.alert_engine import run_engine
        grade = pd.read_sql("SELECT * FROM fact_grade", conn)
        students = pd.read_sql("SELECT * FROM dim_student", conn)
        courses = pd.read_sql("SELECT * FROM dim_course", conn)
        plan_meta = pd.read_sql("SELECT * FROM fact_plan_meta", conn)
        plan_course = pd.read_sql("SELECT * FROM fact_plan_course", conn)
        rules = pd.read_sql("SELECT * FROM sys_alert_rule", conn)
        mask = rules["rule_id"] == row["rule_id"]
        rules.loc[mask, "params"] = row["proposed_params"]
        rules.loc[mask, "enabled"] = row["proposed_enabled"]
        candidate_df = run_engine(grade, students, courses, plan_meta, rules, plan_course)
    except Exception as exc:
        raise ApiError(f"规则影响试算失败：{exc}", code=500, status_code=500)

    target_df = candidate_df.loc[candidate_df["rule_id"] == row["rule_id"]].copy()
    target_df["student_id"] = target_df["student_id"].astype(str)
    proposed = set(target_df["student_id"])
    current = {str(r["student_id"]) for r in dbm.query(conn, """
        SELECT DISTINCT student_id FROM fact_alert
        WHERE rule_id=? AND COALESCE(is_active,1)=1""", (row["rule_id"],))}
    snapshot = _data_snapshot(conn)
    impact = {
        "currentStudents": len(current), "candidateStudents": len(proposed),
        "retainedStudents": len(current & proposed),
        "newStudents": len(proposed - current),
        "exitedStudents": len(current - proposed),
        "netChange": len(proposed) - len(current),
        "candidateStatus": "evaluated",
        "evaluatedBy": user["username"],
        "evaluatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataFingerprint": snapshot["fingerprint"],
        "dataSnapshot": snapshot,
    }
    details = {str(r["student_id"]): (r.get("level"), r.get("trigger_detail"))
               for _, r in target_df.iterrows()}
    conn.execute("DELETE FROM alert_rule_change_candidate WHERE change_id=?", (change_id,))
    candidate_rows = []
    for sid in sorted(current | proposed):
        action = "retained" if sid in current and sid in proposed else (
            "new" if sid in proposed else "exited")
        level, detail = details.get(sid, (None, None))
        candidate_rows.append((change_id, sid, action, level, detail,
                               impact["evaluatedAt"]))
    conn.executemany("""INSERT INTO alert_rule_change_candidate
        (change_id,student_id,action,level,trigger_detail,created_at)
        VALUES (?,?,?,?,?,?)""", candidate_rows)
    dbm.execute(conn, "UPDATE alert_rule_change SET impact_json=? WHERE change_id=?",
                (json.dumps(impact, ensure_ascii=False), change_id))
    return ok(impact, msg="规则影响试算完成，当前预警未发生变化")


@router.get("/settings/rule-changes/{change_id}/candidates")
def list_rule_change_candidates(change_id: int, action: str | None = None,
                                page: int = 1, page_size: int = 20,
                                user: dict = Depends(get_current_user),
                                conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "audit")
    if not dbm.query_one(conn, "SELECT 1 FROM alert_rule_change WHERE change_id=?", (change_id,)):
        raise ApiError("规则变更单不存在", code=404, status_code=404)
    if action and action not in ("retained", "new", "exited"):
        raise ApiError("无效的候选分类", code=400, status_code=400)
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    cond = "WHERE c.change_id=?"
    params: list = [change_id]
    if action:
        cond += " AND c.action=?"
        params.append(action)
    total = dbm.scalar(conn, f"SELECT COUNT(*) FROM alert_rule_change_candidate c {cond}",
                       tuple(params)) or 0
    rows = dbm.query(conn, f"""SELECT c.student_id,c.action,c.level,c.trigger_detail,
        s.name student_name,co.name college_name,m.name major_name,cl.name class_name
        FROM alert_rule_change_candidate c
        LEFT JOIN dim_student s ON c.student_id=s.student_id
        LEFT JOIN dim_college co ON s.college_id=co.college_id
        LEFT JOIN dim_major m ON s.major_id=m.major_id
        LEFT JOIN dim_class cl ON s.class_id=cl.class_id
        {cond}
        ORDER BY CASE c.action WHEN 'new' THEN 0 WHEN 'exited' THEN 1 ELSE 2 END,
                 c.student_id LIMIT ? OFFSET ?""",
        tuple(params + [page_size, (page - 1) * page_size]))
    return ok({"total": total, "page": page, "pageSize": page_size,
               "list": [dict(r) for r in rows]})


@router.get("/settings/rule-changes/{change_id}/analysis")
def rule_change_analysis(change_id: int, user: dict = Depends(get_current_user),
                         conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "audit")
    change = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?", (change_id,))
    if not change:
        raise ApiError("规则变更单不存在", code=404, status_code=404)
    try:
        base = json.loads(change["base_params"] or "{}")
        proposed = json.loads(change["proposed_params"] or "{}")
    except Exception:
        base, proposed = {}, {}
    keys = sorted((set(base) | set(proposed)) - {"text"})
    param_diff = [{"key": key, "before": base.get(key), "after": proposed.get(key),
                   "changed": base.get(key) != proposed.get(key)} for key in keys]

    def grouped(dimension_sql: str, label_sql: str) -> list[dict]:
        return dbm.query(conn, f"""SELECT {dimension_sql} id,{label_sql} name,
            COUNT(*) total,
            SUM(CASE WHEN c.action='new' THEN 1 ELSE 0 END) new_count,
            SUM(CASE WHEN c.action='retained' THEN 1 ELSE 0 END) retained_count,
            SUM(CASE WHEN c.action='exited' THEN 1 ELSE 0 END) exited_count
            FROM alert_rule_change_candidate c
            LEFT JOIN dim_student s ON c.student_id=s.student_id
            LEFT JOIN dim_college co ON s.college_id=co.college_id
            LEFT JOIN dim_major m ON s.major_id=m.major_id
            WHERE c.change_id=? GROUP BY {dimension_sql},{label_sql}
            ORDER BY total DESC""", (change_id,))

    by_action = dbm.query(conn, """SELECT action name,COUNT(*) total
        FROM alert_rule_change_candidate WHERE change_id=? GROUP BY action
        ORDER BY total DESC""", (change_id,))
    by_level = dbm.query(conn, """SELECT COALESCE(level,'退出') name,COUNT(*) total
        FROM alert_rule_change_candidate WHERE change_id=? GROUP BY COALESCE(level,'退出')
        ORDER BY total DESC""", (change_id,))
    return ok({
        "changeId": change_id, "ruleId": change["rule_id"],
        "paramDiff": param_diff,
        "enabledDiff": {"before": bool(change["base_enabled"]),
                        "after": bool(change["proposed_enabled"])},
        "byCollege": grouped("s.college_id", "COALESCE(co.name,'未知学院')"),
        "byMajor": grouped("s.major_id", "COALESCE(m.name,'未知专业')"),
        "byGrade": grouped("s.grade", "COALESCE(CAST(s.grade AS TEXT),'未知年级')"),
        "byAction": by_action, "byLevel": by_level,
    })


@router.get("/settings/rule-changes/{change_id}/candidates.csv")
def export_rule_change_candidates(change_id: int,
                                  user: dict = Depends(get_current_user),
                                  conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "audit")
    if not dbm.query_one(conn, "SELECT 1 FROM alert_rule_change WHERE change_id=?", (change_id,)):
        raise ApiError("规则变更单不存在", code=404, status_code=404)
    rows = dbm.query(conn, """SELECT c.student_id,s.name student_name,
        co.name college_name,m.name major_name,cl.name class_name,s.grade,
        c.action,c.level,c.trigger_detail
        FROM alert_rule_change_candidate c
        LEFT JOIN dim_student s ON c.student_id=s.student_id
        LEFT JOIN dim_college co ON s.college_id=co.college_id
        LEFT JOIN dim_major m ON s.major_id=m.major_id
        LEFT JOIN dim_class cl ON s.class_id=cl.class_id
        WHERE c.change_id=? ORDER BY c.action,c.student_id""", (change_id,))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["学号", "姓名", "学院", "专业", "班级", "年级", "变化类型",
                     "预警等级", "候选命中说明"])
    for row in rows:
        writer.writerow([row["student_id"], row["student_name"], row["college_name"],
                         row["major_name"], row["class_name"], row["grade"], row["action"],
                         row["level"], row["trigger_detail"]])
    content = "\ufeff" + output.getvalue()
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="rule-change-{change_id}-candidates.csv"'})


@router.post("/settings/rule-changes/{change_id}/submit")
def submit_rule_change(change_id: int, user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "edit")
    row = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?", (change_id,))
    if not row or row["status"] != "draft":
        raise ApiError("仅草稿状态可以提交", code=400, status_code=400)
    _require_fresh_impact(conn, row)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    dbm.execute(conn, "UPDATE alert_rule_change SET status='submitted',submitted_at=? WHERE change_id=?",
                (now, change_id))
    return ok({"changeId": change_id, "status": "submitted"}, msg="变更单已提交审核")


@router.post("/settings/rule-changes/{change_id}/review")
def review_rule_change(change_id: int, body: RuleChangeReviewIn,
                       user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "review")
    if body.action not in ("approve", "reject"):
        raise ApiError("action 必须为 approve 或 reject", code=400, status_code=400)
    row = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?", (change_id,))
    if not row or row["status"] != "submitted":
        raise ApiError("仅已提交状态可以审核", code=400, status_code=400)
    _require_fresh_impact(conn, row)
    if row["created_by"] == user["username"]:
        raise ApiError("创建人不能审核自己的规则变更", code=403, status_code=403)
    status = "approved" if body.action == "approve" else "rejected"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    dbm.execute(conn, """UPDATE alert_rule_change SET status=?,reviewed_by=?,
        reviewed_at=?,review_comment=? WHERE change_id=?""",
        (status, user["username"], now, body.comment, change_id))
    return ok({"changeId": change_id, "status": status}, msg="审核结果已记录")


@router.post("/settings/rule-changes/{change_id}/publish")
def publish_rule_change(change_id: int, user: dict = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db_rw)):
    """发布只更新规则配置；预警结果仍需走候选试算和受控激活。"""
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "publish")
    row = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?", (change_id,))
    if not row or row["status"] != "approved":
        raise ApiError("仅审核通过的变更单可以发布", code=400, status_code=400)
    _require_fresh_impact(conn, row)
    current = dbm.query_one(conn, "SELECT params,enabled FROM sys_alert_rule WHERE rule_id=?",
                            (row["rule_id"],))
    snapshot = json.dumps(dict(current), ensure_ascii=False)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    dbm.execute(conn, "UPDATE sys_alert_rule SET params=?,enabled=? WHERE rule_id=?",
                (row["proposed_params"], row["proposed_enabled"], row["rule_id"]))
    dbm.execute(conn, """UPDATE alert_rule_change SET status='published',published_by=?,
        published_at=?,previous_snapshot=? WHERE change_id=?""",
        (user["username"], now, snapshot, change_id))
    return ok({"changeId": change_id, "status": "published", "ruleId": row["rule_id"]},
              msg="规则配置已发布；预警结果需经候选试算后受控激活")


@router.post("/settings/rule-changes/{change_id}/rollback")
def create_rollback_change(change_id: int, user: dict = Depends(get_current_user),
                           conn: sqlite3.Connection = Depends(get_db_rw)):
    """根据已发布变更的上一版本快照创建回滚草稿，不直接回写生产规则。"""
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "edit")
    source = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?", (change_id,))
    if not source or source["status"] not in ("published", "activated") or not source["previous_snapshot"]:
        raise ApiError("仅已发布且具有上一版本快照的变更可以回滚", code=400, status_code=400)
    open_change = dbm.query_one(conn, """SELECT change_id FROM alert_rule_change
        WHERE rule_id=? AND status IN ('draft','submitted','approved')""", (source["rule_id"],))
    if open_change:
        raise ApiError("该规则已有未完成的变更单，不能创建回滚", code=409, status_code=409)
    try:
        snapshot = json.loads(source["previous_snapshot"])
    except Exception:
        raise ApiError("上一版本快照损坏，无法自动回滚", code=500, status_code=500)
    current = dbm.query_one(conn, "SELECT params,enabled FROM sys_alert_rule WHERE rule_id=?",
                            (source["rule_id"],))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    current_hits = dbm.scalar(conn, """SELECT COUNT(DISTINCT student_id) FROM fact_alert
        WHERE rule_id=? AND COALESCE(is_active,1)=1""", (source["rule_id"],)) or 0
    impact = {"currentStudents": current_hits, "candidateStatus": "pending",
              "note": "回滚草稿仍需重新试算、审核和发布",
              "rollbackOf": change_id}
    cur = dbm.execute(conn, """INSERT INTO alert_rule_change
        (rule_id,base_params,proposed_params,base_enabled,proposed_enabled,status,
         reason,impact_json,created_by,created_at)
        VALUES (?,?,?,?,?,'draft',?,?,?,?)""",
        (source["rule_id"], current["params"], snapshot["params"], current["enabled"],
         snapshot["enabled"], f"回滚已发布变更单 #{change_id}",
         json.dumps(impact, ensure_ascii=False), user["username"], now))
    created = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?",
                            (cur.lastrowid,))
    return ok(_change_item(created), msg="回滚草稿已创建，生产规则未改变")


@router.post("/settings/rule-changes/{change_id}/activate")
def activate_rule_change(change_id: int, user: dict = Depends(get_current_user),
                         conn: sqlite3.Connection = Depends(get_db_rw)):
    """将已发布变更的学生级候选事务化激活为当前预警。"""
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "activate")
    change = dbm.query_one(conn, "SELECT * FROM alert_rule_change WHERE change_id=?", (change_id,))
    if not change or change["status"] != "published":
        raise ApiError("仅已发布且尚未激活的规则变更可以激活", code=400, status_code=400)
    if dbm.query_one(conn, "SELECT 1 FROM alert_rule_change_activation WHERE change_id=?", (change_id,)):
        raise ApiError("该规则变更已经激活，禁止重复执行", code=409, status_code=409)
    impact = _require_fresh_impact(conn, change)
    candidates = dbm.query(conn, """SELECT * FROM alert_rule_change_candidate
        WHERE change_id=? ORDER BY student_id""", (change_id,))
    if len(candidates) != (impact.get("retainedStudents", 0) + impact.get("newStudents", 0)
                           + impact.get("exitedStudents", 0)):
        raise ApiError("候选明细与影响汇总不一致，请重新试算", code=409, status_code=409)
    rule = dbm.query_one(conn, "SELECT name,level FROM sys_alert_rule WHERE rule_id=?",
                         (change["rule_id"],))
    if not rule:
        raise ApiError("生产规则不存在", code=404, status_code=404)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    version = f"{change['rule_id']}-change-{change_id}"
    from .alert_assignment import assignees_for_student, insert_event_assignees
    v2_conn = dbm.get_v2_conn()
    assignee_cache: dict[str, list[dict]] = {}

    def _assignees(sid: str) -> list[dict]:
        if sid not in assignee_cache:
            assignee_cache[sid] = assignees_for_student(conn, sid, v2_conn)
        return assignee_cache[sid]

    semester = dbm.scalar(conn, "SELECT semester_id FROM dim_semester ORDER BY semester_id DESC LIMIT 1")
    counts = {"retained": 0, "new": 0, "exited": 0}
    for item in candidates:
        sid, action = item["student_id"], item["action"]
        current = dbm.query_one(conn, """SELECT * FROM fact_alert
            WHERE student_id=? AND rule_id=? AND COALESCE(is_active,1)=1
            ORDER BY alert_id DESC LIMIT 1""", (sid, change["rule_id"]))
        if action == "retained":
            if not current:
                raise ApiError(f"保留候选缺少当前预警：{sid}", code=409, status_code=409)
            event = dbm.query_one(conn, """SELECT event_id,workflow_status,cycle_no
                FROM alert_event WHERE alert_id=?""", (current["alert_id"],))
            if event and event["workflow_status"] in ("resolved", "closed"):
                # 人工或系统已经结束的风险不可重新打开；新命中必须形成独立风险周期。
                dbm.execute(conn, """UPDATE fact_alert SET is_active=0,closed_at=?,close_reason=?
                    WHERE alert_id=?""", (now, "已结束事件再次命中，转入新风险周期", current["alert_id"]))
                cur = dbm.execute(conn, """INSERT INTO fact_alert
                    (student_id,rule_id,type,level,trigger_detail,status,created_at,semester_id,
                     source,is_active,rule_version,activation_batch_id)
                    VALUES (?,?,?,?,?,'待处理',?,?,'real',1,?,?)""",
                    (sid, change["rule_id"], rule["name"], item["level"] or rule["level"],
                     item["trigger_detail"], now, semester, version, str(change_id)))
                new_alert_id = cur.lastrowid
                cur = dbm.execute(conn, """INSERT INTO alert_event
                    (alert_id,student_id,rule_id,workflow_status,first_detected_at,
                     last_detected_at,updated_at,source,cycle_no,recurrence_of_event_id,cycle_reason)
                    VALUES (?,?,?,'new',?,?,?,'engine',?,?,?)""",
                    (new_alert_id, sid, change["rule_id"], now, now, now,
                     int(event["cycle_no"] or 1) + 1, event["event_id"], "已结束后规则再次命中"))
                if assignees := _assignees(sid):
                    insert_event_assignees(
                        conn, cur.lastrowid, assignees, now,
                        reason_prefix=f"风险第{int(event['cycle_no'] or 1)+1}周期自动分派：")
            else:
                dbm.execute(conn, """UPDATE fact_alert SET level=?,trigger_detail=?,rule_version=?,
                    activation_batch_id=? WHERE alert_id=?""",
                    (item["level"] or rule["level"], item["trigger_detail"], version,
                     str(change_id), current["alert_id"]))
                dbm.execute(conn, """UPDATE alert_event SET last_detected_at=?,updated_at=?
                    WHERE alert_id=?""", (now, now, current["alert_id"]))
        elif action == "exited":
            if not current:
                raise ApiError(f"退出候选缺少当前预警：{sid}", code=409, status_code=409)
            dbm.execute(conn, """UPDATE fact_alert SET is_active=0,closed_at=?,close_reason=?,
                activation_batch_id=? WHERE alert_id=?""",
                (now, f"规则变更单#{change_id}激活后不再命中", str(change_id), current["alert_id"]))
            event = dbm.query_one(conn, "SELECT event_id,workflow_status FROM alert_event WHERE alert_id=?",
                                  (current["alert_id"],))
            if event and event["workflow_status"] not in ("resolved", "closed"):
                dbm.execute(conn, "UPDATE alert_event SET workflow_status='resolved',updated_at=? WHERE event_id=?",
                            (now, event["event_id"]))
                dbm.execute(conn, """INSERT INTO alert_status_history
                    (event_id,from_status,to_status,operator,reason,changed_at)
                    VALUES (?,?,'resolved',?,?,?)""",
                    (event["event_id"], event["workflow_status"], user["username"],
                     f"规则变更单#{change_id}激活后自动关闭", now))
        elif action == "new":
            if current:
                raise ApiError(f"新增候选已存在当前预警：{sid}", code=409, status_code=409)
            cur = dbm.execute(conn, """INSERT INTO fact_alert
                (student_id,rule_id,type,level,trigger_detail,status,created_at,semester_id,
                 source,is_active,rule_version,activation_batch_id)
                VALUES (?,?,?,?,?,'待处理',?,?,'real',1,?,?)""",
                (sid, change["rule_id"], rule["name"], item["level"] or rule["level"],
                 item["trigger_detail"], now, semester, version, str(change_id)))
            alert_id = cur.lastrowid
            previous = dbm.query_one(conn, """SELECT event_id,cycle_no FROM alert_event
                WHERE student_id=? AND rule_id=? ORDER BY cycle_no DESC,event_id DESC LIMIT 1""",
                (sid, change["rule_id"]))
            cycle_no = int(previous["cycle_no"] or 1) + 1 if previous else 1
            cur = dbm.execute(conn, """INSERT INTO alert_event
                (alert_id,student_id,rule_id,workflow_status,first_detected_at,
                 last_detected_at,updated_at,source,cycle_no,recurrence_of_event_id,cycle_reason)
                 VALUES (?,?,?,'new',?,?,?,'engine',?,?,?)""",
                (alert_id, sid, change["rule_id"], now, now, now, cycle_no,
                 previous["event_id"] if previous else None,
                 "退出后重新命中" if previous else "首次命中"))
            if assignees := _assignees(sid):
                insert_event_assignees(
                    conn, cur.lastrowid, assignees, now,
                    reason_prefix=f"规则变更单#{change_id}激活自动分派：")
        else:
            raise ApiError(f"未知候选动作：{action}", code=409, status_code=409)
        counts[action] += 1
    dbm.execute(conn, """INSERT INTO alert_rule_change_activation
        (change_id,rule_id,retained_count,new_count,exited_count,activated_by,
         activated_at,status,note) VALUES (?,?,?,?,?,?,?,'activated',?)""",
        (change_id, change["rule_id"], counts["retained"], counts["new"],
         counts["exited"], user["username"], now, "事务化通用候选激活"))
    dbm.execute(conn, "UPDATE alert_rule_change SET status='activated' WHERE change_id=?", (change_id,))
    v2_conn.close()
    return ok({"changeId": change_id, "status": "activated", **counts},
              msg="候选预警已受控激活")


# ── 规则自发现 ──

class DiscoveredRuleAction(BaseModel):
    action: str  # "approve" | "reject"


@router.post("/settings/rules/discover")
def trigger_discovery(user: dict = Depends(get_current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    """触发规则自发现分析，返回发现的规则数量。"""
    if not has_action(user, "rule.discovery.manage"):
        raise ApiError("当前角色无权运行规则自发现", code=403, status_code=403)
    from backend.etl.rule_discovery import run_and_save
    from ..settings import CURRENT_SEMESTER
    try:
        n = run_and_save(CURRENT_SEMESTER)
        return ok({"count": n, "semester": CURRENT_SEMESTER,
                   "algorithmVersion": "association-v2",
                   "evidence": {"level": "real-derived",
                                "sources": ["真实成绩", "真实学籍异动", "当前严重预警"],
                                "limitation": "历史关联不等于因果关系，采纳后仍须完成试算、复核、发布与激活。"}},
                  msg=f"分析完成，发现 {n} 条候选规则")
    except Exception as e:
        raise ApiError(f"分析失败：{e}", code=500, status_code=500)


@router.get("/settings/rules/discovered")
def list_discovered(conn: sqlite3.Connection = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    """获取规则自发现结果，按状态分组。"""
    pending, approved, rejected, superseded = [], [], [], []
    last_semester = dbm.scalar(conn,
        "SELECT MAX(semester_id) FROM sys_discovered_rule") or ""
    for r in dbm.query(conn, """
        SELECT * FROM sys_discovered_rule ORDER BY risk_ratio DESC"""):
        try:
            conds = json.loads(r["conditions"])
        except Exception:
            conds = []
        detail = {}
        try:
            detail = json.loads(r["detail_json"] or "{}")
        except Exception:
            pass
        item = {
            "id": r["id"], "semesterId": r["semester_id"],
            "name": r["name"], "conditions": conds,
            "level": r["level"], "confidence": r["confidence"],
            "riskRatio": r["risk_ratio"], "sampleSize": r["sample_size"],
            "detail": detail, "status": r["status"],
            "createdAt": r["created_at"], "approvedAt": r["approved_at"],
        }
        if r["status"] == "pending":
            pending.append(item)
        elif r["status"] in ("approved", "adopted"):
            approved.append(item)
        elif r["status"] == "rejected":
            rejected.append(item)
        elif r["status"] == "superseded":
            superseded.append(item)

    return ok({
        "pending": pending, "approved": approved, "rejected": rejected,
        "superseded": superseded,
        "lastSemester": last_semester,
        "totalStudents": dbm.scalar(conn, "SELECT COUNT(*) FROM dim_student") or 0,
        "evidence": {"level": "real-derived",
                     "sources": ["fact_grade(source=real)", "fact_attrition(source=real)", "fact_alert"],
                     "limitation": "候选规则来自历史关联分析，不代表因果关系或自动生效。"},
    })


@router.put("/settings/rules/discovered/{rule_id}")
def review_discovered(rule_id: int, body: DiscoveredRuleAction,
                       user: dict = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db_rw)):
    """采纳只创建禁用规则占位与治理草稿；不会直接改变生产预警。"""
    _ensure_governance(conn)
    _require_rule_permission(conn, user, "edit")
    if body.action not in ("approve", "reject"):
        raise ApiError("action 必须为 approve 或 reject", code=400, status_code=400)

    row = dbm.query_one(conn,
        "SELECT * FROM sys_discovered_rule WHERE id=?", (rule_id,))
    if not row:
        raise ApiError("规则不存在", code=404, status_code=404)
    if row["status"] != "pending":
        raise ApiError("仅可审核待处理状态的规则", code=400, status_code=400)

    if body.action == "approve":
        try:
            conds = json.loads(row["conditions"])
        except Exception:
            conds = []
        params = {}
        for c in conds:
            params[c["key"]] = c.get("engineValue", c.get("value"))
        params["text"] = row["name"]
        rule_id_str = f"DR{rule_id}"
        if dbm.query_one(conn, "SELECT 1 FROM sys_alert_rule WHERE rule_id=?", (rule_id_str,)):
            raise ApiError("该建议已存在生产规则占位，不能重复采纳", code=409, status_code=409)
        params_json = json.dumps(params, ensure_ascii=False)
        dbm.execute(conn, """
            INSERT INTO sys_alert_rule
                (rule_id, name, level, trigger_type, params, enabled)
            VALUES (?, ?, ?, 'discovered', ?, 0)
        """, (rule_id_str, row["name"], row["level"] or "警告",
              params_json))
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        impact = {"currentStudents": 0, "candidateStatus": "pending",
                  "note": "自发现建议已采纳，必须先完成影响试算",
                  "discoveredRuleId": rule_id}
        cur = dbm.execute(conn, """INSERT INTO alert_rule_change
            (rule_id,base_params,proposed_params,base_enabled,proposed_enabled,status,
             reason,impact_json,created_by,created_at)
            VALUES (?,?,?,0,1,'draft',?,?,?,?)""",
            (rule_id_str, params_json, params_json,
             f"采纳自发现规则建议 #{rule_id}：{row['name']}",
             json.dumps(impact, ensure_ascii=False), user["username"], now))
        change_id = cur.lastrowid
        detail = json.loads(row["detail_json"] or "{}")
        detail["governance_change_id"] = change_id
        detail["adopted_by"] = user["username"]
        detail["adopted_at"] = now
        dbm.execute(conn, """
            UPDATE sys_discovered_rule SET status='adopted', approved_at=?, detail_json=?
            WHERE id=?""", (now, json.dumps(detail, ensure_ascii=False), rule_id))
        msg = f"已创建规则变更草稿 #{change_id}，生产规则尚未启用"
    else:
        dbm.execute(conn,
            "UPDATE sys_discovered_rule SET status='rejected' WHERE id=?", (rule_id,))
        change_id = None
        msg = "规则建议已拒绝"

    return ok({"id": rule_id, "action": body.action, "changeId": change_id}, msg=msg)


# ── 规则自发现配置 ──

class DiscoveryConfigIn(BaseModel):
    data_sources: dict | None = None
    llm: dict | None = None
    sampling: dict | None = None


@router.get("/settings/discovery/config")
def get_discovery_config(conn: sqlite3.Connection = Depends(get_db),
                         user: dict = Depends(get_current_user)):
    """获取规则自发现的数据范围/LLM/采样配置。"""
    exists = dbm.scalar(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sys_config'")
    rows = (dbm.query(conn, "SELECT config_key, config_value FROM sys_config "
                      "WHERE config_key LIKE 'discovery.%'") if exists else [])
    config = {}
    for r in rows:
        try:
            config[r["config_key"]] = json.loads(r["config_value"])
        except Exception:
            config[r["config_key"]] = r["config_value"]
    llm = dict(config.get("discovery.llm", {"mode": "off", "anonymization": "standard"}) or {})
    # 配置接口不回传密钥；当前实现也不允许把新密钥明文写入分析库。
    has_cloud_key = bool(llm.pop("cloud_api_key", None))
    llm["has_cloud_api_key"] = has_cloud_key
    return ok({
        "data_sources": config.get("discovery.data_sources", {
            "core": ["fact_grade", "dim_student", "fact_alert", "fact_attrition", "fact_major_req"]}),
        "llm": llm,
        "sampling": config.get("discovery.sampling", {}),
    })


@router.put("/settings/discovery/config")
def update_discovery_config(body: DiscoveryConfigIn,
                            _: dict = Depends(require_admin),
                            conn: sqlite3.Connection = Depends(get_db_rw)):
    """更新规则自发现配置。仅 admin 可操作。"""
    import json as _json
    if body.llm and body.llm.get("cloud_api_key"):
        raise ApiError("禁止将模型密钥明文写入分析库，请接入服务端密钥管理后再启用",
                       code=400, status_code=400)
    dbm.execute(conn, """CREATE TABLE IF NOT EXISTS sys_config (
        config_key TEXT PRIMARY KEY, config_value TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now','localtime')), updated_by TEXT)""")
    updates = {
        "discovery.data_sources": body.data_sources,
        "discovery.llm": body.llm,
        "discovery.sampling": body.sampling,
    }
    for key, val in updates.items():
        if val is not None:
            dbm.execute(conn, """
                INSERT INTO sys_config (config_key, config_value, updated_at)
                VALUES (?, ?, datetime('now','localtime'))
                ON CONFLICT(config_key) DO UPDATE SET
                    config_value=excluded.config_value,
                    updated_at=excluded.updated_at
            """, (key, _json.dumps(val, ensure_ascii=False)))
    return ok(msg="配置已保存")


# ── V1.1：KPI 指标体系配置 ──

class KpiConfigIn(BaseModel):
    enabled: bool | None = None
    sort_order: int | None = None
    calc_type: str | None = None
    color_rule: str | None = None
    threshold_warn: float | None = None
    threshold_danger: float | None = None
    change_reason: str = Field(default="页面配置调整", min_length=2, max_length=300)


KPI_CONFIG_DDL = """CREATE TABLE IF NOT EXISTS sys_kpi_config (
    kpi_id TEXT PRIMARY KEY,module TEXT NOT NULL,label TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,calc_type TEXT,
    formula TEXT,unit TEXT,color_rule TEXT,threshold_warn REAL,
    threshold_danger REAL,scope_applicable TEXT DEFAULT 'all',
    data_source TEXT,grain TEXT,update_cycle TEXT,version TEXT DEFAULT '1.0',
    page_refs TEXT DEFAULT '[]',management_value TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime')))"""
KPI_DEFAULTS = [
    ("student_count", "在籍学生数", 1, "count", "在籍状态学生去重计数", "人",
     "dim_student", "学生", "数据同步后", "1.0", ["/admin/dashboard"],
     "判断管理覆盖规模并作为相关比例指标的基础分母。"),
    ("course_count", "本学期开课门数", 2, "count", "当前学期课程编码去重计数", "门",
     "fact_lesson / teaching_lesson", "课程×学期", "教学任务同步后", "1.0",
     ["/admin/dashboard"], "反映当前教学供给覆盖面。"),
    ("teacher_count", "专任教师数", 3, "count", "有效教师主数据去重计数", "人",
     "dim_teacher / dim_staff", "教师", "教师主数据同步后", "1.0",
     ["/admin/dashboard", "/admin/faculty"], "用于观察师资保障规模，不代表实际授课人数。"),
    ("alert_count", "当前预警", 4, "count", "有效预警学生去重计数", "人",
     "fact_alert / alert_event", "学生", "预警重算后", "1.0",
     ["/admin/dashboard", "/admin/alert"], "提示当前需要优先核查的学生覆盖规模。"),
    ("current_fail_rate", "当前挂科率", 5, "rate", "当前学期未通过成绩记录数÷有效成绩记录数", "%",
     "fact_grade / grade_attempt", "成绩记录×学期", "成绩发布后", "1.0",
     ["/admin/dashboard"], "观察本学期课程结果总体变化，不用于评价教师个人。"),
    ("history_fail_rate", "历史挂科经历率", 6, "rate", "历史存在未通过记录学生数÷有成绩学生数", "%",
     "fact_grade / grade_attempt", "学生", "成绩发布后", "1.0",
     ["/admin/dashboard", "/admin/students/analysis"], "衡量学生群体既往学业受挫覆盖面。"),
    ("grad_rate", "应届毕业率", 7, "rate", "按期毕业人数÷应届毕业生人数", "%",
     "fact_graduation", "学生×毕业年度", "毕业数据同步后", "1.0",
     ["/admin/dashboard"], "观察按期完成学业情况，正式结果以学校审核为准。"),
    ("degree_rate", "学位授予率", 8, "rate", "获得学位人数÷毕业审核范围人数", "%",
     "fact_graduation", "学生×毕业年度", "学位数据同步后", "1.0",
     ["/admin/dashboard"], "观察学位获得总体情况，正式结果以学校学位审核为准。"),
]

# M1：课程质量三分层指标（module='course_quality'），结构与 KPI_DEFAULTS 相同。
KPI_DEFAULTS_COURSE_QUALITY = [
    ("course_first_pass_rate", "课程首次通过率", 1, "rate",
     "首次修读（attempt_type=regular，含缓考）通过人次数÷首次修读有效人次数；"
     "有效记录=已发布且未作废且is_pass非空；分母为0时不输出比率", "%",
     "agg_course_pass_stat", "课程×学期", "成绩发布后", "1.1",
     ["/admin/operation/course-quality"],
     "衡量课程首修教学结果，是课程质量三分层口径的主指标。"),
    ("course_makeup_pass_rate", "课程补考通过率", 2, "rate",
     "补考（attempt_type=makeup）通过人次数÷补考有效人次数；分母为0时不输出比率", "%",
     "agg_course_pass_stat", "课程×学期", "成绩发布后", "1.1",
     ["/admin/operation/course-quality"],
     "观察补考通道的挽救效果，辅助判断考核与帮扶安排。"),
    ("course_retake_pass_rate", "课程重修通过率", 3, "rate",
     "重修（attempt_type=retake）通过人次数÷重修有效人次数；分母为0时不输出比率", "%",
     "agg_course_pass_stat", "课程×学期", "成绩发布后", "1.1",
     ["/admin/operation/course-quality"],
     "观察重修通道的收敛效果，辅助安排重修资源。"),
    ("public_required_first_pass_rate", "公共必修首次通过率", 4, "rate",
     "公共必修课程首次修读通过人次数÷公共必修首次修读有效人次数；"
     "课程类别由培养方案模块与V1课程类别合并推导", "%",
     "agg_course_pass_stat", "全校/学院×学期", "成绩发布后", "1.1",
     ["/admin/dashboard", "/admin/operation/course-quality"],
     "公共必修覆盖全体学生，是重点关注的通识基础课质量指标。"),
]

KPI_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS sys_kpi_config_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kpi_id TEXT NOT NULL,
    config_json TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_kpi_config_history
ON sys_kpi_config_history(kpi_id,history_id);
"""


def _ensure_kpi_config(conn: sqlite3.Connection) -> None:
    dbm.execute(conn, KPI_CONFIG_DDL)
    conn.executescript(KPI_HISTORY_DDL)
    columns = {
        row["name"] for row in dbm.query(conn, "PRAGMA table_info(sys_kpi_config)")
    }
    for name, definition in {
        "data_source": "TEXT",
        "grain": "TEXT",
        "update_cycle": "TEXT",
        "version": "TEXT DEFAULT '1.0'",
        "page_refs": "TEXT DEFAULT '[]'",
        "management_value": "TEXT",
    }.items():
        if name not in columns:
            dbm.execute(
                conn, f"ALTER TABLE sys_kpi_config ADD COLUMN {name} {definition}"
            )
    for defaults, module in ((KPI_DEFAULTS, "dashboard"),
                             (KPI_DEFAULTS_COURSE_QUALITY, "course_quality")):
        for (kpi_id, label, order, calc_type, formula, unit, data_source,
             grain, update_cycle, version, page_refs, management_value) in defaults:
            dbm.execute(conn, """INSERT OR IGNORE INTO sys_kpi_config
                (kpi_id,module,label,enabled,sort_order,calc_type,formula,unit,
                 scope_applicable,data_source,grain,update_cycle,version,page_refs,
                 management_value)
                VALUES (?,?,?,1,?,?,?,?, 'all',?,?,?,?,?,?)""",
                (
                    kpi_id, module, label, order, calc_type, formula, unit, data_source,
                    grain, update_cycle, version,
                    json.dumps(page_refs, ensure_ascii=False), management_value,
                ))
            dbm.execute(conn, """UPDATE sys_kpi_config SET
                label=?,
                calc_type=?,
                formula=?,
                unit=?,
                data_source=COALESCE(NULLIF(data_source,''),?),
                grain=COALESCE(NULLIF(grain,''),?),
                update_cycle=COALESCE(NULLIF(update_cycle,''),?),
                version=COALESCE(NULLIF(version,''),?),
                page_refs=CASE WHEN page_refs IS NULL OR page_refs='' OR page_refs='[]'
                               THEN ? ELSE page_refs END,
                management_value=COALESCE(NULLIF(management_value,''),?)
                WHERE kpi_id=?""", (
                    label, calc_type, formula, unit,
                    data_source, grain, update_cycle, version,
                    json.dumps(page_refs, ensure_ascii=False), management_value,
                    kpi_id,
                ))


@router.get("/settings/kpi-config")
def get_kpi_config(module: str = None,
                   conn: sqlite3.Connection = Depends(get_db_rw),
                   user: dict = Depends(require_admin)):
    """获取 KPI 配置列表，可按模块过滤。"""
    _ensure_kpi_config(conn)
    if module:
        rows = dbm.query(conn, """
            SELECT * FROM sys_kpi_config WHERE module=? ORDER BY sort_order
        """, (module,))
    else:
        rows = dbm.query(conn, """
            SELECT * FROM sys_kpi_config ORDER BY module, sort_order
        """)
    return ok([dict(r) for r in rows])


@router.put("/settings/kpi-config/{kpi_id}")
def update_kpi_config(kpi_id: str, body: KpiConfigIn,
                      user: dict = Depends(require_admin),
                      conn: sqlite3.Connection = Depends(get_db_rw)):
    """只允许调整已有可执行 KPI 的显示、顺序与着色阈值。"""
    _ensure_kpi_config(conn)
    row = dbm.query_one(conn, "SELECT * FROM sys_kpi_config WHERE kpi_id=?", (kpi_id,))
    if not row:
        raise ApiError("KPI 不存在", code=404, status_code=404)
    fields, params = [], []
    if body.calc_type is not None and body.calc_type != row["calc_type"]:
        raise ApiError("计算口径由后端公式注册表管理，不能在页面中任意修改",
                       code=400, status_code=400)
    for col in ("enabled", "sort_order", "color_rule",
                "threshold_warn", "threshold_danger"):
        val = getattr(body, col, None)
        if val is not None:
            fields.append(f"{col}=?"); params.append(val)
    if fields:
        dbm.execute(conn, """
            INSERT INTO sys_kpi_config_history(
              kpi_id,config_json,change_reason,changed_by
            ) VALUES(?,?,?,?)
        """, (
            kpi_id, json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
            body.change_reason.strip(), user["username"],
        ))
        params.append(kpi_id)
        dbm.execute(conn, f"""UPDATE sys_kpi_config SET {','.join(fields)},
            updated_at=datetime('now','localtime') WHERE kpi_id=?""", params)
        from ..security_governance import write_audit
        write_audit(conn, user["username"], "settings.kpi.update", "kpi", kpi_id,
                    detail={
                        "fields": [f.split("=")[0] for f in fields],
                        "changeReason": body.change_reason.strip(),
                    })
    return ok(msg="KPI 配置已更新")


@router.get("/settings/kpi-config/{kpi_id}/history")
def get_kpi_config_history(kpi_id: str,
                           _: dict = Depends(require_admin),
                           conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_kpi_config(conn)
    rows = dbm.query(conn, """
        SELECT history_id,kpi_id,change_reason,changed_by,changed_at,config_json
        FROM sys_kpi_config_history WHERE kpi_id=?
        ORDER BY history_id DESC LIMIT 30
    """, (kpi_id,))
    for row in rows:
        row["config"] = json.loads(row.pop("config_json") or "{}")
    return ok(rows)


@router.post("/settings/kpi-config/{kpi_id}/rollback/{history_id}")
def rollback_kpi_config(kpi_id: str, history_id: int,
                        user: dict = Depends(require_admin),
                        conn: sqlite3.Connection = Depends(get_db_rw)):
    _ensure_kpi_config(conn)
    current = dbm.query_one(
        conn, "SELECT * FROM sys_kpi_config WHERE kpi_id=?", (kpi_id,)
    )
    history = dbm.query_one(conn, """
        SELECT * FROM sys_kpi_config_history
        WHERE history_id=? AND kpi_id=?
    """, (history_id, kpi_id))
    if not current or not history:
        raise ApiError("指标配置历史不存在", code=404, status_code=404)
    target = json.loads(history["config_json"] or "{}")
    allowed = (
        "enabled", "sort_order", "color_rule",
        "threshold_warn", "threshold_danger",
    )
    dbm.execute(conn, """
        INSERT INTO sys_kpi_config_history(
          kpi_id,config_json,change_reason,changed_by
        ) VALUES(?,?,?,?)
    """, (
        kpi_id, json.dumps(dict(current), ensure_ascii=False, sort_keys=True),
        f"回滚前备份，目标历史#{history_id}", user["username"],
    ))
    dbm.execute(conn, """UPDATE sys_kpi_config SET
        enabled=?,sort_order=?,color_rule=?,threshold_warn=?,
        threshold_danger=?,updated_at=datetime('now','localtime')
        WHERE kpi_id=?""", tuple(target.get(key) for key in allowed) + (kpi_id,))
    write_audit(
        conn, user["username"], "settings.kpi.rollback", "kpi", kpi_id,
        detail={"historyId": history_id},
    )
    return ok({"kpiId": kpi_id, "historyId": history_id},
              msg="指标展示配置已回滚")


@router.post("/settings/kpi-config")
def create_kpi_config(body: dict,
                      _: dict = Depends(require_admin),
                      conn: sqlite3.Connection = Depends(get_db_rw)):
    raise ApiError("暂不支持创建任意 KPI；请先在后端公式注册表实现并验证计算口径",
                   code=410, status_code=410)
