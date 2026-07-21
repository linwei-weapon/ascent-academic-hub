# -*- coding: utf-8 -*-
"""阶段5端到端验证：配置中心端点 + 三态流转 + 菜单可见性（打 :8000 真实服务）。"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def login(client, username, password="Demo@2026"):
    r = client.post(f"{BASE}/api/auth/login",
                    json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["data"]["token"]


def main():
    client = httpx.Client(timeout=60)
    token = login(client, "admin")
    h = {"Authorization": f"Bearer {token}"}

    # 1) Skill配置清单
    r = client.get(f"{BASE}/api/admin/ai/decision/config/skills", headers=h)
    items = r.json()["data"]["items"]
    check("配置清单4个Skill", len(items) == 4, str(len(items)))
    gap = [i for i in items if i["skill_id"] == "graduation-gap"][0]
    check("含默认配置与边界", bool(gap["default_config"]) and bool(gap["config_bounds"]))
    check("初始为产品默认", gap["config_version"] == "product_default", gap["config_version"])

    # 2) 越界值被拒
    r = client.post(f"{BASE}/api/admin/ai/decision/config/skills/course-quality/draft",
                    headers=h, json={"override": {"min_sample": 5},
                                     "changeReason": "越界应拒绝"})
    check("越界覆写400", r.status_code == 400, r.text[:80])

    # 3) 非白名单键被拒
    r = client.post(f"{BASE}/api/admin/ai/decision/config/skills/course-quality/draft",
                    headers=h, json={"override": {"formula": "x"},
                                     "changeReason": "非白名单应拒绝"})
    check("非白名单400", r.status_code == 400, r.text[:80])

    # 4) 合法草稿 → 发布 → 生效（取值 = 默认+5，避开与默认值相同的假阳性）
    default_min = [i for i in items if i["skill_id"] == "course-quality"][0][
        "default_config"]["min_sample"]
    new_min = default_min + 5
    r = client.post(f"{BASE}/api/admin/ai/decision/config/skills/course-quality/draft",
                    headers=h, json={"override": {"min_sample": new_min},
                                     "changeReason": "端到端验证草稿"})
    check("创建草稿", r.status_code == 200, r.text[:100])
    draft = r.json()["data"]
    r = client.get(f"{BASE}/api/admin/ai/decision/config/skills", headers=h)
    cq = [i for i in r.json()["data"]["items"] if i["skill_id"] == "course-quality"][0]
    check("草稿未发布不生效", cq["config_version"] == "product_default"
          and cq["active_config"]["min_sample"] == default_min)

    r = client.post(f"{BASE}/api/admin/ai/decision/config/skills/course-quality/publish",
                    headers=h, json={"configId": draft["configId"]})
    check("发布草稿", r.status_code == 200, r.text[:100])
    r = client.get(f"{BASE}/api/admin/ai/decision/config/skills", headers=h)
    cq = [i for i in r.json()["data"]["items"] if i["skill_id"] == "course-quality"][0]
    check("发布后生效", cq["active_config"]["min_sample"] == new_min
          and cq["config_version"] != "product_default", cq["config_version"])

    # 5) 发布影响Skill运行配置（简报重算可见config_version变化）
    r = client.get(f"{BASE}/api/admin/ai/decision/briefing?force=true", headers=h, timeout=90)
    sec = [s for s in r.json()["data"]["skill_sections"]
           if s["skill_id"] == "course-quality"][0]
    check("简报反映新配置版本", sec["config_version"] == cq["config_version"],
          sec["config_version"])

    # 6) 回滚到产品默认之前的状态 → 再回滚（回滚链）
    versions = cq["versions"]
    first = [v for v in versions if v["change_reason"] == "端到端验证草稿"][0]
    r = client.post(f"{BASE}/api/admin/ai/decision/config/skills/course-quality/rollback",
                    headers=h, json={"configId": first["config_id"],
                                     "changeReason": "端到端验证回滚"})
    check("回滚成功", r.status_code == 200, r.text[:100])

    # 7) LLM配置：读取脱敏 → 保存 → 测试连接（未配齐时失败诚实返回）
    r = client.get(f"{BASE}/api/admin/ai/decision/config/llm", headers=h)
    llm = r.json()["data"]
    check("LLM配置读取脱敏", "has_api_key" in llm and "api_key" not in llm,
          json.dumps(llm, ensure_ascii=False)[:120])
    r = client.put(f"{BASE}/api/admin/ai/decision/config/llm", headers=h,
                   json={"enabled": False, "base_url": "", "model": "", "api_key": "",
                         "timeout_seconds": 20, "max_retries": 1,
                         "narrative_enabled": True, "chat_enabled": True})
    check("LLM配置保存(并清空遗留密钥)", r.status_code == 200
          and r.json()["data"]["enabled"] is False
          and r.json()["data"]["has_api_key"] is False)
    r = client.post(f"{BASE}/api/admin/ai/decision/config/llm/test", headers=h)
    t = r.json()["data"]
    check("未配齐时测试诚实失败", t["success"] is False and t["kind"] == "not_configured",
          json.dumps(t, ensure_ascii=False))

    # 8) 菜单可见性：dean(系统管理员)可见决策配置
    r = client.get(f"{BASE}/api/auth/me", headers=h)
    menus = json.dumps(r.json()["data"], ensure_ascii=False)
    check("dean可见决策配置菜单", "decision-config" in menus)

    # 9) 清理：course-quality 恢复产品默认，并刷新快照保持现场干净
    import sqlite3
    sys.path.insert(0, "code")
    from backend.etl import config as etl_config
    conn = sqlite3.connect(str(etl_config.DB_PATH))
    conn.execute("DELETE FROM sys_ai_skill_config WHERE skill_id='course-quality'")
    conn.commit()
    conn.close()
    r = client.get(f"{BASE}/api/admin/ai/decision/config/skills", headers=h)
    cq = [i for i in r.json()["data"]["items"] if i["skill_id"] == "course-quality"][0]
    check("清理后回到产品默认", cq["config_version"] == "product_default")
    r = client.get(f"{BASE}/api/admin/ai/decision/briefing?force=true", headers=h, timeout=90)
    sec = [s for s in r.json()["data"]["skill_sections"]
           if s["skill_id"] == "course-quality"][0]
    check("快照恢复产品默认口径", sec["config_version"] == "product_default")

    print("\n=== RESULT ===")
    print("ALL PASS" if not FAILS else f"FAILURES: {FAILS}")
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
