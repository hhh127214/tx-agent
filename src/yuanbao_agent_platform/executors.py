from __future__ import annotations

from time import time
from typing import Dict
from uuid import uuid4

from yuanbao_agent_platform.agents import NaturalLanguageCaseConverter
from yuanbao_agent_platform.models import (
    AutomationType,
    ExecutionJob,
    ExecutionResult,
    ExecutionTrace,
    ResultStatus,
)
from yuanbao_agent_platform.vlm import MockVisionAgentClient, VisionAgentClient


class GuiAgentSimulator:
    """Adapter for the existing vision-based GUI Agent.

    The default client is a deterministic mock, but the interface matches the
    production boundary where a VLM/GUI Agent service would execute the plan.
    """

    def __init__(
        self,
        converter: NaturalLanguageCaseConverter,
        vision_client: VisionAgentClient = None,
    ):
        self._converter = converter
        self._vision_client = vision_client or MockVisionAgentClient()

    def execute(self, job: ExecutionJob) -> ExecutionResult:
        started = time()
        plan = self._converter.to_agent_plan(job.task.case)
        runtime_context = {
            "task_id": job.task.task_id,
            **job.task.metadata,
            "retry_count": job.task.retry_count,
        }
        run = self._vision_client.run_plan(plan, runtime_context)
        trace = ExecutionTrace(
            trace_id=f"trace-{uuid4().hex[:8]}",
            actions=run.actions,
            screenshots=run.screenshots,
            logs=["GUI Agent 通过VLM视觉语义目标执行，未依赖 XPath/ResourceId/坐标"],
            confidence=run.confidence,
        )
        return ExecutionResult(
            task_id=job.task.task_id,
            case_id=job.task.case.case_id,
            status=run.status,
            reason=run.reason,
            trace=trace,
            duration_seconds=round(time() - started, 4),
            confidence=run.confidence,
            writeback_target=job.task.metadata.get("writeback_target"),
            metadata={"plan_id": plan.plan_id, "resource": job.resource, **job.task.metadata},
        )


class BackendAutomationExecutor:
    def execute(self, job: ExecutionJob) -> ExecutionResult:
        started = time()
        actions = [
            {
                "step": step.step_id,
                "execute": step.intent,
                "target": step.target_semantics,
                "verify": step.expected_state,
            }
            for step in job.task.case.steps
        ]
        status = ResultStatus.FAIL if job.task.case.metadata.get("force_backend_failure") else ResultStatus.PASS
        trace = ExecutionTrace(
            trace_id=f"trace-{uuid4().hex[:8]}",
            actions=actions,
            logs=["后台自动化执行完成"],
            confidence=0.98,
        )
        return ExecutionResult(
            task_id=job.task.task_id,
            case_id=job.task.case.case_id,
            status=status,
            reason="后台自动化断言通过" if status == ResultStatus.PASS else "后台自动化断言失败",
            trace=trace,
            duration_seconds=round(time() - started, 4),
            confidence=0.98,
            writeback_target=job.task.metadata.get("writeback_target"),
            metadata={"resource": job.resource, **job.task.metadata},
        )


class ExecutionRouter:
    def __init__(self, gui_executor: GuiAgentSimulator, backend_executor: BackendAutomationExecutor):
        self._gui_executor = gui_executor
        self._backend_executor = backend_executor

    def execute(self, job: ExecutionJob) -> ExecutionResult:
        if job.task.case.automation_type == AutomationType.BACKEND_AUTOMATION:
            return self._backend_executor.execute(job)
        if job.task.case.automation_type == AutomationType.MANUAL_REVIEW:
            return self._manual_review(job)
        return self._gui_executor.execute(job)

    def _manual_review(self, job: ExecutionJob) -> ExecutionResult:
        trace = ExecutionTrace(
            trace_id=f"trace-{uuid4().hex[:8]}",
            actions=[],
            logs=["该用例需要人工复核"],
            confidence=0,
        )
        return ExecutionResult(
            task_id=job.task.task_id,
            case_id=job.task.case.case_id,
            status=ResultStatus.UNKNOWN,
            reason="用例被标记为人工复核",
            trace=trace,
            duration_seconds=0,
            confidence=0,
            writeback_target=job.task.metadata.get("writeback_target"),
        )


class ResultAnalyzer:
    def analyze(self, result: ExecutionResult) -> Dict[str, str]:
        if result.status == ResultStatus.PASS:
            category = "PASS"
        elif result.status == ResultStatus.FAIL and result.confidence >= 0.8:
            category = "PRODUCT_OR_ASSERTION_FAILURE"
        elif result.status == ResultStatus.UNKNOWN:
            category = "AGENT_UNABLE_TO_JUDGE"
        else:
            category = "ENVIRONMENT_OR_AGENT_FAILURE"
        return {"category": category, "reason": result.reason}
