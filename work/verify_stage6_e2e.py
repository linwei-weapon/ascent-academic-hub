# -*- coding: utf-8 -*-
"""阶段6 E2E下线回归：旧ai_experts路由应404，迁入端点与保留端点应可用。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def req(method, path, token=None, body=None):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(r, data, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def main():
    ok, fails = [], []

    def check(name, cond):
        (ok if cond else fails).append(name)

    # 登录
    s, login = req("POST", "/api/auth/login",
                   body={"username": "admin", "password": "Demo@2026"})
    token = (login.get("data") or {}).get("token") or login.get("token")
    check("登录", s == 200 and token)

    # 1) 旧路由应 404
    s, _ = req("GET", "/api/admin/ai/experts", token)
    check("旧 /ai/experts 已下线(404)", s == 404)
    s, _ = req("GET", "/api/admin/ai/experts/graduation-readiness/versions", token)
    check("旧 expert versions 已下线(404)", s == 404)
    s, _ = req("POST", "/api/admin/ai/experts/schemes/1/publish", token,
               body={"changeReason": "x"})
    check("旧 scheme publish 已下线(404/405)", s in (404, 405))

    # 2) 保留的 insight 端点仍可用
    s, insight = req("GET", "/api/admin/ai/insight/alert-summary", token)
    check("insight alert-summary 保留可用", s == 200)

    # 3) 迁入 system_management 的方案/版本端点可用
    s, schemes = req("GET", "/api/admin/system/analysis-schemes", token)
    payload = schemes.get("data") if isinstance(schemes, dict) else schemes
    check("GET /system/analysis-schemes 可用", s == 200 and payload)
    versions = (payload or {}).get("versions")
    check("方案响应含 versions 字段(发布/回滚对象)",
          isinstance(versions, list))

    # 4) 决策主链路不受影响
    s, briefing = req("GET", "/api/admin/ai/decision/briefing", token)
    check("决策简报可用", s == 200 and bool(
        (briefing.get("data") or briefing).get("topline")))
    s, status = req("GET", "/api/admin/ai/decision/llm-status", token)
    check("llm-status 可用", s == 200)

    print(f"通过 {len(ok)}/{len(ok) + len(fails)}")
    for name in ok:
        print("  OK ", name)
    for name in fails:
        print("  FAIL", name)
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
