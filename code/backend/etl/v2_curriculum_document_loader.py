"""Parse extracted curriculum documents and load their real plan content into V2."""
from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
from pathlib import Path

from . import config
from .init_v2 import init_v2


SECTION_RE = re.compile(r"(?m)^\s*[一二三四五六七八九十]+\s*[、.]\s*")
ITEM_RE = re.compile(r"(?m)(?<!\d)(1[0-9]|[1-9])\s*[\.、．]\s*")
COURSE_CODE_RE = re.compile(r"^[0-9A-Z]{6,}[A-Z0-9]*$")
TABLE_HEADERS = {"课程模块", "课程代码", "课程名称", "课程性质", "学分", "总学时",
                 "理论学时", "实验学时", "实践学时", "上机学时", "开课学期", "开课部门"}


def clean(value: str) -> str:
    value = value.replace("\x07", " ").replace("\r", "\n")
    value = re.sub(r"[ \t\u3000]+", " ", value)
    return re.sub(r"\n{2,}", "\n", value).strip()


def section(text: str, headings: tuple[str, ...]) -> str:
    text = clean(text)
    for heading in headings:
        pattern = re.compile(r"\s*".join(map(re.escape, re.sub(r"\s", "", heading))))
        match = pattern.search(text)
        if match:
            tail = text[match.end():]
            end = SECTION_RE.search(tail)
            return clean(tail[:end.start()] if end else tail)
    return ""


def numbered_items(value: str) -> list[str]:
    matches = list(ITEM_RE.finditer(value))
    if not matches:
        return [clean(x) for x in value.splitlines() if clean(x)]
    result = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        if item := clean(value[match.end():end]):
            result.append(item)
    return result


def table_module_requirements(item: dict) -> list[dict]:
    rules = []
    for table in item.get("tables") or []:
        encoded = table.get("text_utf16le_base64")
        if not encoded:
            continue
        text = base64.b64decode(encoded).decode("utf-16le")
        cursor = 0
        current_parent = None
        for match in re.finditer(r"要求学分\s*[：:]\s*(\d+(?:\.\d+)?)", text):
            segment = text[cursor:match.start()]
            cursor = match.end()
            tokens = [clean(x) for x in re.split(r"[\r\x07]+", segment) if clean(x)]
            first_course = next((i for i, token in enumerate(tokens) if COURSE_CODE_RE.fullmatch(token)), len(tokens))
            labels = [x for x in tokens[:first_course] if x not in TABLE_HEADERS and x not in {"必修", "选修"}]
            labels = [x for x in labels if not re.fullmatch(r"\d+(?:\.\d+)?", x)]
            if not labels:
                continue
            labels = labels[-3:]
            typed = next((x for x in labels if "必修" in x or "选修" in x), "")
            if typed:
                current_parent = typed
            module_name = labels[-1]
            if module_name == current_parent and len(labels) > 1:
                module_name = labels[-2]
            nature = "必修" if any("必修" in x for x in labels) else ("选修" if any("选修" in x for x in labels) else None)
            rules.append({"parent_module": current_parent, "module_name": module_name,
                          "requirement_type": nature, "minimum_credits": float(match.group(1)),
                          "raw_hierarchy": " / ".join(labels), "source_table": table.get("index")})
    return rules


def parse_document(item: dict) -> dict:
    encoded = item.get("text_utf16le_base64")
    text = base64.b64decode(encoded).decode("utf-16le") if encoded else (item.get("text") or "")
    stem = Path(item.get("file_name") or "").stem
    hint = re.sub(r"^(?:20\d{2}级)?", "", stem)
    hint = hint.replace("专业培养方案", "").replace("培养方案", "").strip()
    requirement_text = section(text, ("二、修读要求", "修读要求"))
    rule_text = clean(requirement_text or text)
    def credit_value(label: str):
        flexible_label = r"\s*".join(map(re.escape, label))
        match = re.search(flexible_label + r"(?:\s*学\s*分)?\s*[：:]?\s*(\d+(?:\.\d+)?)", rule_text)
        return float(match.group(1)) if match else None
    total_match = re.search(r"(?:最低|总)学分\s*[：:]?\s*(\d+(?:\.\d+)?)", rule_text)
    degree_match = re.search(r"(?:授予)?学士学位要求\s*[：:]?\s*([^\n]+)", rule_text)
    table_rows: list[str] = []
    for table in item.get("tables") or []:
        rows: dict[int, list[tuple[int, str]]] = {}
        for cell in table.get("cells") or []:
            value = base64.b64decode(cell["text_utf16le_base64"]).decode("utf-16le")
            rows.setdefault(int(cell["row"]), []).append((int(cell["column"]), clean(value)))
        table_rows.extend(" | ".join(value for _, value in sorted(cells)) for cells in rows.values())
    table_rule_text = "\n".join(table_rows)
    def table_credit(label: str):
        flexible = r"\s*".join(map(re.escape, label))
        match = re.search(flexible + r"(?:\s*学\s*分)?[^\d\n]{0,20}(\d+(?:\.\d+)?)", table_rule_text)
        return float(match.group(1)) if match else None
    practice_credits = table_credit("集中设置的实践教学环节") or credit_value("集中设置的实践教学环节")
    if practice_credits is None:
        # 旧版 .doc 表格可能丢失该列标签的连续编码；此时只在“选修课”
        # 与“总学分”之间存在唯一数字时按原表列序取值，不用总分倒推。
        positional = re.search(r"选\s*修\s*课\s*\d+(?:\.\d+)?\s+[^\d\n]{1,40}?(\d+(?:\.\d+)?)\s+(?:最\s*低|总)\s*学\s*分", rule_text)
        practice_credits = float(positional.group(1)) if positional else None
    return {
        "file_name": item.get("file_name") or "", "major_hint": hint,
        "goals": numbered_items(section(text, ("一、培养目标", "培养目标"))),
        "requirements": numbered_items(section(text, (
            "四、毕业生应获得的知识和能力", "毕业生应获得的知识和能力", "毕业要求"))),
        "minimum_credits": float(total_match.group(1)) if total_match else None,
        "required_min_credits": credit_value("必修课"),
        "elective_min_credits": credit_value("选修课"),
        "practice_min_credits": practice_credits,
        "degree_requirement": clean(degree_match.group(1)) if degree_match else None,
        "module_requirements": table_module_requirements(item),
    }


