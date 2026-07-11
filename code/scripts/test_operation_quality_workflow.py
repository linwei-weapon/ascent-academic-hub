"""教学运行数据质量状态机专项测试，使用临时问题并清理。"""
import json, sqlite3, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.settings import DB_PATH

BASE="http://127.0.0.1:8000"; PASSWORD="Demo@2026"; ISSUE="AUTOTEST:operation-quality"
def req(path,token=None,method="GET",body=None):
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    r=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
    try:
        with urllib.request.urlopen(r) as x:return x.status,json.loads(x.read())
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
def login(user): return req("/api/auth/login",method="POST",body={"username":user,"password":PASSWORD})[1]["data"]["token"]
if __name__=="__main__":
    c=sqlite3.connect(DB_PATH); now=datetime.now().isoformat(timespec="seconds")
    c.execute("""INSERT OR REPLACE INTO data_quality_issue(issue_id,domain,issue_type,semester_id,entity_type,
      entity_id,affected_rows,severity,status,detail,recommendation,detected_at,source)
      VALUES (?, 'operation','autotest','2025-2026-2','teacher','TEST',1,'low','open','test','test',?,'derived')""",(ISSUE,now));c.commit()
    dean,quality=login("dean"),login("quality_office")
    try:
        path="/api/admin/operation/data-quality/"+urllib.parse.quote(ISSUE,safe="")+"/status"
        assert req(path,quality,"PUT",{"status":"reviewing","comment":"x"})[0]==403
        assert req(path,dean,"PUT",{"status":"reviewing","comment":"开始复核"})[1]["data"]["status"]=="reviewing"
        assert req(path,dean,"PUT",{"status":"closed","comment":"确认源数据已修复"})[1]["data"]["status"]=="closed"
        assert req(path,dean,"PUT",{"status":"open","comment":"复核发现仍有问题"})[1]["data"]["status"]=="open"
        trail=req("/api/admin/operation/data-quality/"+urllib.parse.quote(ISSUE,safe="")+"/audit",dean)[1]["data"]
        assert [x["to_status"] for x in trail]==["reviewing","closed","open"]
        print("PASS operation quality permissions, transitions, audit")
    finally:
        c.execute("DELETE FROM data_quality_issue_audit WHERE issue_id=?",(ISSUE,));c.execute("DELETE FROM data_quality_issue WHERE issue_id=?",(ISSUE,));c.commit();c.close()
