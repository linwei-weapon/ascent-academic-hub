"""Sequential, read-only environment checks. Never persist student detail rows.

Run from code with the project virtualenv. --probe reads fixed aggregate
coverage queries. --execute runs registered MySQL templates, including blocked
formulas solely as technical SQL probes; it never changes their approval.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))
from backend.metric_verification.config import load_environment
from backend.metric_verification.database import connection, bind_parameters, execute_read, json_value
from backend.metric_verification.registry import queries_document, find_query

RUNTIME = CODE.parent / "work" / "runtime" / "highedu-start"
PROBES = {
    "grade_flags": ("fact", "SELECT is_published,is_pass,is_void,COUNT(*) AS records FROM act_grade_attempt GROUP BY is_published,is_pass,is_void"),
    "grade_types": ("fact", "SELECT attempt_type,is_retake,COUNT(*) AS records FROM act_grade_attempt GROUP BY attempt_type,is_retake"),
    "grade_coverage": ("fact", "SELECT COUNT(*) AS records,COUNT(credits) AS with_credits,COUNT(gpa) AS with_gpa,COUNT(published_date_time) AS with_published_time,COUNT(input_date_time) AS with_input_time,COUNT(DISTINCT attempt_id) AS distinct_attempts FROM act_grade_attempt"),
    "grade_batches": ("fact", "SELECT source,batch_id,COUNT(*) AS records FROM act_grade_attempt GROUP BY source,batch_id"),
    "source_grade_states": ("source", "SELECT STATE,GRADE_STATUS,PUBLISHED,PASSED,COUNT(*) AS records FROM grade GROUP BY STATE,GRADE_STATUS,PUBLISHED,PASSED"),
    "student_enrolment": ("fact", "SELECT has_xue_ji,in_school,std_status,COUNT(*) AS records FROM act_student GROUP BY has_xue_ji,in_school,std_status"),
    "source_student_enrolment": ("source", "SELECT ZAI_JI,HAS_XUE_JI,IN_SCHOOL,COUNT(*) AS records FROM student GROUP BY ZAI_JI,HAS_XUE_JI,IN_SCHOOL"),
    "teacher_population": ("fact", "SELECT hire_type,is_on_job,staff_type,COUNT(*) AS records FROM act_staff GROUP BY hire_type,is_on_job,staff_type"),
    "plan_course_states": ("fact", "SELECT status,requirement_type,is_pass,COUNT(*) AS records FROM act_student_plan_course_status GROUP BY status,requirement_type,is_pass"),
    "plan_module_states": ("fact", "SELECT status,COUNT(*) AS records,COUNT(required_credits) AS required_credits_present,COUNT(completion_pct) AS completion_pct_present FROM act_student_plan_module_status GROUP BY status"),
    "growth_types": ("fact", "SELECT event_type,source,batch_id,COUNT(*) AS records FROM act_student_timeline_event GROUP BY event_type,source,batch_id"),
    "alert_hit_coverage": ("fact", "SELECT a.is_active,a.is_resolved,r.enabled,COUNT(*) AS records,COUNT(DISTINCT a.student_id) AS students FROM act_alert a LEFT JOIN sys_alert_rule r ON r.id=a.rule_id GROUP BY a.is_active,a.is_resolved,r.enabled"),
    "alert_id_uniqueness": ("fact", "SELECT COUNT(*) AS records,COUNT(DISTINCT alert_id) AS distinct_alerts FROM act_alert"),
    "grade_value_coverage": ("fact", "SELECT COUNT(*) AS records,COUNT(credits) AS with_credits,COUNT(gpa) AS with_gpa,COUNT(published_date_time) AS with_published_time,COUNT(input_date_time) AS with_input_time,SUM(score < 0 OR score > 100) AS out_of_range_scores FROM act_grade_attempt"),
    "source_grade_state": ("source", "SELECT STATE,COUNT(*) AS records FROM grade GROUP BY STATE"),
    "alert_code_coverage": ("fact", "SELECT COUNT(*) AS records,COUNT(r.id) AS matching_rule_code,SUM(r.enabled=1) AS enabled_matched FROM act_alert a LEFT JOIN sys_alert_rule r ON r.rule_code=a.rule_code"),
    "rule_code_uniqueness": ("fact", "SELECT COUNT(*) AS rules,COUNT(DISTINCT rule_code) AS distinct_codes FROM sys_alert_rule"),
}


def atomic_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(6):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.1)


def error_summary(error):
    # Driver messages can contain network addresses, database users or literals.
    return {"errorType": type(error).__name__, "errorCode": error.args[0] if error.args and isinstance(error.args[0], int) else None}


def probe(only_names=None):
    report = {"checkedAt": datetime.now(timezone.utc).isoformat(), "mode": "read_only_aggregate_probes", "checks": []}
    path = RUNTIME / "metric-verification-enumeration-evidence.json"
    if only_names and path.exists():
        report["checks"] = [r for r in json.loads(path.read_text(encoding="utf-8"))["checks"] if r["id"] not in only_names]
    for name, (layer, sql) in PROBES.items():
        if only_names and name not in only_names:
            continue
        started = time.perf_counter()
        item = {"id": name, "layer": layer, "sql": sql}
        try:
            with connection(layer) as conn, conn.cursor() as cur:
                cur.execute(sql)
                item.update(status="success", aggregates=[{k: json_value(v) for k, v in row.items()} for row in cur.fetchall()])
        except Exception as error:
            item.update(status="failed", **error_summary(error))
        item["durationMs"] = round((time.perf_counter() - started) * 1000)
        report["checks"].append(item)
        atomic_report(path, report)
        print(json.dumps({"probe": name, "status": item["status"], "durationMs": item["durationMs"]}), flush=True)
    return report


def one(layer, sql, parameters=None):
    for attempt in range(2):
        try:
            with connection(layer) as conn, conn.cursor() as cur:
                cur.execute(sql, parameters)
                return cur.fetchone()
        except Exception as error:
            if attempt or error_summary(error)["errorCode"] not in {0, 2003, 2013}:
                raise


def seeds():
    # These IDs are used only in memory as bound query parameters. The saved
    # execution report excludes student_id and hashes the full parameter set.
    result = {"organization_id": None, "college_id": None, "major_id": None, "grade": None,
              "in_school_flag": 1, "has_xue_ji_flag": 1, "base_metric_id": "O-10",
              "minimum_sample": 0, "result_batch_id": None, "rule_version": "1"}
    chosen = one("fact", "SELECT student_id,course_id,semester_id,batch_id FROM act_grade_attempt WHERE source='real' AND is_published=1 AND is_pass IS NOT NULL ORDER BY id DESC LIMIT 1")
    result.update(chosen)
    result["grade_batch_id"] = result.pop("batch_id")
    for param, table in [("student_batch_id", "act_student"), ("course_batch_id", "act_course"), ("teacher_batch_id", "act_staff"), ("lesson_batch_id", "act_teaching_lesson"), ("event_batch_id", "act_student_status_event")]:
        row = one("fact", f"SELECT batch_id FROM {table} WHERE source='real' AND batch_id IS NOT NULL ORDER BY id DESC LIMIT 1")
        result[param] = row["batch_id"] if row else None
    row = one("fact", "SELECT batch_id FROM act_alert WHERE batch_id IS NOT NULL ORDER BY id DESC LIMIT 1")
    result["alert_batch_id"] = row["batch_id"] if row else None
    row = one("fact", "SELECT semester_id FROM act_grade_attempt WHERE source='real' AND semester_id <> %s ORDER BY id DESC LIMIT 1", (result["semester_id"],))
    result["previous_semester_id"] = row["semester_id"] if row else None
    result["pass_rule_version"] = (one("application", "SELECT rule_version FROM agg_course_pass_stat ORDER BY id DESC LIMIT 1") or {}).get("rule_version")
    return result


def execute(only_ids=None, resume=False):
    seed = seeds()
    doc = queries_document()
    report = {"checkedAt": datetime.now(timezone.utc).isoformat(), "registryVersion": doc["version"],
              "mode": "read_only_sql_execution_not_metric_acceptance", "privateRowsStored": False,
              "scope": {k: v for k, v in seed.items() if k not in {"student_id"}}, "checks": []}
    path = RUNTIME / "metric-verification-live-check.json"
    previous = {}
    if resume and path.exists():
        previous = {r['queryId']: r for r in json.loads(path.read_text(encoding='utf-8'))['checks']}
    for metric in doc["metrics"]:
        for layer in metric["layers"]:
            for raw in layer["queries"]:
                if raw["dialect"] != "mysql" or (only_ids and raw["id"] not in only_ids):
                    continue
                q = find_query(raw["id"])
                params = {p['name']: seed.get(p['name']) for p in q['parameters']}
                if "rule_version" in params and "AGG_COURSE_PASS_STAT" in q["requiredTables"]:
                    params["rule_version"] = seed["pass_rule_version"]
                item = {"queryId": q["id"], "metricId": q["metricId"], "layer": q["layer"], "kind": q["kind"],
                        "executionApproval": q["executionApproval"], "sqlChecksum": q["checksum"],
                        "parametersChecksum": hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()}
                old = previous.get(q['id'])
                if old and old['status'] == 'success' and all(old.get(key) == item[key] for key in ('sqlChecksum', 'parametersChecksum', 'executionApproval')):
                    report['checks'].append(old)
                    continue
                if old and old['status'] != 'success':
                    item['priorAttempts'] = old.get('priorAttempts', []) + [{k:old.get(k) for k in ['status','errorType','errorCode','durationMs']}]
                started = time.perf_counter()
                try:
                    params = bind_parameters(q, params)
                    with connection(q["layer"]) as conn:
                        result = execute_read(conn, q, params, "mysql", 100)
                    item.update(status="success", returnedRows=result["returnedRows"], truncated=result["truncated"], columns=result["columns"],
                                recordCount=result["recordCount"] if q["kind"] == "count" else None,
                                interpretation="技术执行成功，未批准计算不得作为正式指标" if q["executionApproval"] != "documented" else "查询执行成功，业务验收另行判断")
                except Exception as error:
                    item.update(status="failed", **error_summary(error))
                    item['failureCategory'] = 'timeout' if item.get('errorCode') == 3024 else ('connection' if item.get('errorCode') in {0,2003,2013} else 'query_or_parameter')
                item["durationMs"] = round((time.perf_counter() - started) * 1000)
                report["checks"].append(item)
                atomic_report(path, report)
                print(json.dumps({"queryId": q["id"], "status": item["status"], "durationMs": item["durationMs"]}), flush=True)
    report["summary"] = {"checked": len(report["checks"]), "success": sum(r["status"] == "success" for r in report["checks"]), "failed": sum(r["status"] == "failed" for r in report["checks"])}
    atomic_report(path, report)
    return report


def boundaries():
    seed = seeds()
    q = find_query('O-01-fact-detail-mysql')
    path = RUNTIME / 'metric-verification-live-boundaries.json'
    report = {'checkedAt':datetime.now(timezone.utc).isoformat(),'privateRowsStored':False,'mode':'read_only_api_limit_and_empty_set','checks':[]}
    for name, student, limit in [('real_empty_set', 'MV-NONEXISTENT-STUDENT-BOUNDARY', 50),('fifty_row_cap', None, 50)]:
        params = {p['name']:seed.get(p['name']) for p in q['parameters']}
        params['student_id'] = student
        item = {'id':name,'queryId':q['id'],'apiLimit':limit}
        try:
            with connection('fact') as conn:
                result = execute_read(conn,q,bind_parameters(q,params),'mysql',limit)
            item.update(status='success', returnedRows=result['returnedRows'], truncated=result['truncated'], recordCount=result['recordCount'])
            assert result['returnedRows'] == (0 if student else 50)
            assert bool(result['truncated']) is (student is None)
        except Exception as error:
            item.update(status='failed',**error_summary(error))
        report['checks'].append(item)
    report['failureEvidence'] = {'report':'metric-verification-enumeration-evidence.json','probe':'source_grade_state','status':'failed','errorCode':3024,'meaning':'真实聚合在15秒服务器限时中断；不记作零记录或通过'}
    atomic_report(path, report)
    print(json.dumps(report,ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--query", action="append")
    parser.add_argument("--probe-name", action="append")
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--boundaries', action='store_true')
    args = parser.parse_args()
    load_environment()
    os.environ["MV_QUERY_TIMEOUT_SECONDS"] = str(max(1, min(15, args.timeout)))
    if args.probe:
        probe(set(args.probe_name) if args.probe_name else None)
    if args.execute:
        execute(set(args.query) if args.query else None, resume=args.resume)
    if args.boundaries:
        boundaries()
