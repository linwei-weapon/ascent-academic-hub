"""可配置的高校教学管理专家协议。"""

from .registry import (
    EXPERT_PROTOCOL_VERSION,
    apply_school_override,
    get_expert,
    list_experts,
    validate_expert_definition,
    validate_school_override,
)

__all__ = [
    "EXPERT_PROTOCOL_VERSION",
    "apply_school_override",
    "get_expert",
    "list_experts",
    "validate_expert_definition",
    "validate_school_override",
]
