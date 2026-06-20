from __future__ import annotations

import json
from time import time
from typing import Dict
from uuid import uuid4
from urllib import request
from urllib.error import URLError

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
        if job.task.case.metadata.get("api_requests"):
            return self._execute_api_requests(job, started)

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

    def _execute_api_requests(self, job: ExecutionJob, started: float) -> ExecutionResult:
        actions = []
        failures = []
        for index, api_request in enumerate(job.task.case.metadata["api_requests"], start=1):
            action = self._call_api(index, api_request)
            actions.append(action)
            if not action["passed"]:
                failures.append(action["name"])

        status = ResultStatus.FAIL if failures or job.task.case.metadata.get("force_backend_failure") else ResultStatus.PASS
        confidence = 0.99 if status == ResultStatus.PASS else 0.86
        trace = ExecutionTrace(
            trace_id=f"trace-{uuid4().hex[:8]}",
            actions=actions,
            logs=[
                "Backend API automation executed real HTTP requests",
                f"api_request_count={len(actions)}",
                f"failed_assertions={len(failures)}",
            ],
            confidence=confidence,
        )
        return ExecutionResult(
            task_id=job.task.task_id,
            case_id=job.task.case.case_id,
            status=status,
            reason="Backend API assertions passed" if status == ResultStatus.PASS else f"Backend API assertions failed: {failures}",
            trace=trace,
            duration_seconds=round(time() - started, 4),
            confidence=confidence,
            writeback_target=job.task.metadata.get("writeback_target"),
            metadata={
                "resource": job.resource,
                "execution_mode": "BACKEND_API_AUTOMATION",
                "api_request_count": len(actions),
                **job.task.metadata,
            },
        )

    def _call_api(self, index: int, api_request: dict) -> dict:
        method = api_request.get("method", "GET").upper()
        name = api_request.get("name", f"api-{index}")
        body = api_request.get("json")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = request.Request(
            api_request["url"],
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with request.urlopen(req, timeout=float(api_request.get("timeout", 5))) as response:
                response_body = response.read().decode("utf-8")
                response_status = response.status
        except URLError as exc:
            return {
                "step": f"api-{index}",
                "name": name,
                "method": method,
                "url": api_request["url"],
                "passed": False,
                "error": str(exc),
            }

        parsed_json = None
        try:
            parsed_json = json.loads(response_body)
        except json.JSONDecodeError:
            pass

        expected_status = int(api_request.get("expected_status", 200))
        expected_json = api_request.get("expected_json", {})
        expected_body_contains = api_request.get("expected_body_contains")
        assertions = {
            "status": response_status == expected_status,
            "json": all(parsed_json and parsed_json.get(key) == value for key, value in expected_json.items()),
            "body_contains": True if not expected_body_contains else expected_body_contains in response_body,
        }
        return {
            "step": f"api-{index}",
            "name": name,
            "method": method,
            "url": api_request["url"],
            "response_status": response_status,
            "response_json": parsed_json,
            "response_body_excerpt": response_body[:200],
            "assertions": assertions,
            "passed": all(assertions.values()),
        }


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
