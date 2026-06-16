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
    TestCase,
)


class GuiAgentSimulator:
    """Local deterministic stand-in for the existing vision-based GUI Agent."""

    def __init__(self, converter: NaturalLanguageCaseConverter):
        self._converter = converter

    def execute(self, job: ExecutionJob) -> ExecutionResult:
        started = time()
        plan = self._converter.to_agent_plan(job.task.case)
        actions = []
        confidence = 0.96

        for index, step in enumerate(plan.steps, start=1):
            target = step["visual_target"]
            actions.append(
                {
                    "observe": f"screen-{index}.png",
                    "think": f"寻找语义目标: {target}",
                    "act": step["intent"],
                    "verify": step["success_criteria"],
                    "mode": "vision_based",
                }
            )
            if "无法判定" in target or "不明确" in target:
                confidence = 0.45

        status = self._decide_status(job.task.case, confidence)
        reason = self._reason(status, job.task.case)
        trace = ExecutionTrace(
            trace_id=f"trace-{uuid4().hex[:8]}",
            actions=actions,
            screenshots=[action["observe"] for action in actions],
            logs=["GUI Agent 使用视觉语义目标执行，未依赖 XPath/ResourceId/坐标"],
            confidence=confidence,
        )
        return ExecutionResult(
            task_id=job.task.task_id,
            case_id=job.task.case.case_id,
            status=status,
            reason=reason,
            trace=trace,
            duration_seconds=round(time() - started, 4),
            confidence=confidence,
            writeback_target=job.task.metadata.get("writeback_target"),
            metadata={"plan_id": plan.plan_id, "resource": job.resource, **job.task.metadata},
        )

    def _decide_status(self, test_case: TestCase, confidence: float) -> ResultStatus:
        raw = " ".join([test_case.title] + [step.target_semantics for step in test_case.steps])
        if confidence < 0.6:
            return ResultStatus.UNKNOWN
        if "失败" in raw and "验证" not in raw:
            return ResultStatus.FAIL
        return ResultStatus.PASS

    def _reason(self, status: ResultStatus, test_case: TestCase) -> str:
        if status == ResultStatus.PASS:
            return "视觉执行与断言验证通过"
        if status == ResultStatus.FAIL:
            return "页面明确展示与预期相反的结果"
        return "断言不明确或视觉置信度不足"


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
        status = ResultStatus.PASS
        if job.task.case.metadata.get("force_backend_failure"):
            status = ResultStatus.FAIL

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
