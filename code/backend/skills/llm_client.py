"""OpenAI 兼容协议的 LLM 客户端（决策点 D2：国内模型API/私有化均可接入）。

设计约束（来自已确认计划）：
- LLM 只做叙事，不产生数字；调用方拿到文本后做数字字面量校验，失败回退模板版。
- 重试 ≤ max_retries（默认1），超时/网络/5xx 可重试，4xx 与解析失败不重试。
- 所有失败抛 LLMError(kind=...)，由调用方决定回退与"规则生成"标注（决策点 D3）。
"""
from __future__ import annotations

import httpx

from .llm_config import llm_ready

# 错误分类：not_configured 不算故障（走规则版）；其余为真实故障，需诚实标注
KIND_NOT_CONFIGURED = "not_configured"
KIND_TIMEOUT = "timeout"
KIND_NETWORK = "network"
KIND_HTTP = "http"
KIND_INVALID_RESPONSE = "invalid_response"

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(Exception):
    def __init__(self, kind: str, detail: str = "", status: int | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail
        self.status = status


def chat_completion(cfg: dict, messages: list[dict], *,
                    max_tokens: int = 800, temperature: float = 0.2) -> str:
    """同步调用 OpenAI 兼容 Chat Completions，返回纯文本。

    cfg 来自 llm_config.load_config。失败抛 LLMError。
    """
    if not llm_ready(cfg):
        raise LLMError(KIND_NOT_CONFIGURED, "LLM 未启用或配置不完整")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    timeout = float(cfg.get("timeout_seconds") or 20)
    retries = max(0, min(int(cfg.get("max_retries") or 0), 1))  # 稳定性防线：重试≤1

    last_error: LLMError | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            last_error = LLMError(KIND_TIMEOUT, str(exc) or "request timeout")
            continue
        except httpx.TransportError as exc:
            last_error = LLMError(KIND_NETWORK, str(exc) or "network error")
            continue

        if resp.status_code >= 400:
            last_error = LLMError(
                KIND_HTTP, _safe_body(resp), status=resp.status_code)
            if resp.status_code in _RETRYABLE_STATUS:
                continue
            break

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            return content.strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            last_error = LLMError(KIND_INVALID_RESPONSE, str(exc))
            break  # 解析失败重试无意义

    raise last_error or LLMError(KIND_NETWORK, "unknown failure")


def _safe_body(resp: httpx.Response, limit: int = 200) -> str:
    try:
        return resp.text[:limit]
    except Exception:
        return f"status={resp.status_code}"


def test_connection(cfg: dict, timeout: float = 8) -> str:
    """连通性测试：保存前的试调，只要求 base_url/api_key/model 齐全（不要求 enabled）。

    返回模型回复文本；失败抛 LLMError（kind 同 chat_completion）。
    """
    if not (cfg.get("base_url") and cfg.get("api_key") and cfg.get("model")):
        raise LLMError(KIND_NOT_CONFIGURED, "base_url / api_key / model 未配齐")
    trial = dict(cfg)
    trial["enabled"] = True
    trial["timeout_seconds"] = timeout
    trial["max_retries"] = 0  # 测试调用不重试，快速反馈
    return chat_completion(trial, [
        {"role": "user", "content": "连通性测试，请回复 ok"}], max_tokens=8, temperature=0)
