"""Build documented, read-only teaching-overview verification queries.

This script never connects to a database. The SQL is based on the two V6
documents and requirement 106; it does not certify the deployed schema or
school policy. Run metric_verification_check_queries.py for isolated checks.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from collections import defaultdict
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE / "metric-verification"
SQL_ROOT = ROOT / "sql" / "teaching-overview"
OUT = ROOT / "queries" / "teaching-overview.json"

CORE = ["O-01", "O-02", "O-03", "O-05", "O-06", "O-08", "O-09", "O-10", "O-11", "O-13", "O-14", "O-16", "O-17", "O-18", "O-19", "O-20", "O-21", "O-22", "O-23"]
EXTRA = """TERM-COURSE-COUNT TEACHER-COUNT FIRST-PASS-RATE MAKEUP-PASS-RATE
RETAKE-PASS-RATE PUBLIC-FIRST-PASS-RATE GPA-DISTRIBUTION GPA-RANK
PRIORITY-MAJOR-COUNT CREDIT-PASS-RATIO VALID-ATTEMPT-COUNT COURSE-MEAN-SCORE
COURSE-EXCELLENT-RATE SCORE-DISTRIBUTION GRADE-COURSE-COUNT STUDENT-TERM-GPA
UNRESOLVED-COURSE-COUNT REPEAT-UNRESOLVED-COUNT ACTIVE-RULE-COUNT EARNED-CREDITS
PASSED-COURSE-COUNT STUDY-HOURS PLAN-MODULE-COMPLETION PLAN-RULE-COVERAGE
PLAN-GAP-MODULES PLAN-CANDIDATE-MODULES ALERT-HISTORY-COUNT FOLLOWUP-COUNT
ALERT-TRAJECTORY GROWTH-EVENT-COUNT GPA-ARITHMETIC RETAKE-ATTEMPT-COUNT
STATUS-EVENT-COUNT REQUIRED-FAILURE-COUNT REPEAT-FAILURE-ATTEMPTS
PLAN-CANDIDATE-COURSES""".split()

AUDIT_EXTRA = """COLLEGE-EXCESS-IMPACT COURSE-TOP10-MEAN-SCORE COURSE-TOP6-MEAN-SCORE
COURSE-EXCELLENT-COUNT FILTERED-STUDENT-COUNT STUDENT-PERIOD-GPA STUDENT-COURSE-RESULT
TERM-FAILED-COURSE-COUNT TERM-EARNED-CREDITS CURRENT-PASSED-COURSE-COUNT
CURRENT-FAILED-COURSE-COUNT CURRENT-EARNED-CREDITS EVIDENCE-RULE-COUNT
CURRENT-ALERT-RECORD-COUNT HIGHEST-ALERT-LEVEL MANAGEMENT-ATTENTION ALERT-CHANGE
HISTORICAL-FAILED-COURSES DIFFICULTY-EVIDENCE R2-UNRESOLVED-COURSES""".split()
AUDIT_IDS = {'MV106-' + key for key in AUDIT_EXTRA}
PERSONAL_EVIDENCE_IDS = {'O-06'} | {'MV106-' + key for key in (
    'UNRESOLVED-COURSE-COUNT REPEAT-UNRESOLVED-COUNT EARNED-CREDITS PASSED-COURSE-COUNT '
    'STUDY-HOURS GPA-ARITHMETIC RETAKE-ATTEMPT-COUNT REPEAT-FAILURE-ATTEMPTS '
    'REQUIRED-FAILURE-COUNT STUDENT-TERM-GPA STUDENT-PERIOD-GPA STUDENT-COURSE-RESULT '
    'TERM-FAILED-COURSE-COUNT TERM-EARNED-CREDITS CURRENT-PASSED-COURSE-COUNT '
    'CURRENT-FAILED-COURSE-COUNT CURRENT-EARNED-CREDITS HISTORICAL-FAILED-COURSES '
    'DIFFICULTY-EVIDENCE R2-UNRESOLVED-COURSES').split()}
AUDIT_CHANGED_IDS = {'O-03', 'O-21', 'O-23'} | PERSONAL_EVIDENCE_IDS | AUDIT_IDS
O03_PENDING = '106第12章明确Σ(有效数值成绩×学分)÷Σ计入学分且学分>0；观察期内重复成绩是否去重、采用哪条结果及页面落点待明确。本模板按有效记录加权，仅为候选，禁止把未确认去重策略当正式口径。'
O23_PENDING = '106§7.3/O-23没有明确最新有效成绩缺GP时是否回退旧GP。当前SQL展示先选最新结果再排除缺GP的候选解释，另一解释为先筛有GP再取最后记录；两者均未确认，计算保持阻止，不能引用学生总GPA规则代替决定。'

VALIDITY = "V6仅明确已发布且结果非空；106还要求未作废。GRADE_STATUS/STATE作废码、缓考缺考取消资格规则须确认，不能把候选有效记录当已签版验收基准。"
GPA_RULE = "学校绩点规则、CALCULATE_GP、重修覆盖及修读时点学分版本须确认；当前模板使用源GP及课程主数据学分，不能默认为正式GPA口径。"
ENROLLED = "在籍状态与统计时点未确认：Oracle有ZAI_JI，V6 ACT_STUDENT未映射此字段；HAS_XUE_JI和IN_SCHOOL不能直接等同有效在籍。历史学期须绑定对应学籍快照。"
LATEST = "最新有效结果排序须确认学期顺序、补重修覆盖及相同时间记录决胜规则；模板按发布时间/录入时间/尝试ID形成可重复候选排序，未签版不得作为最终值。"
FACT_GRADE_EVIDENCE = "2026-09-29只读汇总：3434801条成绩全部is_void=0、credits与录入时间有值；3422123条有GP，1195541条有发布时间，4条分数超[0,100]。事实有效条件使用real、指定批次、已发布、未作废且is_pass为0/1；GP采用现有成绩原值，复算不证明源GP转换正确。attempt_type全空、is_retake大量空，不能反推首次/补考。最新覆盖和时间决胜仍需依据。"
APP_UNKNOWN = "V6未定位该指标的同粒度应用结果字段；待核对实际页面接口及SQL。不得用SYS指标配置行数代替业务结果。"
SOURCE_ENGINE = "该结果由平台规则或人工过程生成，Oracle没有对应结果表；须按实际规则版本逐项登记输入表和加工关系，不能编造Oracle结果。"

PARAMS = {
    "organization_id": ("学院（空值仅限服务端授权全校）", "string", "business"),
    "college_id": ("应用表学院键college_id（未证明等同组织ID；空值查授权全校）", "string", "business"),
    "major_id": ("专业", "string", "business"),
    "grade": ("入学年级", "string", "business"),
    "student_id": ("学生标识", "string", "business"),
    "course_id": ("课程标识", "string", "business"),
    "semester_id": ("当前学期标识", "string", "business"),
    "previous_semester_id": ("上一可比学期标识", "string", "business"),
    "student_batch_id": ("学生快照批次", "string", "batch"),
    "grade_batch_id": ("成绩采集批次", "string", "batch"),
    "course_batch_id": ("课程采集批次", "string", "batch"),
    "alert_batch_id": ("可靠预警计算批次", "string", "batch"),
    "lesson_batch_id": ("教学任务采集批次", "string", "batch"),
    "teacher_batch_id": ("授课关系采集批次", "string", "batch"),
    "event_batch_id": ("事件采集批次", "string", "batch"),
    "result_batch_id": ("派生结果批次（空值仅查未标记批次，不等于全量）", "string", "batch"),
    "in_school_flag": ("候选在校标记（不是已确认在籍定义）", "integer", "policy"),
    "has_xue_ji_flag": ("候选有学籍标记", "integer", "policy"),
    "rule_version": ("规则版本", "string", "policy"),
    "base_metric_id": ("偏离/变化的基础指标编号", "string", "policy"),
    "minimum_sample": ("课程最小有效人次（学院TOP6按106为0）", "integer", "policy"),
}
OPTIONAL = {"organization_id", "college_id", "major_id", "grade", "course_id", "student_id"}


class Context:
    def __init__(self, source: bool = False):
        self.source = source
        self.columns: dict[str, set[str]] = defaultdict(set)
        self.aliases: dict[str, str] = {}
        self.required = set()

    def table(self, alias: str, source: str, fact: str | None = None) -> str:
        table = source if self.source else (fact or source)
        self.aliases[alias] = table
        return f"{table} {alias}"

    def col(self, alias: str, source: str, fact: str | None = None) -> str:
        column = source if self.source else (fact or source)
        self.columns[self.aliases[alias]].add(column)
        return f"{alias}.{column}"

    def p(self, name: str, required: bool | None = None) -> str:
        if required is True or (required is None and name not in OPTIONAL):
            self.required.add(name)
        return ":" + name

    def opt(self, name: str, col: str) -> str:
        p = self.p(name)
        return f"({p} IS NULL OR {col} = {p})"

    def student(self) -> tuple[str, list[str]]:
        table = self.table("s", "STUDENT", "ACT_STUDENT")
        filters = [self.opt("organization_id", self.col("s", "DEPARTMENT_ID", "organization_id")),
                   self.opt("major_id", self.col("s", "MAJOR_ID", "major_id")),
                   self.opt("grade", self.col("s", "GRADE", "entry_grade")),
                   self.opt("student_id", self.col("s", "ID", "student_id"))]
        if not self.source:
            filters += [f"{self.col('s', 'batch_id')} = {self.p('student_batch_id')}", f"{self.col('s', 'source')} = 'real'"]
        return table, filters

    def metadata(self) -> dict[str, list[str]]:
        return {t: sorted(cols) for t, cols in sorted(self.columns.items())}


def where(filters: list[str]) -> str:
    return "\nWHERE " + "\n  AND ".join(filters)


def query(mid: str, lid: str, kind: str, dialect: str, sql: str, ctx: Context,
          blocked: str = "", note: str = "", variant: str = "") -> dict:
    qid = "-".join(x for x in [mid, lid, kind, dialect, variant] if x)
    sql = sql.strip().rstrip(";") + "\n"
    names = sorted(set(re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", sql)))
    parameters = []
    for name in names:
        label, ptype, source = PARAMS.get(name, (name, "string", "business"))
        parameters.append(dict(name=name, label=label, type=ptype, required=name in ctx.required, source=source))
    q = dict(id=qid, kind=kind, dialect=dialect,
             sqlFile=f"sql/teaching-overview/{qid}.sql", sql=sql,
             parameters=parameters, requiredTables=list(ctx.metadata()),
             requiredColumns=ctx.metadata(), version="1.0.0",
             executionApproval="blocked" if blocked else "documented",
             requiresServerScope=True, note=note,
             scopeBinding="服务端按当前身份校验学院、专业、年级、课程及学生交集；空组织只允许明确的全校授权，不以参数空值推断授权。",
             resultRole="candidate_calculation" if kind == "calculate" and blocked else ("source_evidence" if lid != "application" else "application_candidate"))
    if kind == "detail":
        q["maxRows"] = 100
    if blocked:
        q["blockedReason"] = blocked
    return q


def layer(lid: str, tables: list[str] | None = None, grain: str = "待确认", issues: list[str] | None = None,
          transform: list[str] | None = None) -> dict:
    return dict(id=lid, name={"source": "贴源层", "fact": "事实层", "application": "应用层"}[lid],
                tables=tables or [], grain=grain, transform=transform or [], issues=issues or [],
                status="blocked", queries=[])


def add_set(target: dict, mid: str, ctx: Context, base: str, order: str, calc: str | None = None,
            blocked: str = "", note: str = "", count: str | None = None, calc_variant: str = ""):
    lid = target["id"]
    dialects = ["mysql", "oracle"] if ctx.source else ["mysql"]
    for dialect in dialects:
        cte = "WITH input_rows AS (\n" + base + "\n)\n"
        count_sql = count or (cte + "SELECT COUNT(*) AS matched_records FROM input_rows")
        detail = cte + "SELECT * FROM input_rows\nORDER BY " + order
        detail += "\nFETCH FIRST 100 ROWS ONLY" if dialect == "oracle" else "\nLIMIT 100"
        target["queries"] += [query(mid, lid, "count", dialect, count_sql, ctx, note=note),
                              query(mid, lid, "detail", dialect, detail, ctx, note=note)]
        if calc:
            target["queries"].append(query(mid, lid, "calculate", dialect, calc, ctx, blocked=blocked, note=note, variant=calc_variant))
    target["tables"] = sorted(set(target["tables"]) | set(ctx.metadata()))
    target["status"] = "documented"
    if blocked and blocked not in target["issues"]:
        target["issues"].append(blocked)


def grade_rows(source: bool, *, term: str = "current", credits: bool = False, course_required: bool = False,
               student_required: bool = False) -> tuple[Context, str]:
    c = Context(source)
    gt = c.table("g", "GRADE", "ACT_GRADE_ATTEMPT")
    st, filters = c.student()
    g = lambda raw, fact=None: c.col("g", raw, fact)
    s = lambda raw, fact=None: c.col("s", raw, fact)
    fields = [(g("ID", "attempt_id"), "attempt_id"), (g("STUDENT_ID", "student_id"), "student_id"),
              (g("COURSE_ID", "course_id"), "course_id"), (g("SEMESTER_ID", "semester_id"), "semester_id"),
              (g("SCORE", "score"), "score"), (g("GP", "gpa"), "gpa"),
              (g("PUBLISHED", "is_published"), "is_published"), (g("PASSED", "is_pass"), "is_pass"),
              (g("GRADE_STATUS", "grade_status"), "grade_status"), (g("RETAKE", "is_retake"), "is_retake"),
              (g("PUBLISHED_DATE_TIME", "published_date_time"), "published_date_time"),
              (g("INPUT_DATE_TIME", "input_date_time"), "input_date_time"),
              (s("DEPARTMENT_ID", "organization_id"), "organization_id"), (s("MAJOR_ID", "major_id"), "major_id"),
              (s("GRADE", "entry_grade"), "entry_grade")]
    join = f"\nFROM {gt}\nJOIN {st} ON {s('ID', 'student_id')} = {g('STUDENT_ID', 'student_id')}"
    if credits:
        ct = c.table("c", "COURSE", "ACT_COURSE")
        join += f"\nLEFT JOIN {ct} ON {c.col('c', 'ID', 'course_id')} = {g('COURSE_ID', 'course_id')}"
        if not source:
            join += f" AND {c.col('c', 'batch_id')} = {c.p('course_batch_id')} AND {c.col('c', 'source')} = 'real'"
        fields += [(c.col("c", "CREDITS", "credits") if source else g("credits"), "credits"), (c.col("c", "CALCULATE_GP", "calculate_gp"), "calculate_gp")]
    if term == "current":
        filters += [f"{g('SEMESTER_ID', 'semester_id')} = {c.p('semester_id')}"]
    elif term == "pair":
        filters += [f"{g('SEMESTER_ID', 'semester_id')} IN ({c.p('semester_id')}, {c.p('previous_semester_id')})"]
    filters += [c.opt("course_id", g("COURSE_ID", "course_id"))]
    if course_required:
        c.required.add("course_id")
        filters[-1] = f"{g('COURSE_ID', 'course_id')} = :course_id"
    if student_required:
        c.required.add("student_id")
        filters += [f"{g('STUDENT_ID', 'student_id')} = :student_id"]
    if not source:
        filters += [f"{g('batch_id')} = {c.p('grade_batch_id')}", f"{g('source')} = 'real'"]
        fields += [(g("source_row_no"), "source_row_no"), (g("batch_id"), "batch_id")]
        fields += [(g('id'), 'fact_row_id')]
        fields += [(g("is_void"), "is_void"), (g("attempt_type"), "attempt_type"),
                   (g("credits"), "attempt_credits"), (g("publish_status"), "publish_status"), (g("exam_status"), "exam_status")]
    return c, "SELECT " + ",\n       ".join(f"{expr} AS {name}" for expr, name in fields) + join + where(filters)


def valid_cte(base: str) -> str:
    validity = "is_published = 1 AND is_pass IN (0, 1)" + (" AND is_void = 0" if " AS is_void" in base else "")
    return "WITH input_rows AS (\n" + base + "\n), valid_rows AS (\n  SELECT * FROM input_rows WHERE " + validity + "\n)\n"


def student_gpa_cte(base: str) -> str:
    return valid_cte(base).rstrip() + ", student_gpa AS (\n  SELECT student_id, SUM(gpa * credits) / NULLIF(SUM(credits), 0) AS term_gpa,\n         SUM(credits) AS included_credits\n  FROM valid_rows WHERE gpa IS NOT NULL AND credits > 0\n  GROUP BY student_id\n)\n"


def latest_cte(base: str, gp_required: bool = False) -> str:
    # Stable candidate ordering is documented and blocked until school confirms it.
    return valid_cte(base).rstrip() + ", ranked AS (\n  SELECT valid_rows.*, ROW_NUMBER() OVER (\n    PARTITION BY student_id, course_id\n    ORDER BY CASE WHEN published_date_time IS NULL THEN 1 ELSE 0 END, published_date_time DESC,\n             CASE WHEN input_date_time IS NULL THEN 1 ELSE 0 END, input_date_time DESC, attempt_id DESC" + (', fact_row_id DESC' if ' AS fact_row_id' in base else '') + "\n  ) AS result_rank\n  FROM valid_rows\n), latest_rows AS (SELECT * FROM ranked WHERE result_rank = 1" + (" AND gpa IS NOT NULL" if gp_required else "") + ")\n"


def grade_calculation(mid: str, base: str) -> tuple[str | None, str]:
    v = valid_cte(base)
    common = VALIDITY
    simple = {
        "O-02": "COUNT(DISTINCT student_id)",
        "O-08": "COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END)",
        "O-09": "COUNT(CASE WHEN is_pass = 0 THEN 1 END)",
        "O-20": "COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END)",
        "MV106-VALID-ATTEMPT-COUNT": "COUNT(*)",
        "MV106-GRADE-COURSE-COUNT": "COUNT(DISTINCT course_id)",
        "MV106-RETAKE-ATTEMPT-COUNT": "COUNT(CASE WHEN is_retake = 1 THEN 1 END)",
        "MV106-GPA-ARITHMETIC": "AVG(gpa)",
    }
    if mid in simple:
        if mid == "MV106-GPA-ARITHMETIC":
            return "WITH input_rows AS (\n" + base + "\n)\nSELECT AVG(gpa) AS candidate_metric_value, COUNT(gpa) AS input_records FROM input_rows WHERE is_published = 1 AND gpa IS NOT NULL" + (" AND is_void = 0" if " AS is_void" in base else ""), common
        return v + f"SELECT {simple[mid]} AS candidate_metric_value, COUNT(*) AS input_records FROM valid_rows", common
    if mid == "O-03":
        return v + "SELECT SUM(score * credits) AS weighted_score_sum, SUM(credits) AS included_credits,\n       SUM(score * credits) / NULLIF(SUM(credits), 0) AS candidate_metric_value\nFROM valid_rows WHERE score IS NOT NULL AND credits > 0", common + O03_PENDING
    if mid in {"O-05", "MV106-STUDENT-TERM-GPA"}:
        final = ("SELECT student_id, term_gpa AS candidate_metric_value, included_credits FROM student_gpa ORDER BY student_id" if mid != "O-05" else "SELECT AVG(term_gpa) AS candidate_metric_value, COUNT(*) AS students_with_gpa FROM student_gpa")
        return student_gpa_cte(base) + final, common + GPA_RULE
    if mid == "O-10":
        return v + "SELECT COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) AS numerator,\n       COUNT(DISTINCT student_id) AS denominator,\n       100.0 * COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) / NULLIF(COUNT(DISTINCT student_id), 0) AS candidate_metric_value\nFROM valid_rows", common
    if mid == "O-11":
        return v + "SELECT COUNT(CASE WHEN is_pass = 0 THEN 1 END) AS numerator, COUNT(*) AS denominator,\n       100.0 * COUNT(CASE WHEN is_pass = 0 THEN 1 END) / NULLIF(COUNT(*), 0) AS candidate_metric_value\nFROM valid_rows", common
    if mid == "O-06":
        return latest_cte(base) + "SELECT student_id,\n       SUM(CASE WHEN gpa IS NOT NULL AND credits > 0 THEN gpa * credits END) /\n       NULLIF(SUM(CASE WHEN gpa IS NOT NULL AND credits > 0 THEN credits END), 0) AS candidate_metric_value,\n       SUM(CASE WHEN gpa IS NOT NULL AND credits > 0 THEN credits ELSE 0 END) AS included_credits,\n       COUNT(CASE WHEN gpa IS NULL OR credits IS NULL OR credits <= 0 THEN 1 END) AS excluded_courses\nFROM latest_rows GROUP BY student_id", common + LATEST + GPA_RULE
    if mid == "O-22":
        return latest_cte(base) + "SELECT COUNT(CASE WHEN is_pass = 0 THEN 1 END) AS numerator, COUNT(*) AS denominator,\n       100.0 * COUNT(CASE WHEN is_pass = 0 THEN 1 END) / NULLIF(COUNT(*), 0) AS candidate_metric_value\nFROM latest_rows", common + LATEST
    if mid == "O-23":
        return latest_cte(base, gp_required=True) + "SELECT AVG(gpa) AS candidate_metric_value, COUNT(*) AS students_with_course_gp FROM latest_rows", common + LATEST + O23_PENDING
    if mid == "MV106-CREDIT-PASS-RATIO":
        return v + "SELECT SUM(CASE WHEN is_pass = 1 THEN credits ELSE 0 END) AS passed_credits, SUM(credits) AS attempted_credits,\n       100.0 * SUM(CASE WHEN is_pass = 1 THEN credits ELSE 0 END) / NULLIF(SUM(credits), 0) AS candidate_metric_value\nFROM valid_rows WHERE credits > 0", common + "按有效成绩记录学分加权，不按课程去重，不等同培养方案完成率。历史学分版本待确认。"
    if mid == "MV106-COURSE-MEAN-SCORE":
        return v + "SELECT AVG(score) AS candidate_metric_value, COUNT(score) AS numeric_score_attempts FROM valid_rows", common + "106§7.3使用成绩记录算术均值，§3.11却以去重学生作分母；本模板仅供§7.3口径核查，不覆盖冲突的TOP10均分。"
    if mid == "MV106-COURSE-EXCELLENT-RATE":
        return v + "SELECT COUNT(CASE WHEN score BETWEEN 90 AND 100 THEN 1 END) AS numerator, COUNT(CASE WHEN score BETWEEN 0 AND 100 THEN 1 END) AS denominator,\n       100.0 * COUNT(CASE WHEN score BETWEEN 90 AND 100 THEN 1 END) / NULLIF(COUNT(CASE WHEN score BETWEEN 0 AND 100 THEN 1 END), 0) AS candidate_metric_value,\n       COUNT(CASE WHEN score < 0 OR score > 100 THEN 1 END) AS excluded_out_of_range\nFROM valid_rows", common + "按106百分制分数[0,100]；优秀人次与优秀率分别返回，不把超范围值作为优秀。"
    if mid == "MV106-SCORE-DISTRIBUTION":
        return v + ", bucket_rows AS (\n  SELECT CASE WHEN score < 60 THEN '0-59' WHEN score < 70 THEN '60-69' WHEN score < 80 THEN '70-79' WHEN score < 90 THEN '80-89' ELSE '90-100' END AS bucket\n  FROM valid_rows WHERE score BETWEEN 0 AND 100\n)\nSELECT bucket, COUNT(*) AS attempt_count,\n       100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0) AS share_percent\nFROM bucket_rows GROUP BY bucket ORDER BY bucket", common + "按百分制有效范围[0,100]，连续分数使用左闭右开分档。"
    if mid == "MV106-GPA-DISTRIBUTION":
        return student_gpa_cte(base).rstrip() + ", bucket_rows AS (\n  SELECT CASE WHEN term_gpa < 2 THEN '<2.0' WHEN term_gpa < 2.5 THEN '2.0-2.5' WHEN term_gpa < 3 THEN '2.5-3.0' WHEN term_gpa < 3.5 THEN '3.0-3.5' ELSE '>=3.5' END AS bucket,\n         CASE WHEN term_gpa < 2 THEN 1 WHEN term_gpa < 2.5 THEN 2 WHEN term_gpa < 3 THEN 3 WHEN term_gpa < 3.5 THEN 4 ELSE 5 END AS bucket_order\n  FROM student_gpa WHERE term_gpa IS NOT NULL\n)\nSELECT bucket, COUNT(*) AS student_count,\n       100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0) AS share_percent\nFROM bucket_rows GROUP BY bucket, bucket_order ORDER BY bucket_order", common + GPA_RULE
    if mid == "MV106-GPA-RANK":
        return v.rstrip() + ", student_gpa AS (\n  SELECT organization_id, student_id, SUM(gpa * credits) / NULLIF(SUM(credits), 0) AS term_gpa\n  FROM valid_rows WHERE gpa IS NOT NULL AND credits > 0 GROUP BY organization_id, student_id\n), college_gpa AS (\n  SELECT organization_id, AVG(term_gpa) AS average_student_gpa, COUNT(*) AS students_with_gpa\n  FROM student_gpa GROUP BY organization_id\n)\nSELECT organization_id, average_student_gpa, students_with_gpa,\n       RANK() OVER (ORDER BY average_student_gpa DESC) AS candidate_rank, COUNT(*) OVER () AS comparable_colleges\nFROM college_gpa ORDER BY candidate_rank, organization_id", common + GPA_RULE + "106的GPA排名按学院，不是学生排名。须使用完整授权可比学院总体，并列排名及学院可比性规则待确认；不能先限定单学院再声称全校排名。"
    if mid in {"MV106-EARNED-CREDITS", "MV106-PASSED-COURSE-COUNT", "MV106-STUDY-HOURS"}:
        expr = {"MV106-EARNED-CREDITS": "SUM(credits)", "MV106-PASSED-COURSE-COUNT": "COUNT(*)", "MV106-STUDY-HOURS": "SUM(credits) * 16"}[mid]
        if mid != 'MV106-STUDY-HOURS':
            return latest_cte(base).rstrip() + ", passed_courses AS (SELECT student_id, course_id, MAX(credits) AS credits FROM valid_rows WHERE is_pass = 1 GROUP BY student_id, course_id), history_summary AS (SELECT student_id, " + expr + " AS profile_ever_passed_value FROM passed_courses GROUP BY student_id), current_summary AS (SELECT student_id, " + expr + " AS growth_current_passed_value FROM latest_rows WHERE is_pass = 1 GROUP BY student_id), students AS (SELECT DISTINCT student_id FROM valid_rows)\nSELECT s.student_id, COALESCE(h.profile_ever_passed_value, 0) AS profile_ever_passed_value, COALESCE(c.growth_current_passed_value, 0) AS growth_current_passed_value\nFROM students s LEFT JOIN history_summary h ON h.student_id=s.student_id LEFT JOIN current_summary c ON c.student_id=s.student_id ORDER BY s.student_id", common + LATEST + '106§10.3历史曾通过与§10.7当前最新有效通过分列，不能共用一个值；课程学分变动、替代认定和历史通过去重学分取值仍需确认。'
        return v.rstrip() + ", passed_courses AS (SELECT student_id, course_id, MAX(credits) AS credits FROM valid_rows WHERE is_pass = 1 GROUP BY student_id, course_id)\nSELECT student_id, " + expr + " AS candidate_metric_value FROM passed_courses GROUP BY student_id", common + "106§10.3按历史通过课程去重，§10.7按当前有效通过结果；此模板仅对应§10.3，不能混用于成长指标。课程学分变动、替代认定及16学时折算须确认。"
    if mid in {"MV106-UNRESOLVED-COURSE-COUNT", "MV106-REPEAT-UNRESOLVED-COUNT"}:
        count_min = 2 if mid.endswith("REPEAT-UNRESOLVED-COUNT") else 1
        return latest_cte(base).rstrip() + ", failed_history AS (SELECT student_id, course_id, COUNT(*) AS fail_attempts FROM valid_rows WHERE is_pass = 0 GROUP BY student_id, course_id)\nSELECT COUNT(*) AS candidate_metric_value\nFROM latest_rows l JOIN failed_history h ON h.student_id = l.student_id AND h.course_id = l.course_id\nWHERE l.is_pass = 0 AND h.fail_attempts >= " + str(count_min), common + LATEST
    if mid == "MV106-REPEAT-FAILURE-ATTEMPTS":
        return v.rstrip() + ", repeated AS (SELECT student_id, course_id, COUNT(*) AS fail_attempts FROM valid_rows WHERE is_pass = 0 GROUP BY student_id, course_id HAVING COUNT(*) >= 2)\nSELECT COALESCE(SUM(fail_attempts), 0) AS candidate_metric_value FROM repeated", common
    if mid in {"O-17", "O-18"}:
        # The other base indicators require their own policy-checked SQL.
        group = "organization_id" if mid == "O-17" else "semester_id"
        agg = f"rate_rows AS (SELECT {group}, COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) AS failed_students, COUNT(DISTINCT student_id) AS valid_students FROM valid_rows GROUP BY {group})"
        if mid == 'O-17' and 'ACT_GRADE_ATTEMPT' in base:
            agg = agg.replace('FROM valid_rows GROUP BY', "FROM valid_rows WHERE organization_id IN (SELECT organization_id FROM ACT_ORGANIZATION WHERE is_college = 1 AND source = 'real') GROUP BY")
        if mid == "O-18":
            sql = v.rstrip() + ", " + agg + "\nSELECT :base_metric_id AS base_metric_id,\n       MAX(CASE WHEN semester_id = :semester_id THEN 100.0 * failed_students / NULLIF(valid_students, 0) END) AS current_value,\n       MAX(CASE WHEN semester_id = :previous_semester_id THEN 100.0 * failed_students / NULLIF(valid_students, 0) END) AS previous_value,\n       MAX(CASE WHEN semester_id = :semester_id THEN 100.0 * failed_students / NULLIF(valid_students, 0) END) - MAX(CASE WHEN semester_id = :previous_semester_id THEN 100.0 * failed_students / NULLIF(valid_students, 0) END) AS candidate_delta_pp\nFROM rate_rows HAVING :base_metric_id = 'O-10'"
        else:
            sql = v.rstrip() + ", " + agg + ", scope_total AS (SELECT COUNT(DISTINCT CASE WHEN is_pass = 0 THEN student_id END) AS failed_students, COUNT(DISTINCT student_id) AS valid_students FROM valid_rows), deviations AS (\nSELECT r.organization_id, r.valid_students, 100.0 * r.failed_students / NULLIF(r.valid_students, 0) AS organization_value,\n       100.0 * t.failed_students / NULLIF(t.valid_students, 0) AS scope_value,\n       100.0 * r.failed_students / NULLIF(r.valid_students, 0) - 100.0 * t.failed_students / NULLIF(t.valid_students, 0) AS deviation_pp\nFROM rate_rows r CROSS JOIN scope_total t WHERE :base_metric_id = 'O-10'), impacts AS (\nSELECT deviations.*, CASE WHEN deviation_pp > 0 THEN deviation_pp * valid_students / 100.0 ELSE 0 END AS estimated_excess_students FROM deviations)\nSELECT impacts.*, deviation_pp AS candidate_deviation_pp, RANK() OVER (ORDER BY estimated_excess_students DESC) AS impact_rank\nFROM impacts ORDER BY estimated_excess_students DESC, organization_id"
        return sql, common + "本候选模板仅覆盖基础指标O-10；O-05/O-19/O-14和课程辅助通过率须独立绑定各自口径后增加模板。组织比较须使用服务端授权总体；相邻可比学期、历史学籍快照、版本与覆盖变化须确认。"
    specific = {
        "O-21": "用户已确认以106为准：首页TOP10至少1条未通过、不加30人次门槛；学院TOP6包含0样本课程且空分母率为空。仍缺公共必修分类、完整开课候选集合与上期可比结果，当前是成绩输入证据，不能遗漏零样本后宣称完整TOP6。",
        "MV106-FIRST-PASS-RATE": "GRADE是单次修读最终总评，不能从最终通过标记倒推补考前首次通过；需first/regular/deferred分类和首次结果来源。RETAKE有大量NULL，不得把NULL直接当首次。",
        "MV106-MAKEUP-PASS-RATE": "已登记MAKEUP_GRADE.GRADE_ID关联GRADE.ID及SCORE/STATUS/PUBLISHED原值、ACT.makeup_score；缺补考有效/通过状态字典及总评覆盖规则，不能由GRADE总评is_pass倒推补考通过。",
        "MV106-RETAKE-PASS-RATE": "需确认RETAKE/attempt_type的映射、NULL处理、一次重修的有效结果及覆盖方式；仅凭总评is_pass不能形成正式重修分类。",
        "MV106-PUBLIC-FIRST-PASS-RATE": "需公共必修分类的培养方案/课程字典优先级和首次原始结果；不能将所有必修或所有未标记重修记录当公共必修首次。",
        "MV106-PRIORITY-MAJOR-COUNT": "须建立专业与学院同总体O-10及历史学籍快照O-19，再判定偏离≥3pp或覆盖率<70%；当前仅给成绩输入证据，缺在籍分母与两级对照，未生成不完整计算。",
        "MV106-REQUIRED-FAILURE-COUNT": "需有效培养方案绑定、必修课程集合、最终有效失败及后续替代/认定解决关系；成绩COMPULSORY字段不能单独代替方案必修约束。",
    }
    if mid in specific:
        return None, specific[mid]
    return None, "该指标涉及额外输入或冲突规则，尚不能从当前成绩证据生成可靠复算SQL。"


def build_grade_layers(mid: str) -> list[dict]:
    historical = mid in {"O-06", "MV106-UNRESOLVED-COURSE-COUNT", "MV106-REPEAT-UNRESOLVED-COUNT", "MV106-EARNED-CREDITS", "MV106-PASSED-COURSE-COUNT", "MV106-STUDY-HOURS", "MV106-GPA-ARITHMETIC", "MV106-RETAKE-ATTEMPT-COUNT", "MV106-REPEAT-FAILURE-ATTEMPTS", "MV106-REQUIRED-FAILURE-COUNT"}
    credit_metrics = {"O-03", "O-05", "O-06", "MV106-GPA-DISTRIBUTION", "MV106-GPA-RANK", "MV106-STUDENT-TERM-GPA", "MV106-CREDIT-PASS-RATIO", "MV106-EARNED-CREDITS", "MV106-PASSED-COURSE-COUNT", "MV106-STUDY-HOURS"}
    course_required = mid in {"O-20", "O-22", "O-23", "MV106-COURSE-MEAN-SCORE", "MV106-COURSE-EXCELLENT-RATE", "MV106-SCORE-DISTRIBUTION"}
    student_required = historical or mid in {"MV106-STUDENT-TERM-GPA"}
    result = []
    for source, lid in [(True, "source"), (False, "fact")]:
        c, base = grade_rows(source, term="all" if historical else ("pair" if mid == "O-18" else "current"), credits=mid in credit_metrics, course_required=course_required, student_required=student_required)
        if mid == 'MV106-MAKEUP-PASS-RATE':
            if source:
                mt = c.table('mg', 'MAKEUP_GRADE')
                evidence = [(c.col('mg','ID'),'makeup_id'),(c.col('mg','SCORE'),'makeup_score'),(c.col('mg','STATUS'),'makeup_status'),(c.col('mg','PUBLISHED'),'makeup_published')]
                base = base.replace('\nFROM ', ',\n       ' + ', '.join(f'{v} AS {n}' for v,n in evidence) + '\nFROM ', 1)
                base = base.replace('\nWHERE ', f"\nLEFT JOIN {mt} ON {c.col('mg','GRADE_ID')} = {c.col('g','ID')}\nWHERE ", 1)
            else:
                base = base.replace('\nFROM ', ',\n       ' + c.col('g','makeup_score') + ' AS makeup_score\nFROM ', 1)
        if mid == "O-17":
            # The authorized all-school baseline must not shrink with a row filter.
            base = re.sub(r"\(:[a-z_]+ IS NULL OR [a-z]\.[A-Za-z_]+ = :[a-z_]+\)", "1 = 1", base)
            if not source:
                c.table('org', 'ACT_ORGANIZATION')
                for column in ['organization_id', 'is_college', 'source']:
                    c.col('org', column)
        l = layer(lid, grain="学生×课程×修读尝试", issues=[VALIDITY], transform=[
            "按服务端授权学生范围和学期限定原始修读记录；源库原字段与ACT映射可逐项核对。",
            "记录数是完整输入范围的记录条数；明细只取稳定排序前100条，记录数不从明细长度推断。",
            "候选有效条件为已发布且有明确通过结论；SQL同时保留状态码供核查。",
            "源镜像不假设存在batch_id；需用采集台账证明源快照与ACT各表批次对应。" if source else "成绩、学生和课程批次分别绑定；排除sim/prototype，不要求不同表batch_id相等。"])
        if not source:
            l["issues"].append(FACT_GRADE_EVIDENCE)
        calc, blocked = grade_calculation(mid, base)
        if mid in {"O-17", "O-18"}:
            c.required.add("base_metric_id")
        if calc is None:
            l["issues"].append(blocked)
        valid = "is_published = 1 AND is_pass IN (0, 1)" + (" AND is_void = 0" if not source else "")
        count = "WITH input_rows AS (\n" + base + "\n)\nSELECT COUNT(*) AS matched_records,\n       COUNT(CASE WHEN " + valid + " THEN 1 END) AS candidate_valid_attempts,\n       COUNT(DISTINCT CASE WHEN " + valid + " THEN student_id END) AS candidate_valid_students\nFROM input_rows"
        if mid == 'MV106-MAKEUP-PASS-RATE' and source:
            count = "WITH input_rows AS (\n" + base + "\n)\nSELECT COUNT(*) AS matched_records, COUNT(makeup_id) AS linked_makeup_records FROM input_rows"
            l['grain'] = '学生×课程总评×关联补考记录，保留未匹配总评'
            l['transform'].append('MAKEUP_GRADE.GRADE_ID→GRADE.ID，展示补考原始分数/状态/发布标记；补考原始记录不等于最终总评，不以总评is_pass反推补考通过。')
        add_set(l, mid, c, base, "student_id, course_id, semester_id, attempt_id" + (', makeup_id' if source and mid == 'MV106-MAKEUP-PASS-RATE' else '') + (', fact_row_id' if not source else ''), calc, blocked, count=count,
                note="仅登记文档查询；字段验证与实际执行状态由服务端单独记录。", calc_variant="o10" if mid in {"O-17", "O-18"} else "")
        result.append(l)
    return result


def student_layers(mid: str) -> list[dict]:
    layers = []
    for source, lid in [(True, "source"), (False, "fact")]:
        c = Context(source)
        st, filters = c.student()
        fields = [(c.col("s", "ID", "student_id"), "student_id"), (c.col("s", "DEPARTMENT_ID", "organization_id"), "organization_id"),
                  (c.col("s", "HAS_XUE_JI", "has_xue_ji"), "has_xue_ji"), (c.col("s", "IN_SCHOOL", "in_school"), "in_school")]
        if source:
            fields += [(c.col("s", "ZAI_JI"), "zai_ji"), (c.col("s", "STD_STATUS_ID"), "student_status_code")]
        else:
            fields += [(c.col("s", "std_status"), "student_status_name")]
        base = "SELECT " + ", ".join(f"{value} AS {name}" for value, name in fields) + f"\nFROM {st}" + where(filters)
        rule = f"has_xue_ji = {c.p('has_xue_ji_flag')} AND in_school = {c.p('in_school_flag')}"
        calc = "WITH input_rows AS (\n" + base + "\n)\nSELECT COUNT(DISTINCT student_id) AS candidate_metric_value FROM input_rows WHERE " + rule
        l = layer(lid, grain="学生当前快照", issues=[ENROLLED], transform=["源表学籍标记与ACT字段逐项展示；不把在校、有学籍直接等同在籍。", "记录数为当前授权范围学生快照行数，不是已确认O-01人数。"])
        add_set(l, mid, c, base, "student_id", calc, ENROLLED)
        layers.append(l)
    return layers


def coverage_layers() -> list[dict]:
    layers = []
    for source, lid in [(True, "source"), (False, "fact")]:
        c, grades = grade_rows(source)
        # Same student snapshot and same authorized population on both sides.
        st = c.aliases["s"]
        idcol = c.col("s", "ID", "student_id")
        popfilters = [c.opt("organization_id", c.col("s", "DEPARTMENT_ID", "organization_id")), c.opt("major_id", c.col("s", "MAJOR_ID", "major_id")), c.opt("grade", c.col("s", "GRADE", "entry_grade")), c.opt("student_id", idcol),
                      f"{c.col('s', 'IN_SCHOOL', 'in_school')} = {c.p('in_school_flag')}", f"{c.col('s', 'HAS_XUE_JI', 'has_xue_ji')} = {c.p('has_xue_ji_flag')}"]
        if not source:
            popfilters += [f"{c.col('s', 'batch_id')} = :student_batch_id", f"{c.col('s', 'source')} = 'real'"]
        prefix = "WITH population AS (SELECT " + idcol + " AS student_id FROM " + st + " s" + where(popfilters) + "),\ninput_grades AS (\n" + grades + "\n), valid_students AS (SELECT DISTINCT student_id FROM input_grades WHERE is_published = 1 AND is_pass IS NOT NULL),\ninput_rows AS (SELECT p.student_id, CASE WHEN v.student_id IS NULL THEN 0 ELSE 1 END AS has_valid_grade FROM population p LEFT JOIN valid_students v ON v.student_id = p.student_id)\n"
        l = layer(lid, grain="同一候选在籍学生总体", issues=[ENROLLED, VALIDITY], transform=["先构造候选在籍总体，再与当期有效成绩学生求交集，防止分子包含分母外学生。", "贴源/事实记录数均为候选总体学生行数；此指标输入不是成绩人次。"])
        if not source:
            l["issues"].append(FACT_GRADE_EVIDENCE)
        for dialect in (["mysql", "oracle"] if source else ["mysql"]):
            detail = prefix + "SELECT * FROM input_rows ORDER BY student_id" + (" FETCH FIRST 100 ROWS ONLY" if dialect == "oracle" else " LIMIT 100")
            l["queries"] += [query("O-19", lid, "count", dialect, prefix + "SELECT COUNT(*) AS matched_records, COALESCE(SUM(has_valid_grade), 0) AS candidate_valid_students FROM input_rows", c),
                             query("O-19", lid, "detail", dialect, detail, c),
                             query("O-19", lid, "calculate", dialect, prefix + "SELECT COALESCE(SUM(has_valid_grade), 0) AS numerator, COUNT(*) AS denominator, 100.0 * SUM(has_valid_grade) / NULLIF(COUNT(*), 0) AS candidate_metric_value FROM input_rows", c, blocked=ENROLLED + VALIDITY)]
        l.update(tables=list(c.metadata()), status="documented")
        layers.append(l)
    return layers


def application(mid: str) -> dict:
    app = layer("application", issues=[APP_UNKNOWN])
    college = {"O-01": "student_count", "O-02": "student_count", "O-03": "avg_score", "O-05": "gpa_avg", "O-10": "fail_rate", "O-14": "alert_rate", "O-17": "fail_rate", "O-18": "fail_rate"}
    course = {"O-11": "fail_rate", "MV106-COURSE-MEAN-SCORE": "avg_score", "MV106-COURSE-EXCELLENT-RATE": "excellent_rate"}
    c = Context()
    if mid in college or mid in course:
        is_course = mid in course
        table = "AGG_COURSE_TERM" if is_course else "AGG_COLLEGE_TERM"
        value = (course if is_course else college)[mid]
        tab = c.table("a", table)
        key = "course_id" if is_course else "organization_id"
        fields = [key, "semester_id", value, "source"]
        filters = [c.opt(key, c.col("a", key)), f"{c.col('a', 'source')} = '{'real' if is_course else 'derived'}'"]
        if mid == "O-18":
            filters += [f"{c.col('a', 'semester_id')} IN ({c.p('semester_id')}, {c.p('previous_semester_id')})"]
        else:
            filters += [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}"]
        if is_course:
            c.required.add("course_id")
            filters[0] = "a.course_id = :course_id"
        base = "SELECT " + ", ".join(c.col("a", f) for f in fields) + "\nFROM " + tab + where(filters)
        app.update(grain="课程×学期" if is_course else "学院×学期", issues=[f"{table}.{value}仅为文档候选；分子分母、单位及刷新批次需与实际接口确认，不能直接等同{mid}。"])
        if is_course:
            app["issues"].append("该聚合表无学院/专业/年级维度，受限组织不能通过课程ID查全校结果；服务端仅允许全校范围执行此模板。")
            app["issues"].append("2026-09-29测试库AGG_COURSE_TERM的33429条记录source实际为real，故证据过滤使用real；此标签不证明聚合计算已通过需求核验。")
            app["schemaEvidence"] = {"checkedAt": "2026-09-29", "basis": "测试库字段及source分组汇总"}
        app["transform"] = ["读取已有应用对象的实际存储值；count统计聚合记录条数，不能与学生数/成绩人次相减。"]
        add_set(app, mid, c, base, key + ", semester_id")
        for q in app["queries"]:
            q["scopeMode"] = "school_only" if is_course else "organization_aggregate"
        return app
    if mid in {"O-22", "O-23", "O-06", "MV106-UNRESOLVED-COURSE-COUNT", "MV106-REPEAT-UNRESOLVED-COUNT"}:
        tab = c.table("a", "AGG_STUDENT_COURSE_OUTCOME")
        st, filters = c.student()
        filters += [c.opt("course_id", c.col("a", "course_id")), f"{c.col('a', 'source')} = 'derived'"]
        fields = ["student_id", "course_id", "final_score", "final_result", "is_retake", "is_makeup_pass", "source"]
        base = "SELECT " + ", ".join(c.col("a", f) for f in fields) + f"\nFROM {tab}\nJOIN {st} ON {c.col('s', 'ID', 'student_id')} = {c.col('a', 'student_id')}" + where(filters)
        app.update(grain="学生×课程累计结果（无学期、无GP）", issues=["该表没有semester_id及GP，不能作为所选学期O-22/O-23结果；final_result值域及最终结果选取规则未确认。"], transform=["仅供累计课程结果证据查询；不能把累计结果当学期结果，不能从final_score临时换算GP。"])
        add_set(app, mid, c, base, "student_id, course_id")
        return app
    if mid in {"MV106-FIRST-PASS-RATE", "MV106-MAKEUP-PASS-RATE", "MV106-RETAKE-PASS-RATE", "MV106-PUBLIC-FIRST-PASS-RATE"}:
        tab = c.table("a", "AGG_COURSE_PASS_STAT")
        key = "makeup" if "MAKEUP" in mid else ("retake" if "RETAKE" in mid else "first")
        fields = ["course_id", "semester_id", "course_group", "group_basis", f"{key}_attempts", f"{key}_pass", f"{key}_pass_rate", "rule_version", "calculated_at", "source"]
        filters = [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}", c.opt("course_id", c.col("a", "course_id")), f"{c.col('a', 'source')} = 'derived'", f"{c.col('a', 'rule_version')} = {c.p('rule_version')}"]
        if "PUBLIC" in mid:
            filters += [f"{c.col('a', 'course_group')} = '公共必修'"]
        base = "SELECT " + ", ".join(c.col("a", f) for f in fields) + f"\nFROM {tab}" + where(filters)
        calc = f"WITH input_rows AS (\n{base}\n)\nSELECT COALESCE(SUM({key}_pass), 0) AS numerator, COALESCE(SUM({key}_attempts), 0) AS denominator,\n       100.0 * SUM({key}_pass) / NULLIF(SUM({key}_attempts), 0) AS candidate_metric_value FROM input_rows"
        app.update(grain="课程×学期×规则版本", issues=["表无学院/专业/年级维度，仅能校级查询；不能用学院开课单位代替学生归属。首次/补考/重修分类、存储单位及计算版本待核实。"], transform=["先汇总分子分母再相除；不得对课程百分比直接求平均。"])
        add_set(app, mid, c, base, "course_id, semester_id", calc, app["issues"][0])
        for q in app["queries"]:
            q["scopeMode"] = "school_only"
        return app
    growth = {"MV106-STUDENT-TERM-GPA": "avg_gpa", "MV106-EARNED-CREDITS": "earned_credits", "MV106-PASSED-COURSE-COUNT": "passed_courses"}
    if mid in growth:
        tab = c.table("a", "AGG_STUDENT_TERM_GROWTH")
        st, filters = c.student()
        filters += [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}", f"{c.col('a', 'source')} = 'derived'"]
        fields = ["student_id", "semester_id", growth[mid], "source"]
        base = "SELECT " + ", ".join(c.col("a", f) for f in fields) + f"\nFROM {tab}\nJOIN {st} ON {c.col('s', 'ID', 'student_id')} = {c.col('a', 'student_id')}" + where(filters)
        app.update(grain="学生×学期", issues=["学期聚合不等同累计档案；avg_gpa是否学分加权、已通过课程是否最终有效结果须核实。"], transform=["按同学期读取实际聚合记录，保留学生范围；不以分页均值计算全体GPA。"])
        add_set(app, mid, c, base, "student_id, semester_id")
        return app
    if mid == "MV106-GPA-DISTRIBUTION":
        tab = c.table("a", "AGG_GPA_DIST")
        fields = ["scope", "semester_id", "gpa_bucket", "student_count", "source"]
        filters = [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}", f"{c.col('a', 'scope')} = 'all'", f"{c.col('a', 'source')} = 'derived'"]
        base = "SELECT " + ", ".join(c.col("a", f) for f in fields) + f"\nFROM {tab}" + where(filters)
        app.update(grain="全校×学期×GPA档位", issues=["V6该表没有学院ID；scope='college'不能定位具体学院，因此此查询只取全校scope='all'。GPA加权及档位码须核实。"], transform=["读取全校五档分布；不从缺学院键的记录推断学院结果。"])
        add_set(app, mid, c, base, "scope, semester_id, gpa_bucket")
        for q in app["queries"]:
            q["scopeMode"] = "school_only"
        return app
    if mid == "MV106-TERM-COURSE-COUNT":
        tab = c.table("a", "AGG_COURSE_OFFERING")
        fields = ["course_id", "semester_id", "lesson_count", "teacher_count", "enrolled", "total_hours", "source"]
        filters = [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}", f"{c.col('a', 'source')} = 'derived'"]
        base = "SELECT " + ", ".join(c.col("a", f) for f in fields) + f"\nFROM {tab}" + where(filters)
        app.update(grain="课程×学期", issues=["聚合无学院维度，仅限全校；是否排除停开教学班及开课定义待核实。"], transform=["按course_id去重统计课程，不对lesson_count当课程门数。"])
        add_set(app, mid, c, base, "course_id, semester_id", f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(DISTINCT course_id) AS candidate_metric_value FROM input_rows", app["issues"][0])
        for q in app["queries"]:
            q["scopeMode"] = "school_only"
        return app
    return app


def alert_layers(mid: str) -> list[dict]:
    source = layer("source", issues=[SOURCE_ENGINE], transform=["当前预警来自启用规则与其输入事实，按规则版本另行展开输入；源层不登记虚构预警表。"])
    c = Context()
    at = c.table("a", "ACT_ALERT")
    st, filters = c.student()
    filters += [f"{c.col('a', 'source')} = 'real'", f"{c.col('a', 'batch_id')} = {c.p('alert_batch_id')}"]
    is_history = mid in {"MV106-ALERT-HISTORY-COUNT", "MV106-ALERT-TRAJECTORY"}
    if not is_history:
        filters += [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}"]
    fields = ["alert_id", "student_id", "rule_id", "rule_code", "semester_id", "is_active", "is_resolved", "alert_level", "metric_value", "threshold_value", "source", "batch_id"]
    select = [c.col("a", f) for f in fields]
    join = f"\nFROM {at}\nJOIN {st} ON {c.col('s', 'ID', 'student_id')} = {c.col('a', 'student_id')}"
    if not is_history:
        rt = c.table("r", "SYS_ALERT_RULE")
        join += f"\nLEFT JOIN {rt} ON {c.col('r', 'rule_code')} = {c.col('a', 'rule_code')}"
        select += [c.col("r", "enabled"), c.col("r", "version") + " AS rule_version"]
    base = "SELECT " + ", ".join(select) + join + where(filters)
    blocked = "ACT_ALERT缺可靠计算时间/所用规则版本关联；必须证明所选批次为该学期可靠快照，不能把当前SYS规则覆盖历史版本。is_resolved是处置状态，不作为当前命中筛除条件。2026-09-29测试库实际source全部real（46007条），与V6 engine/字段注释derived冲突；real仅为当前装载标签，不证明预警来自教务源。45100条batch_id为空，本模板只取明确批次，不把未知批次当全部历史。SYS_ALERT_RULE实际版本字段为整数version。"
    calc = None
    if mid == "O-13":
        c.p("rule_version")
        calc = f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(DISTINCT student_id) AS candidate_metric_value FROM input_rows WHERE is_active = 1 AND enabled = 1 AND rule_version = :rule_version"
    elif mid == "MV106-ACTIVE-RULE-COUNT":
        calc = f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(*) AS candidate_active_records, COUNT(DISTINCT rule_id) AS candidate_active_rules FROM input_rows WHERE is_active = 1 AND enabled = 1"
        blocked += "档案当前有效数按记录数，标签写规则数时须按rule_id去重，两者不能混用。"
    elif mid == "MV106-ALERT-HISTORY-COUNT":
        calc = f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(*) AS candidate_metric_value FROM input_rows"
        blocked += "该模板仅含一个明确批次；历史全量是否由该批次覆盖须先确认，不能累加重复快照。"
    elif mid == "O-14":
        c.p("rule_version")
        popfilters = [c.opt("organization_id", c.col("s", "DEPARTMENT_ID", "organization_id")),
                      c.opt("major_id", c.col("s", "MAJOR_ID", "major_id")),
                      c.opt("grade", c.col("s", "GRADE", "entry_grade")),
                      c.opt("student_id", c.col("s", "ID", "student_id")),
                      f"{c.col('s', 'source')} = 'real'", f"{c.col('s', 'batch_id')} = :student_batch_id",
                      f"{c.col('s', 'IN_SCHOOL', 'in_school')} = {c.p('in_school_flag')}",
                      f"{c.col('s', 'HAS_XUE_JI', 'has_xue_ji')} = {c.p('has_xue_ji_flag')}"]
        calc = "WITH population AS (SELECT " + c.col("s", "ID", "student_id") + " AS student_id FROM " + st + where(popfilters) + "),\ninput_rows AS (\n" + base + "\n), active_students AS (SELECT DISTINCT student_id FROM input_rows WHERE is_active = 1 AND enabled = 1 AND rule_version = :rule_version)\nSELECT COUNT(a.student_id) AS numerator, COUNT(*) AS denominator,\n       100.0 * COUNT(a.student_id) / NULLIF(COUNT(*), 0) AS candidate_metric_value\nFROM population p LEFT JOIN active_students a ON a.student_id = p.student_id"
        blocked += ENROLLED + "分子只取同一候选在籍总体内当前命中学生；不对已解除人工流程状态筛除。"
    else:
        blocked += "ACT_ALERT无可靠预警发生时间字段；不能用alert_id或批次字符串臆造历史先后。"
    fact = layer("fact", grain="学生×预警事件", issues=[blocked], transform=["保留is_active和is_resolved两字段，分别核查当前命中与人工处置。", "不同规则命中同一学生，O-13按学生去重；预警记录数量与人数分开。"])
    add_set(fact, mid, c, base, "student_id, alert_id", calc, blocked)
    return [source, fact]


def lesson_layers(mid: str) -> list[dict]:
    layers = []
    for source, lid in [(True, "source"), (False, "fact")]:
        c = Context(source)
        lt = c.table("l", "LESSON", "ACT_TEACHING_LESSON")
        fields = [(c.col("l", "ID", "lesson_id"), "lesson_id"), (c.col("l", "COURSE_ID", "course_id"), "course_id"), (c.col("l", "SEMESTER_ID", "semester_id"), "semester_id"), (c.col("l", "OPEN_DEPARTMENT_ID", "open_department_id"), "open_department_id")]
        filters = [f"{c.col('l', 'SEMESTER_ID', 'semester_id')} = {c.p('semester_id')}", c.opt("organization_id", c.col("l", "OPEN_DEPARTMENT_ID", "open_department_id"))]
        join = f"\nFROM {lt}"
        if not source:
            filters += [f"{c.col('l', 'batch_id')} = {c.p('lesson_batch_id')}", f"{c.col('l', 'source')} = 'real'"]
        order = "lesson_id"
        expr = "COUNT(DISTINCT course_id)"
        if mid == "MV106-TEACHER-COUNT":
            tt = c.table("t", "LESSON_TEACHER_ASSIGNMENT", "ACT_LESSON_TEACHER")
            join += f"\nJOIN {tt} ON {c.col('t', 'LESSON_ID', 'lesson_id')} = {c.col('l', 'ID', 'lesson_id')}"
            fields += [(c.col("t", "TEACHER_ID", "staff_id"), "staff_id"), (c.col("t", "ROLE", "role"), "teacher_role")]
            if not source:
                filters += [f"{c.col('t', 'batch_id')} = {c.p('teacher_batch_id')}", f"{c.col('t', 'source')} = 'real'"]
            expr = "COUNT(DISTINCT staff_id)"
            order += ", staff_id, teacher_role"
        base = "SELECT " + ", ".join(f"{v} AS {n}" for v, n in fields) + join + where(filters)
        blocked = "开课范围与学生归属范围不同，须确认首页该辅助计数采用开课学院还是受教学生范围；停开/取消教学班及教师角色规则待确认。"
        l = layer(lid, grain="教学班×教师指派" if "TEACHER" in mid else "教学班", issues=[blocked], transform=["课程数按course_id去重，教师数按staff_id去重；不能汇总各课程teacher_count得到全校教师数。"])
        add_set(l, mid, c, base, order, f"WITH input_rows AS (\n{base}\n)\nSELECT {expr} AS candidate_metric_value FROM input_rows", blocked)
        layers.append(l)
    return layers


def teacher_layers(mid: str) -> list[dict]:
    layers = []
    for source, lid in [(True, "source"), (False, "fact")]:
        c = Context(source)
        tab = c.table("t", "TEACHER", "ACT_STAFF")
        fields = [(c.col("t", "ID", "staff_id"), "staff_id"), (c.col("t", "DEPARTMENT_ID", "organization_id"), "organization_id"),
                  (c.col("t", "HIRE_TYPE", "hire_type"), "hire_type"), (c.col("t", "TEACHING", "teaching"), "teaching"), (c.col("t", "ZAI_ZHI", "is_on_job"), "is_on_job")]
        filters = [c.opt("organization_id", c.col("t", "DEPARTMENT_ID", "organization_id"))]
        if not source:
            filters += [f"{c.col('t', 'batch_id')} = {c.p('teacher_batch_id')}", f"{c.col('t', 'source')} = 'real'"]
        base = "SELECT " + ", ".join(f"{v} AS {n}" for v, n in fields) + f"\nFROM {tab}" + where(filters)
        reason = "106§3.4说明专任教师数不随统计学期变化，并假设教师表仅装载有效在职专任教师。V6仍有HIRE_TYPE/TEACHING/ZAI_ZHI且未确认专任代码与装载过滤，不能把授课教师去重数或全表教师数当正式专任教师数。"
        l = layer(lid, grain="教师当前主数据", issues=[reason], transform=["按教师主数据及来源批次提供记录数与状态证据；不套用学期授课名单。"])
        add_set(l, mid, c, base, "staff_id")
        layers.append(l)
    return layers


def generic_derived_fact(mid: str, table: str, key: str, fields: list[str], batch: str = "result_batch_id", source_value: str | None = "growth-v1") -> dict:
    c = Context()
    tab = c.table("a", table)
    st, filters = c.student()
    batch_col, batch_param = c.col('a', 'batch_id'), c.p(batch, required=False)
    filters += [f"(({batch_param} IS NULL AND {batch_col} IS NULL) OR {batch_col} = {batch_param})"]
    if source_value:
        filters += [f"{c.col('a', 'source')} = '{source_value}'"]
    select = ", ".join(c.col("a", f) for f in dict.fromkeys([key, "student_id"] + fields + ["source", "batch_id"]))
    base = f"SELECT {select}\nFROM {tab}\nJOIN {st} ON {c.col('s', 'ID', 'student_id')} = {c.col('a', 'student_id')}" + where(filters)
    l = layer("fact", grain="学生×派生证据", issues=["此表是ACT命名的派生结果，其所属事实层与加工来源分别披露；count是证据记录数，不能直接等于指标值。具体规则版本和页面绑定待确认。实测方案汇总/模块表source为growth-v1，非V6声明的derived；result_batch_id空值只选择实际未标记批次的记录，不表示全部批次，不能据此证明与成绩采集同一快照。"], transform=["按学生范围读取实际证据，并展示真实source/batch_id；源层缺口不以派生值自证正确。"])
    add_set(l, mid, c, base, "student_id, " + key)
    return l


def special_layers(mid: str) -> list[dict]:
    source = layer("source", issues=[SOURCE_ENGINE])
    derived = {
        "O-16": ("ACT_STUDENT_PLAN_PROGRESS_SUMMARY", "id", ["plan_id", "total_credits_required", "total_credits_earned", "credit_completion_pct", "total_courses_required", "total_courses_completed"]),
        "MV106-PLAN-MODULE-COMPLETION": ("ACT_STUDENT_PLAN_MODULE_STATUS", "id", ["plan_id", "module_name", "status", "earned_credits", "required_credits", "completion_pct"]),
        "MV106-PLAN-GAP-MODULES": ("ACT_STUDENT_PLAN_MODULE_STATUS", "id", ["plan_id", "module_name", "status", "earned_credits", "required_credits", "completion_pct"]),
        "MV106-PLAN-CANDIDATE-MODULES": ("ACT_STUDENT_PLAN_MODULE_STATUS", "id", ["plan_id", "module_name", "status", "earned_credits", "required_credits", "completion_pct"]),
        "MV106-PLAN-RULE-COVERAGE": ("ACT_STUDENT_PLAN_PROGRESS_SUMMARY", "id", ["plan_id", "total_credits_required", "total_credits_earned", "credit_completion_pct", "total_courses_required", "total_courses_completed"]),
        "MV106-PLAN-CANDIDATE-COURSES": ("ACT_STUDENT_PLAN_COURSE_STATUS", "id", ["course_id", "plan_id", "module_name", "requirement_type", "status", "score", "is_pass", "earned_credits"]),
        "MV106-GROWTH-EVENT-COUNT": ("ACT_STUDENT_TIMELINE_EVENT", "id", ["event_type", "event_date", "title", "semester_id"]),
    }
    if mid in derived:
        args = derived[mid]
        fact = generic_derived_fact(mid, *args, source_value=None if mid == "MV106-GROWTH-EVENT-COUNT" else "growth-v1")
        fact["issues"].append("2026-09-29测试库元数据与V6列名不同；此处保留真实字段名，不把status/score或completion_pct直接等同明确失败、有效成绩或规则证据覆盖率。模块表使用module_name而非module_id，缺稳定模块编码；课程状态表缺is_actionable/is_overdue/rule_version。")
        if mid.startswith("MV106-PLAN-") or mid == "O-16":
            source["issues"] = ["培养方案来自PROGRAM/COURSE_PLAN/PLAN_COURSE/COURSE_MODULE，结合STUDENT.PROGRAM_ID、成绩及认定规则；多表的有效绑定、模块约束和替代认定映射未完整确认，不能只查GRADE作为完整计划证据。"]
            source["tables"] = ["PROGRAM", "COURSE_PLAN", "PLAN_COURSE", "COURSE_MODULE", "STUDENT", "GRADE", "OTHER_ACHIEVEMENT"]
            fact["issues"].append("缺可机器校验模块约束、先修/替代认定、确认课程状态码与正式绑定规则；不可把缺成绩直接判定未通过/不能毕业。")
        return [source, fact]
    if mid == "MV106-FOLLOWUP-COUNT":
        c = Context()
        ft = c.table("f", "ACT_ALERT_FOLLOWUP")
        at = c.table("a", "ACT_ALERT")
        st, filters = c.student()
        filters += [f"{c.col('a', 'batch_id')} = {c.p('alert_batch_id')}", f"{c.col('a', 'source')} = 'real'"]
        fields = ["id", "alert_id", "followup_type", "followup_at"]
        base = "SELECT " + ", ".join(c.col("f", f) for f in fields) + f", {c.col('a', 'student_id')} AS student_id\nFROM {ft}\nJOIN {at} ON {c.col('a', 'alert_id')} = {c.col('f', 'alert_id')}\nJOIN {st} ON {c.col('s', 'ID', 'student_id')} = {c.col('a', 'student_id')}" + where(filters)
        fact = layer("fact", grain="一条跟进记录（按关联预警批次范围）", issues=["2026-09-29实测ACT_ALERT_FOLLOWUP没有source/batch_id，不能伪造人工来源或事件批次过滤；本查询只按关联ACT_ALERT明确批次与学生范围限定，跟进实际发生时间使用followup_at。一次预警多次跟进各算一条。缺批次预警及未关联的跟进不在此查询范围，不能声称覆盖完整历史。"])
        add_set(fact, mid, c, base, "student_id, id", f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(*) AS candidate_metric_value FROM input_rows", fact["issues"][0])
        return [source, fact]
    if mid == "MV106-STATUS-EVENT-COUNT":
        layers = []
        for is_source, lid in [(True, "source"), (False, "fact")]:
            c = Context(is_source)
            et = c.table("e", "STD_ALTERATION", "ACT_STUDENT_STATUS_EVENT")
            st, filters = c.student()
            fields = [(c.col("e", "ID", "event_id"), "event_id"), (c.col("e", "STUDENT_ID", "student_id"), "student_id"), (c.col("e", "STATUS", "status"), "status"), (c.col("e", "EFFECTIVE_DATE_TIME", "effective_date"), "effective_date")]
            if not is_source:
                filters += [f"{c.col('e', 'batch_id')} = {c.p('event_batch_id')}", f"{c.col('e', 'source')} = 'real'"]
            base = "SELECT " + ", ".join(f"{v} AS {n}" for v, n in fields) + f"\nFROM {et}\nJOIN {st} ON {c.col('s', 'ID', 'student_id')} = {c.col('e', 'STUDENT_ID', 'student_id')}" + where(filters)
            l = layer(lid, grain="学籍异动事件", issues=["审核通过、生效时间及撤销状态码须确认；原始事件数不是正式生效异动数。"])
            add_set(l, mid, c, base, "student_id, effective_date, event_id", f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(*) AS candidate_metric_value FROM input_rows", l["issues"][0])
            layers.append(l)
        return layers
    return [source, layer("fact", issues=["需求涉及未签版业务规则及尚未核对的实际字段关联，未提供可执行SQL；须补足具体映射后发布查询版本。"])]


def test_environment_application(mid: str, original: dict) -> dict:
    """Use observed 114 schema without equating differently defined metrics.

    Names/comments were read from information_schema on 2026-09-29. Metadata
    supports an evidence query, not semantic equivalence or KPI acceptance.
    The V6 application templates are replaced, not silently column-aliased.
    """
    college = {"O-01", "O-02", "O-03", "O-05", "O-10", "O-14", "O-17", "O-18"}
    outcome = {"O-06", "O-22", "O-23", "MV106-UNRESOLVED-COURSE-COUNT", "MV106-REPEAT-UNRESOLVED-COUNT"}
    growth = {"MV106-STUDENT-TERM-GPA", "MV106-EARNED-CREDITS", "MV106-PASSED-COURSE-COUNT"}
    if mid not in college | outcome | growth | {"MV106-GPA-DISTRIBUTION", "MV106-TERM-COURSE-COUNT"}:
        return original
    c = Context()
    calc = None
    issues = ["测试库此应用表没有source/batch_id；读取发布标记、version与calculated_at作为原值证据，不能自行认定来源均为derived或与事实层同批次。"]
    if mid in college:
        table = "AGG_COLLEGE_TERM"
        tab = c.table("a", table)
        fields = ["id", "college_id", "semester_id", "student_count", "avg_gpa", "pass_rate", "alert_rate", "is_published", "version", "calculated_at"]
        filters = [c.opt("college_id", c.col("a", "college_id"))]
        if mid == "O-18":
            filters += [f"{c.col('a', 'semester_id')} IN ({c.p('semester_id')}, {c.p('previous_semester_id')})"]
        else:
            filters += [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}"]
        join = f"\nFROM {tab}"
        issues += ["college_id是应用表物理学院键，未证明与Oracle组织ID的业务映射；参数独立标注，不自动代入organization_id。实测14个学院键均可匹配14个唯一组织键，但1个组织未标记学院，且学生表两键同时非空为0，存在性匹配不足以确认同口径。",
                   "student_count注释为在校生总数，不能当有效成绩学生数O-02或未经确认的在籍学生数O-01；avg_gpa是否先按学生学分加权后平均仍需核对。",
                   "实际没有avg_score或fail_rate，不能将pass_rate取补数推导O-10，也不能据此完成O-17/O-18。这里的count/detail是相关学院综合对象原值证据，不是缺失指标的实际结果。"]
        grain = "应用学院键×学期×版本/发布记录"
    elif mid in outcome | growth:
        table = "AGG_STUDENT_COURSE_OUTCOME" if mid in outcome else "AGG_STUDENT_TERM_GROWTH"
        tab = c.table("a", table)
        st, filters = c.student()
        join = f"\nFROM {tab}\nJOIN {st} ON {c.col('s', 'ID', 'student_id')} = {c.col('a', 'student_id')}"
        if mid in outcome:
            fields = ["id", "student_id", "course_id", "semester_id", "score", "gpa", "is_pass", "is_retake", "attempt_count", "is_published", "version", "calculated_at"]
            filters += [c.opt("course_id", c.col("a", "course_id"))]
            if mid in {"O-22", "O-23"}:
                filters[-1] = f"{c.col('a', 'course_id')} = {c.p('course_id', required=True)}"
                filters += [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}"]
            else:
                filters += [f"{c.col('a', 'student_id')} = {c.p('student_id', required=True)}"]
            issues += ["与V6不同，测试库实际有semester_id/score/gpa/is_pass及版本、发布时间。O-22/O-23按所选学期和课程查看原值；累计指标查看学生跨期记录，不把多学期成果行直接当每课程唯一最终结果。",
                       "发布时间、补重修覆盖、每学生课程版本去重与缺GP处理仍未确认；is_pass仅按字段注释显示，不等同已验证的最终有效结果。"]
            grain = "学生×课程×学期×版本/发布记录"
        else:
            fields = ["id", "student_id", "semester_id", "term_gpa", "cumulative_gpa", "term_credits", "cumulative_credits", "pass_count", "fail_count", "is_published", "version", "calculated_at"]
            filters += [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}"]
            issues += ["实际字段为term_gpa/cumulative_gpa/term_credits/cumulative_credits/pass_count，保留原名；term_credits注释仅为学期学分，不能静默等同已获学分，pass_count也未证明为历史去重或当前最终有效通过门数。"]
            grain = "学生×学期×版本/发布记录"
    elif mid == "MV106-GPA-DISTRIBUTION":
        table = "AGG_GPA_DIST"
        tab = c.table("a", table)
        fields = ["id", "semester_id", "college_id", "major_id", "grade", "gpa_min", "gpa_max", "gpa_avg", "gpa_median", "gpa_stddev", "distribution", "is_published", "version", "calculated_at"]
        filters = [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}", c.opt("college_id", c.col("a", "college_id")), c.opt("major_id", c.col("a", "major_id")), c.opt("grade", c.col("a", "grade"))]
        join = f"\nFROM {tab}"
        issues += ["实际按学院/专业/年级保存distribution JSON，无gpa_bucket/student_count/scope列；记录数统计聚合对象，不是档位人数。JSON结构、档位人数总数和学院键映射仍待核对，不能猜测JSON键来计算人数。"]
        grain = "学院键×专业×年级×学期×版本，档位保存在JSON"
    else:
        table = "AGG_COURSE_OFFERING"
        tab = c.table("a", table)
        fields = ["id", "semester_id", "organization_id", "course_id", "course_category", "course_type", "lesson_count", "enrolled_total", "teacher_count", "is_published", "version", "calculated_at"]
        filters = [f"{c.col('a', 'semester_id')} = {c.p('semester_id')}", c.opt("organization_id", c.col("a", "organization_id"))]
        join = f"\nFROM {tab}"
        issues += ["实际有organization_id和enrolled_total，无total_hours；按开课组织查询，不把开课组织范围等同受教学生组织范围。发布/停开与版本取值规则尚待确认。"]
        grain = "开课组织×课程×学期×版本/发布记录"
    base = "SELECT " + ", ".join(c.col("a", field) for field in fields) + join + where(filters)
    if mid == "MV106-TERM-COURSE-COUNT":
        calc = f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(DISTINCT course_id) AS candidate_metric_value FROM input_rows"
    result = layer("application", grain=grain, issues=issues, transform=["按2026-09-29测试库information_schema字段及注释建立只读原值证据；不通过相近列名自动批准指标映射。", "count统计完整输入记录，detail以实际主键id稳定排序；页面指标计算口径仍独立待核对。"])
    add_set(result, mid, c, base, "id", calc, "；".join(issues))
    result["metricResultStatus"] = "blocked"
    result["metricResultBlockedReason"] = "实际对象字段已定位；是否是本指标同口径应用结果尚未确认。"
    for q in result["queries"]:
        q["resultRole"] = "related_table_evidence" if q["kind"] != "calculate" else "candidate_calculation"
        q["scopeMode"] = "school_only" if mid in college or mid == "MV106-GPA-DISTRIBUTION" else "authorized_student_or_organization_evidence"
    return result


def plan_source_layer(mid: str) -> dict:
    c = Context(True)
    st, filters = c.student()
    filters.append(f"{c.col('s', 'ID')} = {c.p('student_id', required=True)}")
    program, plan = c.table('p', 'PROGRAM'), c.table('cp', 'COURSE_PLAN')
    module, pc, course = c.table('cm', 'COURSE_MODULE'), c.table('pc', 'PLAN_COURSE'), c.table('c', 'COURSE')
    mapping = [('s','ID','student_id'),('s','PROGRAM_ID','student_program_id'),('p','ID','program_id'),
               ('p','ENABLED','program_enabled'),('p','AUDIT_STATE','program_audit_state'),('cp','ID','course_plan_id'),
               ('cp','BEGIN_SEMESTER_ID','begin_semester_id'),('cm','ID','module_id'),('cm','PARENT_COURSE_MODULE_ID','parent_module_id'),
               ('cm','REQUIRED_CREDITS','required_credits'),('cm','REQUIRED_COURSE_NUM','required_course_num'),
               ('cm','REQUIRED_SUB_MODULE_NUM','required_sub_module_num'),('pc','ID','plan_course_id'),
               ('pc','COURSE_ID','course_id'),('pc','COMPULSORY','compulsory'),('c','CREDITS','course_credits')]
    fields = [f'{c.col(a, f)} AS {alias}' for a, f, alias in mapping]
    joins = (f"\nFROM {st}\nLEFT JOIN {program} ON {c.col('p', 'ID')} = {c.col('s', 'PROGRAM_ID')}"
             f"\nLEFT JOIN {plan} ON {c.col('cp', 'ID')} = {c.col('p', 'COURSE_PLAN_ID')}"
             f"\nLEFT JOIN {module} ON {c.col('cm', 'COURSE_PLAN_ID')} = {c.col('cp', 'ID')}"
             f"\nLEFT JOIN {pc} ON {c.col('pc', 'COURSE_MODULE_ID')} = {c.col('cm', 'ID')}"
             f"\nLEFT JOIN {course} ON {c.col('c', 'ID')} = {c.col('pc', 'COURSE_ID')}")
    result = layer('source', grain='指定学生×当前绑定方案×模块×方案课程（含未匹配行）',
                   issues=['已定位方案约束输入；ENABLED/AUDIT_STATE值域、历史有效绑定、模块继承、替代课程和OTHER_ACHIEVEMENT认定仍需核对，约束清单不等于完成度结果。'],
                   transform=['STUDENT.PROGRAM_ID→PROGRAM.ID→PROGRAM.COURSE_PLAN_ID→COURSE_PLAN.ID→COURSE_MODULE.COURSE_PLAN_ID→PLAN_COURSE.COURSE_MODULE_ID。', 'LEFT JOIN保留缺方案/模块/课程的原始行；不把缺约束判作未通过。成绩和认定须另按学生关联，避免与约束行交叉相乘。'])
    add_set(result, mid, c, 'SELECT ' + ', '.join(fields) + joins + where(filters), 'student_id, course_plan_id, module_id, plan_course_id')
    return result


def approve_calculation(q: dict, basis: str, role: str = 'requirement_recalculation'):
    q.update(executionApproval='documented', approvalBasis=basis, resultRole=role)
    q.pop('blockedReason', None)
    q['note'] = basis + '。查询成功仍须人工对照应用结果，不自动形成验收通过。'


def all_attempt_evidence(mid: str, items: list[dict]) -> list[dict]:
    """106 10.10 evidence: preserve attempts, including non-calculable rows."""
    for item in items:
        if item['id'] not in {'source', 'fact'}:
            continue
        source = item['id'] == 'source'
        c, base = grade_rows(source, term='all', student_required=True)
        base = re.sub(r'\(:course_id IS NULL OR g\.[A-Za-z_]+ = :course_id\)', '1 = 1', base)
        course = c.table('dc', 'COURSE', 'ACT_COURSE')
        cid, code, name = c.col('dc','ID','course_id'), c.col('dc','CODE','code'), c.col('dc','NAME_ZH','name_zh')
        course_filters = [] if source else [f"{c.col('dc','batch_id')} = {c.p('course_batch_id')}", f"{c.col('dc','source')} = 'real'"]
        course_lookup = f"SELECT {cid} AS course_key, CASE WHEN COUNT(DISTINCT {code}) = 1 THEN MIN({code}) END AS course_code, CASE WHEN COUNT(DISTINCT {name}) = 1 THEN MIN({name}) END AS course_name, COUNT(*) AS course_metadata_rows FROM {course}" + (where(course_filters) if course_filters else '') + f' GROUP BY {cid}'
        semester = c.table('tm','SEMESTER','ACT_SEMESTER')
        tid, label, start = c.col('tm','ID','semester_id'), c.col('tm','NAME_ZH','name_zh'), c.col('tm','START_DATE','start_date')
        semester_lookup = f"SELECT {tid} AS semester_key, CASE WHEN COUNT(DISTINCT {label}) = 1 THEN MIN({label}) END AS semester_name, CASE WHEN COUNT(DISTINCT {start}) = 1 THEN MIN({start}) END AS semester_start_date, COUNT(*) AS semester_metadata_rows FROM {semester}" + ('' if source else where([f"{c.col('tm','source')} = 'real'"])) + f' GROUP BY {tid}'
        projection = 'cm.course_code, cm.course_name, cm.course_metadata_rows, sm.semester_name, sm.semester_start_date, sm.semester_metadata_rows'
        joins = f"\nLEFT JOIN ({course_lookup}) cm ON cm.course_key = {c.col('g','COURSE_ID','course_id')}\nLEFT JOIN ({semester_lookup}) sm ON sm.semester_key = {c.col('g','SEMESTER_ID','semester_id')}"
        if source:
            makeup = c.table('mg','MAKEUP_GRADE')
            grade_id = c.col('mg','GRADE_ID')
            projection += f", {c.col('g','STATE')} AS source_state, mc.makeup_component_count"
            joins += f"\nLEFT JOIN (SELECT {grade_id} AS grade_key, COUNT(*) AS makeup_component_count FROM {makeup} GROUP BY {grade_id}) mc ON mc.grade_key = {c.col('g','ID')}"
        base = base.replace('\nFROM ', ',\n       ' + projection + '\nFROM ', 1).replace('\nWHERE ', joins + '\nWHERE ', 1)
        note = '106§10.10全部个人成绩尝试：不按课程去重，不筛失败、发布、作废、通过判定或GP；仅限定个人授权范围及真实来源批次。count为全历史原始尝试数，不是指标纳入样本数。课程/学期元数据分组连接避免放大；冲突标签返回空值。'
        order = 'CASE WHEN semester_start_date IS NULL THEN 1 ELSE 0 END, semester_start_date DESC, CASE WHEN score IS NULL THEN 1 ELSE 0 END, score ASC, semester_id DESC, attempt_id' + (', fact_row_id' if not source else '')
        evidence = layer(item['id'])
        add_set(evidence, mid, c, base, order, note=note)
        for q in evidence['queries']:
            q.update(title='全部个人成绩尝试' + ('记录数' if q['kind']=='count' else '明细'),
                     description=note, scenarioPurpose='106§10.10共用追查证据，不等于当前指标最终结果集合',
                     evidenceCollectionId='all_personal_grade_attempts', resultRole='source_evidence',
                     grain='学生×全部历史成绩尝试（保留原状态）')
        item['queries'] = evidence['queries'] + [q for q in item['queries'] if q['kind'] not in {'count','detail'}]
        item['tables'] = sorted(set(item['tables']) | set(evidence['tables']))
        item['issues'].append('全部尝试明细与本指标calculate的纳入集合分开。按学期开始日期降序、成绩升序；缺失/冲突学期日期时仅做稳定兜底，不代表业务顺序已核验。源考试类别仅展示GRADE_STATUS/STATE及补考分项数量，不把分项存在直接解码为补考；事实exam_status/attempt_type原码仍需字典。')
    return items


def audit_new_layers(mid: str) -> list[dict]:
    """New requirement definitions get explicit inputs, never a renamed value."""
    key = mid.removeprefix('MV106-')
    if key == 'FILTERED-STUDENT-COUNT':
        items = student_layers(mid)
        for item in items:
            item['queries'] = [q for q in item['queries'] if q['kind'] != 'calculate']
            item['issues'] = ['当前只读学生快照按学院/专业/年级/个人限定；画像所需学期/学年、课程、重修、必修、班级、关键词组合选人尚未完整登记，快照行数不等于画像筛选总数。']
            item['transform'] = ['提供学生总体原始证据；不把有效成绩人数O-02或分页行数改名为完整筛选人数。']
        return items
    alert_keys = {'EVIDENCE-RULE-COUNT','CURRENT-ALERT-RECORD-COUNT','HIGHEST-ALERT-LEVEL','ALERT-CHANGE'}
    if key in alert_keys:
        c = Context()
        table = c.table('a','ACT_ALERT')
        st, filters = c.student()
        filters += [f"{c.col('a','source')} = 'real'", f"{c.col('a','student_id')} = {c.p('student_id', required=True)}"]
        columns = ['id','alert_id','student_id','rule_id','rule_code','semester_id','alert_level','is_active','is_resolved','workflow_status','created_at','updated_at','batch_id','metric_value','threshold_value','alert_detail']
        base = 'SELECT ' + ', '.join(c.col('a', col) for col in columns) + f"\nFROM {table}\nJOIN {st} ON {c.col('s','ID','student_id')} = {c.col('a','student_id')}" + where(filters)
        reason = {'EVIDENCE-RULE-COUNT':'§9.2触发观察期、截止时点及同规则多命中去重范围待明确；不能以全历史规则数代替。',
                  'CURRENT-ALERT-RECORD-COUNT':'仅汇总现库is_active标记记录；数据更新时点与规则生成正确性另行核对，不把工作流已解决当风险解除。',
                  'HIGHEST-ALERT-LEVEL':'当前最高等级需确认alert_level真实字典；字段注释info/warning/critical不是本次枚举验证，未知值不能默认正常。',
                  'ALERT-CHANGE':'created_at/updated_at只提供原值；未证明created_at为预警发生时间，时间并列及规则标识映射也未明确，不能按写库时间认定上一条预警。'}[key]
        calc = None
        if key == 'CURRENT-ALERT-RECORD-COUNT':
            calc = f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(CASE WHEN is_active = 1 THEN 1 END) AS candidate_metric_value FROM input_rows"
        elif key == 'EVIDENCE-RULE-COUNT':
            calc = f"WITH input_rows AS (\n{base}\n)\nSELECT COUNT(DISTINCT rule_code) AS candidate_all_history_rules FROM input_rows"
        fact = layer('fact', grain='指定学生×已登记预警记录', issues=[reason], transform=['保留全部已登记真实来源预警，包括未标记批次；展示原始风险标志、工作流、规则代码和时间字段。', 'count为输入预警记录数，不是人数、规则数或变化类型；不把当前SYS规则覆盖历史触发证据。'])
        add_set(fact,mid,c,base,'student_id, id',calc,reason)
        if key == 'CURRENT-ALERT-RECORD-COUNT':
            for q in fact['queries']:
                if q['kind']=='calculate':
                    approve_calculation(q,'106§10.4明确当前有效=is_active为1的预警记录数；仅核对当前存储标记计数','stored_result_summary')
        return [layer('source',issues=[SOURCE_ENGINE]),fact]
    # Individual evidence/calculations have an explicitly scoped student.
    personal = mid in PERSONAL_EVIDENCE_IDS or key == 'MANAGEMENT-ATTENTION'
    history = key in {'CURRENT-PASSED-COURSE-COUNT','CURRENT-FAILED-COURSE-COUNT','CURRENT-EARNED-CREDITS','HISTORICAL-FAILED-COURSES','DIFFICULTY-EVIDENCE','R2-UNRESOLVED-COURSES'}
    needs_credits = key in {'STUDENT-PERIOD-GPA','TERM-EARNED-CREDITS','CURRENT-EARNED-CREDITS','MANAGEMENT-ATTENTION'}
    course_required = key in {'COURSE-TOP10-MEAN-SCORE','COURSE-TOP6-MEAN-SCORE','COURSE-EXCELLENT-COUNT','STUDENT-COURSE-RESULT'}
    if key == 'COLLEGE-EXCESS-IMPACT':
        items = build_grade_layers('O-17')
        for item in items:
            for q in item['queries']:
                q['id'], q['sqlFile'] = q['id'].replace('O-17-',mid+'-',1), q['sqlFile'].replace('O-17-',mid+'-',1)
                if item['id']=='fact' and q['kind']=='calculate':
                    approve_calculation(q,'用户确认学院TOP1估算影响=max(学院O10−全校O10,0)×学院有效成绩学生数，按原值排序')
                    q['scopeMode']='school_only'
            item['issues'].append('主结果为estimated_excess_students（人），deviation_pp为组成值；不能把两者单位混用。')
        return items
    items = []
    for source,lid in [(True,'source'),(False,'fact')]:
        c,base = grade_rows(source,term='all' if history else 'current',credits=needs_credits,course_required=course_required,student_required=personal)
        v,calc,reason = valid_cte(base),None,''
        if key == 'COURSE-TOP10-MEAN-SCORE':
            calc = v + 'SELECT SUM(score) AS score_sum, COUNT(DISTINCT student_id) AS valid_students, SUM(score) / NULLIF(COUNT(DISTINCT student_id),0) AS candidate_metric_value FROM valid_rows'
            reason = '106§3.11按有效成绩和÷有效成绩学生数；与课程详情记录均分不同，保留异常分数原值，不自动修正为另一公式。'
        elif key == 'COURSE-TOP6-MEAN-SCORE':
            reason = '106§5.7未明确TOP6均分分母，不能直接套TOP10人数分母或课程详情记录分母；该课程成绩仅作输入证据。TOP6候选人次≥0，但零成绩候选总体未绑定。'
        elif key == 'COURSE-EXCELLENT-COUNT':
            calc = v + 'SELECT COUNT(CASE WHEN score >= 90 THEN 1 END) AS candidate_metric_value, COUNT(CASE WHEN score > 100 THEN 1 END) AS above_percentage_range FROM valid_rows'
            reason = '106§7.3明确≥90人次；与§7.4百分制优秀档90—100及当前异常分数处理需统一，当前候选保留两项证据，不默改阈值或默认超范围有效。'
        elif key == 'STUDENT-PERIOD-GPA':
            calc = student_gpa_cte(base) + 'SELECT student_id, term_gpa AS candidate_metric_value, included_credits FROM student_gpa ORDER BY student_id'
            reason = '当前候选仅覆盖单学期个人加权GPA；学年合并、课程条件仅选人还是限制GPA输入、修读筛选范围尚待明确。'
        elif key == 'STUDENT-COURSE-RESULT':
            calc = latest_cte(base) + 'SELECT student_id, course_id, score AS candidate_course_score, gpa AS candidate_course_gp, attempt_id FROM latest_rows ORDER BY student_id, course_id'
            reason = '§8.3.3个人课程成绩与GP不作群体AVG；同一选中结果读取两个值，但结果选择、观察期与缺GP处理须明确。' + LATEST
        elif key == 'TERM-FAILED-COURSE-COUNT':
            calc = v + 'SELECT COUNT(DISTINCT CASE WHEN is_pass = 0 THEN course_id END) AS candidate_ever_failed_courses_in_term FROM valid_rows'
            reason = '§9.4学期未通过课程门数未明确同学期失败后通过如何处理；候选按本期曾失败课程去重，不能认定为最终失败门数。'
        elif key == 'TERM-EARNED-CREDITS':
            calc = v + 'SELECT SUM(CASE WHEN is_pass = 1 AND credits > 0 THEN credits ELSE 0 END) AS candidate_passed_attempt_credits FROM valid_rows'
            reason = '§9.4当期获学分的课程去重、首次获得/最新通过及学分落期未明确；候选仅列通过尝试学分，不能直接当已获学分。'
        elif key in {'CURRENT-PASSED-COURSE-COUNT','CURRENT-FAILED-COURSE-COUNT','CURRENT-EARNED-CREDITS'}:
            expr = 'SUM(CASE WHEN is_pass = 1 AND credits > 0 THEN credits ELSE 0 END)' if key=='CURRENT-EARNED-CREDITS' else 'COUNT(CASE WHEN is_pass = ' + ('0' if key=='CURRENT-FAILED-COURSE-COUNT' else '1') + ' THEN 1 END)'
            calc = latest_cte(base) + f'SELECT {expr} AS candidate_metric_value FROM latest_rows'
            reason = '106§10.7按当前有效结果计数/学分，不按历史曾通过保留；' + LATEST
        elif key == 'HISTORICAL-FAILED-COURSES':
            calc = v + 'SELECT student_id, course_id, COUNT(*) AS historical_failed_attempts FROM valid_rows WHERE is_pass = 0 GROUP BY student_id, course_id ORDER BY student_id, course_id'
            reason = '§9.5/10.9历史失败集合保留后来已通过课程；当前状态仍须关联已确认最新结果选择规则，源有效性映射须独立核对。'
        elif key == 'R2-UNRESOLVED-COURSES':
            c.p('semester_id'); c.p('previous_semester_id')
            calc = v.rstrip() + ", historical_passed AS (SELECT DISTINCT student_id, course_id FROM valid_rows WHERE is_pass = 1), window_failed AS (SELECT DISTINCT student_id, course_id FROM valid_rows WHERE is_pass = 0 AND semester_id IN (:semester_id,:previous_semester_id)), never_passed AS (SELECT f.* FROM window_failed f LEFT JOIN historical_passed p ON p.student_id=f.student_id AND p.course_id=f.course_id WHERE p.student_id IS NULL)\nSELECT COUNT(*) AS candidate_metric_value, CASE WHEN COUNT(*) >= 3 THEN 1 ELSE 0 END AS candidate_r2_hit, CASE WHEN COUNT(*) = 2 THEN 1 ELSE 0 END AS candidate_r2w_hit FROM never_passed"
            reason = '§10.5 R2/R2W排除历史曾通过课程，与§9.3最新失败不同。当前候选以所选批次全量历史作通过排除，业务截至时间、两个观察学期选择及认定通过范围未明确，不得作正式规则核验。'
        elif key == 'MANAGEMENT-ATTENTION':
            reason = '这里只提供个人筛选期成绩；还需当前最高有效预警、完整筛选规则及缺GPA分支定义。不能仅凭成绩生成AI重点/需核查/常规查看。'
        elif key == 'DIFFICULTY-EVIDENCE':
            reason = '三组困难输入分别为当前失败课程、重复失败尝试、方案明确失败必修课程；此处仅有成绩原始证据，需引用各依赖集合，不能套一个未解决课程数替代三类标签数字。'
        item = layer(lid,grain='学生×课程×成绩尝试输入',issues=[reason] + ([VALIDITY] if source else [FACT_GRADE_EVIDENCE]),transform=['按本场景读取真实成绩输入，指标/集合公式与输入记录数分别核对。'])
        add_set(item,mid,c,base,'student_id, course_id, semester_id, attempt_id' + ('' if source else ', fact_row_id'),calc,(VALIDITY if source else '') + reason)
        if not source and key=='COURSE-TOP10-MEAN-SCORE':
            for q in item['queries']:
                if q['kind']=='calculate': approve_calculation(q,'106§3.11明确成绩和÷有效成绩去重学生数；使用既有事实有效字段复算此场景')
        for q in item['queries']:
            q.update(title={'count':'输入记录数','detail':'输入明细','calculate':'场景计算'}[q['kind']],description=reason,scenarioPurpose='106场景：'+key)
            if key=='R2-UNRESOLVED-COURSES': q['evidenceCollectionId']='rule_r2_never_passed'
        items.append(item)
    return items


def complete_layers(mid: str, layers: list[dict]) -> list[dict]:
    source, fact, app = layers
    if mid == 'O-16' or mid.startswith('MV106-PLAN-'):
        source = plan_source_layer(mid)
    if mid == 'O-01':
        boundary = '只读实测源ZAI_JI=1为9990人，有学籍且在校9991人，两者不能替代。仅源端当前快照标记可直接计数，历史有效学籍快照未绑定。'
        source['issues'].append(boundary)
        fact['issues'].append(boundary + 'ACT_STUDENT缺ZAI_JI，不能开放代理公式。')
        for q in source['queries']:
            if q['kind'] == 'calculate':
                q['sql'] = q['sql'].replace('WHERE has_xue_ji = :has_xue_ji_flag AND in_school = :in_school_flag', 'WHERE zai_ji = 1')
                q['parameters'] = [p for p in q['parameters'] if p['name'] not in {'has_xue_ji_flag', 'in_school_flag'}]
                approve_calculation(q, '源STUDENT.ZAI_JI当前快照在籍标记人数；不代表历史有效学籍审核', 'source_flag_summary')
    if mid == 'O-19':
        fact['issues'].append('源在籍标记9990人与有学籍且在校9991人不等；代理在籍分母已被反证，历史源快照也未绑定。')
    if mid == 'MV106-TEACHER-COUNT':
        fact['issues'].append('实库含兼职290人、非在职137人（有交集），FORMAL且在职1555人；FORMAL与学校专任缺字典证明，不能全表计专任教师。')
    if 'ACT_ALERT' in fact['tables']:
        fact['issues'].append('实测rule_id关联失配46007/46007；rule_code匹配46007/46007且10个代码唯一，查询显式采用rule_code桥接当前规则，当前version不代表历史触发版本。')
    simple = {'O-02','O-05','O-08','O-09','O-10','O-11','O-17','O-20',
              'MV106-VALID-ATTEMPT-COUNT','MV106-GRADE-COURSE-COUNT','MV106-COURSE-MEAN-SCORE',
              'MV106-COURSE-EXCELLENT-RATE','MV106-SCORE-DISTRIBUTION','MV106-STUDENT-TERM-GPA',
              'MV106-CREDIT-PASS-RATIO','MV106-GPA-DISTRIBUTION','MV106-GPA-ARITHMETIC','MV106-REPEAT-FAILURE-ATTEMPTS'}
    if mid in simple:
        fact['issues'] = [i for i in fact['issues'] if i != VALIDITY]
        fact['transform'][2:3] = ['真实来源、指定批次、已发布、未作废且明确0/1结果选有效记录；学分权重用成绩credits，GP用成绩已有值。GPA算术平均按106仅要求已发布、未作废且有GP。']
        for q in fact['queries']:
            if q['kind'] == 'calculate':
                fact['issues'] = [i for i in fact['issues'] if i != q.get('blockedReason')]
                approve_calculation(q, '106对应章节及§12公式；实库is_void/is_pass/is_published/credits字段和枚举覆盖已有汇总证据')
                if mid == 'O-17':
                    q['approvalBasis'] += '；用户确认估算人数=max(学院O10−全校O10,0)×学院O02，百分数差除100、原值排序；仅覆盖O10场景'
                    q['scopeMode'] = 'school_only'
        fact['issues'].append('复算使用已落地事实字段，不证明源作废/特殊成绩映射或GP转换正确；应用绑定独立待核对。4条超范围分数作为质量问题；优秀率/分布限百分制[0,100]。')
    if mid == 'MV106-STATUS-EVENT-COUNT':
        for item in [source, fact]:
            for q in item['queries']:
                if q['kind'] == 'calculate':
                    approve_calculation(q, '106§10.8按已接入学籍异动事件计数；事件数量不等于审核通过且已生效异动数量')
    states = {'MV106-PLAN-GAP-MODULES': "COUNT(CASE WHEN status = 'explicit_gap' THEN 1 END)",
              'MV106-PLAN-CANDIDATE-MODULES': "COUNT(CASE WHEN status = 'candidate' THEN 1 END)",
              'MV106-GROWTH-EVENT-COUNT': 'COUNT(*)'}
    if mid in states:
        q = deepcopy(next(q for q in fact['queries'] if q['kind'] == 'count'))
        q.update(id=q['id'].replace('-count-', '-calculate-'), sqlFile=q['sqlFile'].replace('-count-', '-calculate-'), kind='calculate')
        q['sql'] = q['sql'].replace('COUNT(*) AS matched_records', states[mid] + ' AS candidate_metric_value')
        approve_calculation(q, '106结果状态/事件记录数量；实测explicit_gap/candidate枚举，只汇总已有结果，不独立验真其生成规则', 'stored_result_summary')
        fact['queries'].append(q)
    if mid == 'MV106-GROWTH-EVENT-COUNT':
        fact['issues'] = ['该时间线为已存储的成长事件组合，真实source含real/derived，batch_id均为空；空result_batch_id只选择未标记批次，不能证明同一成绩快照。']
        fact['issues'].append('时间线实际仅有status_change、semester_result、graduation；预警/跟进/课程失败类未在该表发现，不能当完整成长事件覆盖。')
    for item in [source, fact, app]:
        item.update(applicability='applicable', mappingMode='physical_table' if item['queries'] else 'missing_evidence',
                    directSource={'layer':item['id'],'tables':item['tables'],'reason':'已定位只读证据对象，字段与口径校验分开记录'},
                    remainingGaps=list(item['issues']), closureReason='可查询输入或原值；不据记录数一致认定通过。' if item['queries'] else '未定位独立结果或完整计算输入。')
    app.setdefault('metricResultStatus', 'blocked')
    app.setdefault('metricResultBlockedReason', '可读取存储对象原值；当前页面实际接口绑定、单位与同口径刷新版本未独立证明。')
    if not source['queries']:
        source.update(applicability='not_applicable', mappingMode='no_independent_source',
                      directSource={'layer':'fact','tables':fact['tables'],'reason':'平台预警、人工跟进或组合成长事件没有同名Oracle结果表；沿事实事件及SYS规则查看直接输入'},
                      closureReason='不存在独立贴源结果；需要展开事件引用的成绩、学籍等原始输入。',
                      remainingGaps=['触发规则版本、输入快照或人工事件来源须继续追溯。'])
    if not app['queries']:
        app.update(mappingMode='reference_from_fact', tables=list(fact['tables']), grain=fact['grain'], queries=deepcopy(fact['queries']),
                   directSource={'layer':'fact','tables':fact['tables'],'reason':'未定位独立AGG/SYS业务结果；此入口为事实需求参考查询，实际应用接口绑定未证明'},
                   metricResultStatus='blocked', metricResultBlockedReason='实际应用字段/接口绑定未证明；事实参考不使应用映射闭合。',
                   remainingGaps=['实际应用字段/接口绑定未证明；事实参考不使应用映射闭合。'], closureReason='已提供事实参考入口，应用实际结果待核对。')
        for q in app['queries']:
            q['id'], q['sqlFile'] = q['id'].replace('-fact-', '-application-'), q['sqlFile'].replace('-fact-', '-application-')
            q['resultRole'], q['note'] = 'reference_from_fact', '事实层参考查询，不能作为应用实际存储值或接口证据。' + q.get('note','')
        app['status'] = 'documented' if app['queries'] else 'blocked'
    for item in [source, fact, app]:
        direct = item['directSource']
        item['directSource'] = {'source':'贴源层','fact':'事实层','application':'应用层'}[direct['layer']] + '：' + '、'.join(direct['tables']) + '；' + direct['reason']
        item['dataQuality'] = {'evidenceFile':'work/runtime/highedu-start/metric-verification-enumeration-evidence.json','checkedAt':'2026-09-29','meaning':'固定只读汇总证据；技术执行和业务验收独立'}
    return [source, fact, app]


def build() -> dict:
    result = []
    alert_metrics = {"O-13", "O-14", "MV106-ACTIVE-RULE-COUNT", "MV106-ALERT-HISTORY-COUNT", "MV106-ALERT-TRAJECTORY"}
    special = {"O-16", "MV106-PLAN-MODULE-COMPLETION", "MV106-PLAN-RULE-COVERAGE", "MV106-PLAN-GAP-MODULES", "MV106-PLAN-CANDIDATE-MODULES", "MV106-PLAN-CANDIDATE-COURSES", "MV106-GROWTH-EVENT-COUNT", "MV106-FOLLOWUP-COUNT", "MV106-STATUS-EVENT-COUNT"}
    for mid in CORE + ["MV106-" + key for key in EXTRA + AUDIT_EXTRA]:
        if mid in AUDIT_IDS:
            layers = audit_new_layers(mid)
        elif mid == "O-01":
            layers = student_layers(mid)
        elif mid == "O-19":
            layers = coverage_layers()
        elif mid in alert_metrics:
            layers = alert_layers(mid)
        elif mid == "MV106-TERM-COURSE-COUNT":
            layers = lesson_layers(mid)
        elif mid == "MV106-TEACHER-COUNT":
            layers = teacher_layers(mid)
        elif mid in special:
            layers = special_layers(mid)
        else:
            layers = build_grade_layers(mid)
        layers.append(test_environment_application(mid, application(mid)))
        if mid in PERSONAL_EVIDENCE_IDS:
            layers = all_attempt_evidence(mid, layers)
        layers = complete_layers(mid, layers)
        for item in layers:
            physical_update = (item["id"] == "application" and (item.get("metricResultStatus") == "blocked" or item.get("schemaEvidence"))) or (item["id"] == "fact" and (mid in alert_metrics | special or "ACT_GRADE_ATTEMPT" in item["tables"]))
            if physical_update:
                item["schemaEvidence"] = {"checkedAt": "2026-09-29", "basis": "测试库information_schema字段/注释和只读汇总；不代表业务口径通过"}
                for q in item["queries"]:
                    q["version"] = "1.0.1"
                    q["schemaEvidence"] = item["schemaEvidence"]
            for q in item['queries']:
                q['version'] = '2.0.0' if mid in AUDIT_CHANGED_IDS else '1.1.0'
            if not item["queries"]:
                item["blockedReason"] = "；".join(item["issues"])
            item["calculationStatus"] = "blocked" if not any(q["kind"] == "calculate" and q["executionApproval"] != "blocked" for q in item["queries"]) else "documented"
            if not any(q["kind"] == "calculate" for q in item["queries"]):
                item["calculationBlockedReason"] = "；".join(item["issues"])
        result.append(dict(metricId=mid, layers=layers))
    return dict(schemaVersion=2, moduleId="teaching-overview", version="2.0.0",
                basis=["106-教学数据总览功能指标详细需求说明.md §3–12", "本科教学分析与学业决策支持平台需求调研及指标口径确认书V2.md O系列", "Oracle源表字段完整清单V6.0(2).md", "中国矿业大学学业分析平台数据库设计文档V6.0(3).md"],
                validationStatus="documented_with_test_schema_evidence_not_metric_verified",
                executionRules=["只允许已登记单条SELECT/CTE，禁用任意SQL和客户端指定连接。", "执行前检验schema、参数、范围和executionApproval；documented不代表验收通过。", "source-mysql为同名字段镜像，仅在元数据一致后运行；oracle为原库参考。", "count统计完整输入，detail稳定排序最多100条，不比较不同粒度记录数是否相等。", "calculate逐条审批：documented有approvalBasis，blocked禁止运行。事实参考不代表应用实际值，不认定三层闭合。", "源快照、事实批次、应用刷新均需环境证据；不假定不同表批次ID相同。"],
                metrics=result)


def main():
    manifest = build()
    SQL_ROOT.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    for metric in manifest["metrics"]:
        for item in metric["layers"]:
            for q in item["queries"]:
                (ROOT / q["sqlFile"]).write_text(q["sql"], encoding="utf-8")
                count += 1
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": len(manifest["metrics"]), "queries": count, "databaseConnections": 0, "output": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
