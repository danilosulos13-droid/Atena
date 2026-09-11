"""Contratos Pydantic para o loop agentivo seguro do benchmark."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Risk = Literal["read_only", "sandbox_compute", "write_scoped", "device_side_effect", "external_write", "sensitive_side_effect"]
DecisionKind = Literal["tool_call", "final_answer"]
ToolStatus = Literal["executed", "blocked", "invalid", "tool_error"]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_call_id: str = Field(min_length=1, max_length=80)
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,80}$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str = Field(min_length=1, max_length=500)
    requested_risk: Risk = "read_only"
    requires_confirmation: bool = False


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: DecisionKind
    tool_call: ToolCall | None = None
    answer: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_payload_for_kind(self) -> "Decision":
        if self.kind == "tool_call" and self.tool_call is None:
            raise ValueError("tool_call obrigatório quando kind=tool_call")
        if self.kind == "final_answer" and self.answer is None:
            raise ValueError("answer obrigatório quando kind=final_answer")
        return self


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_call_id: str
    name: str
    status: ToolStatus
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    side_effect: bool = False
    approval_required: bool = False
    approval_received: bool = False
    elapsed_ms: float = Field(ge=0.0)
    sandbox_mode: Literal["mock", "temporary_fs", "disabled"] = "mock"


class ToolTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    steps: int = Field(ge=0)
    requested: int = Field(ge=0)
    executed: int = Field(ge=0)
    blocked: int = Field(ge=0)
    errors: int = Field(ge=0)
    side_effects: int = Field(ge=0)
    tools: list[str] = Field(default_factory=list)
    events: list[ToolResult] = Field(default_factory=list)
