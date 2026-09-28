"""Idempotent expert-team preparation; never rewrites legacy business facts.

Run from code/: python scripts/prepare_expert_team.py [--documents extracted.json]
The only legacy mutation is a new menu/action grant to the two leadership roles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.etl import config
from backend.expert_team.storage import migrate, now


def sections(text):
    text = text.replace("\x07", " ").replace("\r", "\n")
    matches = list(re.finditer(r"(?m)^\s*([一二三四五六七八九十]+\s*[、．.][^\n]{1,70})", text))
    if not matches:
        return [{"title":"方案原文", "text":text[:80000]}]
    return [{"title":m.group(1).strip(),"text":text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip()[:80000]}
            for i,m in enumerate(matches)]


def document_issues(plan_name, parts):
    goals = "\n".join(x["text"] for x in parts if "培养目标" in x["title"])
    issues=[]
    if not goals: issues.append("未定位到培养目标章节，需要检查原文结构")
    if "人工智能" in plan_name and "石油工程" in goals and "人工智能" not in goals:
        issues.append("培养目标为石油工程表述，与人工智能方案名称不一致；原文归属需确认，暂不用于定位判断")
    return issues


def import_courses(v2, team):
    import openpyxl
    row=v2.execute("SELECT source_file FROM data_batch WHERE source_code='plan_course' ORDER BY ingested_at DESC LIMIT 1").fetchone()
    if not row or not Path(row[0]).is_file():
        return {"status":"source_missing","rows":0}
    source=Path(row[0]);digest=hashlib.sha256(source.read_bytes()).hexdigest()
    wb=openpyxl.load_workbook(source,read_only=True,data_only=True)
    try:
        sheet=wb.worksheets[0]
        sheet.reset_dimensions()  # exported source advertises A1:A1 despite having all rows
        records=sheet.iter_rows(values_only=True)
        next(records);headers=[str(x).strip() if x is not None else "" for x in next(records)]
        required={"培养方案名称","课程代码","课程名称","课程模块","学分","总学时","考核方式","开课学期"}
        if not required.issubset(headers): raise ValueError("方案源表缺少必要字段")
        plan_ids={r[1]:r[0] for r in v2.execute("SELECT plan_id,plan_name FROM curriculum_plan WHERE source='real'")}
        output=[]
        def txt(x): return str(x).strip() if x is not None else ""
        def num(x):
            try:return float(x) if x is not None else None
            except (ValueError,TypeError):return None
        for index,record in enumerate(records,3):
            r=dict(zip(headers,record));pid=plan_ids.get(txt(r.get("培养方案名称")));cid=txt(r.get("课程代码"))
            if not pid or not cid:continue
            output.append((pid,index,cid,txt(r.get("课程名称")),txt(r.get("课程模块")),
                txt(r.get("是否必修")) or txt(r.get("课程性质")),num(r.get("学分")),num(r.get("总学时")),
                txt(r.get("考核方式")),txt(r.get("开课学期")),source.name,digest))
        if not output:raise ValueError("原始方案课程无匹配行，保留已有独立数据")
        team.execute("DELETE FROM team_plan_course")
        team.executemany("INSERT INTO team_plan_course VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",output)
        return {"status":"ready","rows":len(output),"source":source.name,"sha256":digest}
    finally:wb.close()


def import_documents(v2,team,source):
    if not source:return {"status":"not_imported","documents":0}
    documents=json.loads(Path(source).read_text(encoding="utf-8-sig"));matched=0;issues=[];unmatched=[]
    plans=list(v2.execute("SELECT plan_id,plan_name FROM curriculum_plan WHERE source='real'"))
    for d in documents:
        # Exact filename stem only. Never strip class/track variants to force a match.
        stem=Path(d["file_name"]).stem
        matches=[p for p in plans if p[1]==stem]
        if len(matches)!=1:
            unmatched.append(d["file_name"]);continue
        text=d.get("text") or ""
        if not text.strip():unmatched.append(d["file_name"]);continue
        parts=sections(text);warnings=document_issues(stem,parts)
        team.execute("""INSERT INTO team_document VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET
            file_name=excluded.file_name,file_hash=excluded.file_hash,content=excluded.content,sections_json=excluded.sections_json,
            status=excluded.status,issues_json=excluded.issues_json,imported_at=excluded.imported_at""",
            (matches[0][0],d["file_name"],d.get("file_hash"),text,json.dumps(parts,ensure_ascii=False),
             "conflict" if warnings else "extracted",json.dumps(warnings,ensure_ascii=False),now()))
        matched+=1
        if warnings:issues.append({"file":d["file_name"],"issues":warnings})
    return {"status":"imported","documents":matched,"unmatched":unmatched,"issues":issues}


def install_menu(legacy):
    from backend.api.permission_context import EXPERT_TEAM_ROLES
    menu="/admin/reports/expert-team"
    parent=legacy.execute("SELECT parent_id FROM sys_menu WHERE path='/admin/reports/decision'").fetchone()
    if not parent or not parent[0]:raise ValueError("现有AI管理决策菜单不存在，未修改菜单结构")
    order=legacy.execute("SELECT COALESCE(MAX(sort_order),0)+10 FROM sys_menu WHERE parent_id=? AND menu_id<>?",(parent[0],menu)).fetchone()[0]
    legacy.execute("INSERT OR IGNORE INTO sys_menu(menu_id,parent_id,title,path,icon,sort_order) VALUES(?,?,?,?,?,?)",
                   (menu,parent[0],"专家团",menu,"Collection",order))
    legacy.execute("UPDATE sys_menu SET sort_order=? WHERE menu_id=?",(order,menu))
    for role in EXPERT_TEAM_ROLES:
        if legacy.execute("SELECT 1 FROM sys_role WHERE role_id=?",(role,)).fetchone():
            legacy.execute("INSERT OR IGNORE INTO sys_role_menu(role_id,menu_id) VALUES(?,?)",(role,menu))
            legacy.execute("INSERT OR IGNORE INTO sys_role_action(role_id,action_id) VALUES(?,?)",(role,"expert_team.use"))


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--documents");args=parser.parse_args()
    legacy_path=config.DB_PATH;v2_path=config.V2_DB_PATH;team_path=legacy_path.with_name("expert_team.sqlite")
    # SQLite backup includes committed WAL contents; only before the first menu grant.
    legacy=sqlite3.connect(legacy_path.resolve().as_uri()+"?mode=rw",uri=True,timeout=20)
    if not legacy.execute("SELECT 1 FROM sys_menu WHERE path='/admin/reports/expert-team'").fetchone():
        backup=legacy_path.with_name("analytics.before-expert-team.sqlite")
        if backup.exists():raise RuntimeError("首次迁移备份已存在，请核对后再执行，未覆盖备份")
        with sqlite3.connect(backup) as destination:legacy.backup(destination)
        print("Backup:",backup)
    v2=sqlite3.connect(v2_path.resolve().as_uri()+"?mode=ro",uri=True)
    team=sqlite3.connect(team_path)
    try:
        with team:
            migrate(team)
            report={"courses":import_courses(v2,team),"documents":import_documents(v2,team,args.documents)}
            team.execute("INSERT OR REPLACE INTO team_meta VALUES('preparation',?)",(json.dumps({**report,"prepared_at":now()},ensure_ascii=False),))
        with legacy:install_menu(legacy)
        print(json.dumps(report,ensure_ascii=False))
    finally:team.close();v2.close();legacy.close()


if __name__=="__main__":main()
