from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Protocol

from yuanbao_agent_platform.models import AgentPlan, ResultStatus

_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


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
    """Deterministic VLM adapter with confidence-driven outcomes.

    The mock writes small PNG files to the same artifact shape that a real
    device/VLM runner would produce. These files are execution evidence for the
    MVP, not screenshots captured from a physical device.
    """

    def __init__(self, artifact_root: str = "runtime_artifacts/screenshots"):
        self._artifact_root = Path(artifact_root)

    def run_plan(self, plan: AgentPlan, runtime_context: Dict[str, Any]) -> VisionAgentRun:
        force_status = runtime_context.get("force_status")
        observation_confidence = float(runtime_context.get("vision_confidence", 0.96))
        assertion_confidence = float(runtime_context.get("assertion_confidence", observation_confidence))
        visual_mismatch_count = int(runtime_context.get("visual_mismatch_count", 0))
        artifact_owner = str(runtime_context.get("task_id") or plan.plan_id)
        page_changed = bool(runtime_context.get("page_changed_detected") or runtime_context.get("step_path_invalid"))
        replan_attempt = int(runtime_context.get("replan_attempt", runtime_context.get("retry_count", 0)))
        actions = []

        for index, step in enumerate(plan.steps, start=1):
            step_confidence = min(observation_confidence, assertion_confidence)
            screenshot_path = self._write_observation_png(artifact_owner, index)
            actions.append(
                {
                    "observe": screenshot_path,
                    "think": f"VLM识别页面并寻找语义目标: {step['visual_target']}",
                    "plan": f"执行意图: {step['intent']}",
                    "act": step["intent"],
                    "verify": step["success_criteria"],
                    "mode": "vision_based_vlm",
                    "confidence": step_confidence,
                    "page_changed_detected": page_changed,
                    "replan_attempt": replan_attempt,
                }
            )

        confidence = min(observation_confidence, assertion_confidence)
        if force_status:
            status = ResultStatus(force_status)
        elif page_changed and replan_attempt == 0:
            status = ResultStatus.UNKNOWN
        elif confidence < 0.6:
            status = ResultStatus.UNKNOWN
        elif visual_mismatch_count > 0 and confidence >= 0.8:
            status = ResultStatus.FAIL
        else:
            status = ResultStatus.PASS

        if status == ResultStatus.PASS and page_changed and replan_attempt > 0:
            reason = "页面变化后，VLM重新 Observe/Plan/Act 并完成验证"
        elif status == ResultStatus.PASS:
            reason = "VLM视觉执行与断言验证通过"
        elif status == ResultStatus.UNKNOWN and page_changed and replan_attempt == 0:
            reason = "检测到页面改版或复现路径失效，触发Agent重新观察与规划"
        elif status == ResultStatus.FAIL:
            reason = "VLM观察到高置信度视觉状态与断言预期不一致"
        else:
            reason = "VLM无法可靠判断页面状态或断言结果"

        return VisionAgentRun(
            status=status,
            confidence=confidence,
            actions=actions,
            screenshots=[action["observe"] for action in actions],
            reason=reason,
        )

    def _write_observation_png(self, artifact_owner: str, step_index: int) -> str:
        safe_owner = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in artifact_owner)
        screenshot_dir = self._artifact_root / safe_owner
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / f"step-{step_index}-observe.png"
        screenshot_path.write_bytes(_MINIMAL_PNG)
        return screenshot_path.as_posix()


class OpenAICompatibleVisionAgentClient:
    """Production adapter skeleton for an OpenAI-compatible vision GUI Agent.

    This class intentionally does not import an SDK or perform network calls in
    the MVP. In a company environment it should be wired to an internal VLM/GUI
    Agent service that accepts screenshots, page context and AgentPlan steps,
    then returns action traces, visual verification confidence and PASS/FAIL/
    UNKNOWN status.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = "OPENAI_API_KEY",
        timeout_seconds: int = 180,
    ):
        self.base_url = base_url
        self.model = model
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    def run_plan(self, plan: AgentPlan, runtime_context: Dict[str, Any]) -> VisionAgentRun:
        raise NotImplementedError(
            "OpenAICompatibleVisionAgentClient is an integration boundary. "
            "Connect it to the real VLM/GUI Agent endpoint before production use."
        )
