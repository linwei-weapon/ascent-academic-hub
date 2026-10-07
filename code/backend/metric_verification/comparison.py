"""Prepare real manual observations without assigning a judgment automatically."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import re
from typing import Literal

from pydantic import BaseModel, Field
from backend.api.envelope import ApiError


class ComparisonRow(BaseModel):
    expectedKey: str | None = Field(default=None, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="", max_length=80)
    actual: str = Field(default="", max_length=12000)
    expected: str = Field(default="", max_length=12000)
    difference: str | None = Field(default=None, max_length=12000)


class ComparisonInput(BaseModel):
    expectedExecutionId: str | None = Field(default=None, max_length=100)
    scope: str = Field(default="", max_length=1000)
    period: str = Field(default="", max_length=300)
    asOf: str = Field(default="", max_length=100)
    dataVersion: str = Field(default="", max_length=500)
    coverage: Literal["display", "fact_application", "full_chain"] = "display"
    startLayer: Literal["source", "fact", "application", "manual"] = "manual"
    actualSource: str = Field(default="", max_length=2000)
    actualObservedAt: str = Field(default="", max_length=100)
    expectedSource: str = Field(default="", max_length=2000)
    expectedObservedAt: str = Field(default="", max_length=100)
    comparisonRule: str = Field(default="", max_length=1000)
    rows: list[ComparisonRow] = Field(default_factory=list, max_length=100)


def number(value: str) -> Decimal | None:
    text = value.strip()
    # Never infer percent scaling, dates, IDs, units or missing values.
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text) or len(text) > 80:
        return None
    try:
        result = Decimal(text.replace(",", ""))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def prepare(comparison: dict | None, judgment: str) -> dict | None:
    if comparison is None:
        return None
    result = deepcopy(comparison)
    required = ("scope", "period", "asOf", "actualSource", "actualObservedAt",
                "expectedSource", "expectedObservedAt", "comparisonRule")
    if judgment == "符合":
        if any(not str(result.get(key, "")).strip() for key in required) or not result.get("rows"):
            raise ApiError("符合判断需要填写双方真实值、来源、时间、同一范围及比较规则", status_code=422)
        if result["coverage"] == "full_chain" and result["startLayer"] != "source":
            raise ApiError("完整链路核对必须从贴源输入开始；也可选择本次实际核对的环节", status_code=422)
        if result["coverage"] == "full_chain" and not result.get("dataVersion", "").strip():
            raise ApiError("完整链路核对需要记录源、事实和应用的对应批次或快照依据", status_code=422)
    for row in result.get("rows", []):
        if judgment == "符合" and not str(row.get("unit", "")).strip():
            raise ApiError("请填写每项对照值的单位，文本集合可填“项”或“名单及顺序”", status_code=422)
        actual, expected = row.get("actual", "").strip(), row.get("expected", "").strip()
        if not actual or not expected:
            row["difference"] = None
            if judgment == "符合":
                raise ApiError("对照值尚未取得，请补齐或记录条件不足", status_code=422)
            continue
        a, b = number(actual), number(expected)
        if a is not None and b is not None:
            with localcontext() as context:
                context.prec = 180
                diff = a - b
            row["difference"] = format(diff, "f")
            equal = diff == 0
        else:
            equal = actual == expected
            row["difference"] = "内容相同" if equal else "内容不同，请核对成员、顺序或档位"
        if judgment == "符合" and result.get("comparisonRule", "").strip() in {"精确一致", "exact"} and not equal:
            raise ApiError("按精确一致比较仍有差异，不能保存为符合", status_code=422)
    return result
