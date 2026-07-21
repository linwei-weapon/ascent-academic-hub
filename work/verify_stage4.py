# -*- coding: utf-8 -*-
"""阶段4端到端验证：LLM状态/简报叙事回退/对话SSE五意图（打 :8000 真实服务）。"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def login(client):
    r = client.post(f"{BASE}/api/auth/login",
                    json={"username": "admin", "password": "Demo@2026"})
    r.raise_for_status()
    return r.json()["data"]["token"]


def post_chat(client, token, message, signal_id=""):
    """消费SSE流，返回 {event: [payloads]}。"""
    events = {}
    with client.stream("POST", f"{BASE}/api/admin/ai/decision/chat",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"message": message, "signalId": signal_id},
                       timeout=60) as resp:
        assert resp.status_code == 200, f"chat status {resp.status_code}"
        event, data = "", ""
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:]
            elif line == "" and event and data:
                events.setdefault(event, []).append(json.loads(data))
                event, data = "", ""
    return events


def main():
    client = httpx.Client(timeout=60)
    token = login(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1) LLM状态：默认关闭
    r = client.get(f"{BASE}/api/admin/ai/decision/llm-status", headers=headers)
    status = r.json()["data"]
    check("llm-status默认关闭", status["enabled"] is False and status["ready"] is False,
          json.dumps(status, ensure_ascii=False))

    # 2) 简报：LLM关闭时走模板版并诚实标注
    r = client.get(f"{BASE}/api/admin/ai/decision/briefing", headers=headers)
    b = r.json()["data"]
    check("简报生成", bool(b.get("topline")), f"method={b.get('generation_method')}")
    check("LLM关闭时简报为规则生成", b.get("generation_method") == "rule_template")
    check("简报携带llm_status=disabled", b.get("llm_status") == "disabled",
          str(b.get("llm_status")))

    # 3) 查证意图：不调LLM，数字来自信号
    ev = post_chat(client, token, "毕业缺口受阻学生有多少？")
    text = "".join(d["text"] for d in ev.get("delta", []))
    check("查证意图识别", ev["meta"][0]["intent"] == "verify", ev["meta"][0].get("intent_label"))
    check("查证文本含真实数字", any(ch.isdigit() for ch in text), text[:80])
    check("查证标注not_used", ev["done"][0]["llm_status"] == "not_used")
    check("追问建议返回", len(ev["done"][0]["followups"]) > 0)

    # 4) 归因意图：三明治分层（LLM关闭时假设层为占位说明）
    ev = post_chat(client, token, "体质测试为什么会卡住这么多学生？")
    blocks = ev["done"][0]["blocks"]
    layers = [x["layer"] for x in blocks]
    check("归因意图识别", ev["meta"][0]["intent"] == "attribute")
    check("三明治三层", layers == ["facts", "hypothesis", "action"], str(layers))
    check("假设层诚实占位", "LLM" in blocks[1]["text"], blocks[1]["text"][:40])

    # 5) 假设测算：能力边界诚实声明
    ev = post_chat(client, token, "如果新增5个班，毕业缺口会缓解吗？")
    text = "".join(d["text"] for d in ev.get("delta", []))
    check("测算意图识别", ev["meta"][0]["intent"] == "simulate")
    check("测算能力边界声明", "后续阶段" in text, text[:60])

    # 6) 比较/开放：规则回退路径可用
    ev = post_chat(client, token, "目前整体情况怎么看？")
    check("开放意图有回答", len(ev.get("delta", [])) > 0)

    # 7) 信号上下文追问（signalId直接锚定）
    card = b["priority_items"][0]
    q = (card.get("suggested_questions") or ["为什么？"])[0]
    ev = post_chat(client, token, q, signal_id=card["signal_id"])
    cited = ev["meta"][0]["cited"]
    check("signalId锚定引用", cited and cited[0]["signal_id"] == card["signal_id"])
    check("引用信号不含大context", cited and "context" not in cited[0])

    # 8) LLM故障注入：配置一个不可达端点，验证回退与诚实标注，随后恢复
    sys.path.insert(0, "code")
    import sqlite3
    from backend.etl import config as etl_config
    from backend.skills import llm_config

    conn = sqlite3.connect(str(etl_config.DB_PATH))
    llm_config.save_config(conn, {
        "enabled": True, "base_url": "http://127.0.0.1:9/v1",
        "api_key": "x", "model": "fake", "timeout_seconds": 3}, "verify")
    try:
        r = client.get(f"{BASE}/api/admin/ai/decision/briefing?force=true",
                       headers=headers, timeout=90)
        b2 = r.json()["data"]
        check("故障时简报仍可用(回退模板)",
              b2.get("generation_method") == "rule_template" and b2.get("topline"))
        check("故障诚实标注", str(b2.get("llm_status", "")).startswith("failed:"),
              str(b2.get("llm_status")))

        ev = post_chat(client, token, "体质测试为什么会卡住这么多学生？")
        done = ev["done"][0]
        check("故障时对话三明治仍完整",
              [x["layer"] for x in done["blocks"]] == ["facts", "hypothesis", "action"])
        check("对话故障诚实标注", done["llm_status"].startswith("failed:"),
              done["llm_status"])
    finally:
        llm_config.save_config(conn, {"enabled": False}, "verify")
        conn.close()

    # 9) 恢复后强制重算：状态回到disabled
    r = client.get(f"{BASE}/api/admin/ai/decision/briefing?force=true",
                   headers=headers, timeout=90)
    b3 = r.json()["data"]
    check("恢复后回到规则生成", b3.get("generation_method") == "rule_template"
          and b3.get("llm_status") == "disabled", str(b3.get("llm_status")))

    print("\n=== RESULT ===")
    print("ALL PASS" if not FAILS else f"FAILURES: {FAILS}")
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
