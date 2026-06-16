from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

from yuanbao_agent_platform.models import AgentPlan, ResultStatus


@dataclass
class VisionAgentRun:
    status: ResultStatus
    confidence: float
    actions: List[Dict[str, Any]]
    screenshots: List[str]
    reason: str


class VisionAgentClient(Protocol):
    def run_plan(self, plan: AgentPlan, runtime_context: Dict[str, Any]) -> VisionAgentRun:
        """Execute an AgentPlan through a vision-based GUI Agent."""


class MockVisionAgentClient:
    """Deterministic VLM adapter with variable outcomes for tests and demos."""

    def run_plan(self, plan: AgentPlan, runtime_context: Dict[str, Any]) -> VisionAgentRun:
        force_status = runtime_context.get("force_status")
        confidence = float(runtime_context.get("vision_confidence", 0.96))
        actions = []

        for index, step in enumerate(plan.steps, start=1):
            actions.append(
                {
                    "observe": f"screen-{index}.png",
                    "think": f"VLM识别页面并寻找语义目标: {step['visual_target']}",
                    "plan": f"执行意图: {step['intent']}",
                    "act": step["intent"],
                    "verify": step["success_criteria"],
                    "mode": "vision_based_vlm",
                    "confidence": confidence,
                }
            )

        if force_status:
            status = ResultStatus(force_status)
        elif confidence < 0.6:
            status = ResultStatus.UNKNOWN
        elif "失败" in plan.goal and "验证" not in plan.goal:
            status = ResultStatus.FAIL
        else:
            status = ResultStatus.PASS

        if status == ResultStatus.PASS:
            reason = "VLM视觉执行与断言验证通过"
        elif status == ResultStatus.FAIL:
            reason = "VLM观察到页面结果与预期相反"
        else:
            reason = "VLM无法可靠判断页面状态或断言结果"

        return VisionAgentRun(
            status=status,
            confidence=confidence,
            actions=actions,
            screenshots=[action["observe"] for action in actions],
            reason=reason,
        )