def normalize_major(value: str) -> str:
    return re.sub(r"[（(].*?[）)]|专业|方向|本科|留学生|全英文", "", value or "")


def match_plan(conn: sqlite3.Connection, hint: str):
    rows = conn.execute("SELECT plan_id,plan_name,major_name FROM curriculum_plan ORDER BY plan_name").fetchall()
    # 先匹配完整方案名，确保“全英文授课/留学生/创新班”等同专业变体
    # 不会被错误归并到普通班方案。
    named = [r for r in rows if hint and hint in (r["plan_name"] or "")]
    if len(named) == 1:
        return named[0]
    exact_major = [r for r in rows if r["major_name"] == hint]
    if len(exact_major) == 1:
        return exact_major[0]
    normalized = normalize_major(hint)
    candidates = [r for r in rows if normalized and normalized in normalize_major(r["major_name"])]
    return candidates[0] if len(candidates) == 1 else None


def load_documents(input_path: Path, db_path: Path | None = None) -> dict:
    raw = json.loads(input_path.read_text(encoding="utf-8-sig"))
    documents = [parse_document(item) for item in raw]
    conn = init_v2(db_path)
    conn.row_factory = sqlite3.Row
    matched = goal_count = requirement_count = 0
    unmatched = []
    try:
        # 本数据集由文档快照全量重建，避免方案变体匹配规则调整后遗留旧行。
        conn.execute("DELETE FROM curriculum_plan_goal WHERE source='real'")
        conn.execute("DELETE FROM curriculum_graduation_requirement WHERE source='real'")
        conn.execute("DELETE FROM curriculum_plan_module_requirement WHERE source='real'")
        for doc in documents:
            plan = match_plan(conn, doc["major_hint"])
            if not plan:
                unmatched.append(doc["file_name"])
                continue
            matched += 1
            conn.execute("""UPDATE curriculum_plan SET total_credits=?,required_min_credits=?,
                elective_min_credits=?,practice_min_credits=?,degree_requirement=?,credit_rule_source_file=?
                WHERE plan_id=?""", (doc["minimum_credits"], doc["required_min_credits"],
                doc["elective_min_credits"], doc["practice_min_credits"], doc["degree_requirement"],
                doc["file_name"], plan["plan_id"]))
            conn.execute("DELETE FROM curriculum_plan_goal WHERE plan_id=?", (plan["plan_id"],))
            conn.execute("DELETE FROM curriculum_graduation_requirement WHERE plan_id=?", (plan["plan_id"],))
            for no, text in enumerate(doc["goals"], 1):
                conn.execute("INSERT INTO curriculum_plan_goal(plan_id,goal_no,goal_text,source_file,source_section) VALUES(?,?,?,?,?)",
                             (plan["plan_id"], no, text, doc["file_name"], "培养目标"))
                goal_count += 1
            for no, text in enumerate(doc["requirements"], 1):
                conn.execute("INSERT INTO curriculum_graduation_requirement(plan_id,requirement_no,requirement_title,requirement_text,source_file,source_section) VALUES(?,?,?,?,?,?)",
                             (plan["plan_id"], no, text.split("。", 1)[0][:40], text, doc["file_name"], "毕业生应获得的知识和能力"))
                requirement_count += 1
            for rule in doc["module_requirements"]:
                conn.execute("""INSERT OR IGNORE INTO curriculum_plan_module_requirement
                    (plan_id,parent_module,module_name,requirement_type,minimum_credits,raw_hierarchy,source_file,source_table)
                    VALUES(?,?,?,?,?,?,?,?)""", (plan["plan_id"], rule["parent_module"], rule["module_name"],
                    rule["requirement_type"], rule["minimum_credits"], rule["raw_hierarchy"],
                    doc["file_name"], rule["source_table"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"documents": len(documents), "matched": matched, "goals": goal_count,
            "requirements": requirement_count,
            "module_requirements": sum(len(x["module_requirements"]) for x in documents), "unmatched": unmatched}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--db", type=Path, default=config.V2_DB_PATH)
    args = parser.parse_args()
    print(json.dumps(load_documents(args.input, args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
