"""统一响应包络 {code,msg,data} 与业务异常。前端只读 data，code/msg 兼容扩展。"""
from typing import Any


def ok(data: Any = None, msg: str = "ok") -> dict:
    return {"code": 0, "msg": msg, "data": data}


def fail(msg: str, code: int = 1, data: Any = None) -> dict:
    return {"code": code, "msg": msg, "data": data}


class ApiError(Exception):
    """业务异常：被全局处理器转成 {code,msg} 包络。"""

    def __init__(self, msg: str, code: int = 1, status_code: int = 400):
        super().__init__(msg)
        self.msg = msg
        self.code = code
        self.status_code = status_code
