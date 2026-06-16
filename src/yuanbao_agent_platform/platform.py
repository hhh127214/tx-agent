from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Iterable, List

from yuanbao_agent_platform.agents import BugRegressionAgent, NaturalLanguageCaseConverter, PRDTestDesignAgent
from yuanbao_agent_platform.config import integration_config
from yuanbao_agent_platform.executors import BackendAutomationExecutor, ExecutionRouter, GuiAgentSimulator, ResultAnalyzer
from yuanbao_agent_platform.integrations import IntegrationHub
from yuanbao_agent_platform.metrics import MetricsCollector
from yuanbao_agent_platform.models import (
    AutomationType,
    BugRegressionResult,
    BugReport,
    ResultStatus,
    Scenario,
    Task,
    TestCase,
    TestStep,
    TriggerType,
)
from yuanbao_agent_platform.scheduler import ExecutionScheduler, QuarantineManager, ResourceManager


class YuanbaoTestingPlatform:
    def __init__(self):
        self.case_converter = NaturalLanguageCaseConverter()
        self.bug_agent = BugRegressionAgent(self.case_converter)
        self.prd_agent = PRDTestDesignAgent()
        router = ExecutionRouter(
            gui_executor=GuiAgentSimulator(self.case_converter),
            backend_executor=BackendAutomationExecutor(),
        )
        self.integrations = IntegrationHub()
        self.metrics = MetricsCollector()
        self.quarantine = QuarantineManager()
        self.scheduler = ExecutionScheduler(
            router=router,
            resource_manager=ResourceManager(devices=3, containers=2),
            quarantine_manager=self.quarantine,
            analyzer=ResultAnalyzer(),
        )

    def convert_manual_case(self, case_id: str, text: str) -> Dict[str, Any]:
        test_case = self.case_converter.convert(case_id, text)
        return {
            "ir": self.case_converter.as_ir(test_case),
            "agent_plan": asdict(self.case_converter.to_agent_plan(test_case)),
        }

    def submit_manual_case(
        self,
        scenario: Scenario,
        case_id: str,
        text: str,
        trigger_type: TriggerType = TriggerType.MANUAL,
    ) -> Task:
        test_case = self.case_converter.convert(case_id, text)
        return self.submit_case(scenario, test_case, trigger_type)

    def submit_case(self, scenario: Scenario, test_case: TestCase, trigger_type: TriggerType) -> Task:
        task = Task(
            scenario=scenario,
            case=test_case,
            trigger_type=trigger_type,
            source=test_case.source,
            metadata=dict(test_case.metadata),
        )
        return self.scheduler.submit(task)

    def submit_backend_case(self, scenario: Scenario, title: str, steps: Iterable[str]) -> Task:
        test_case = TestCase(
            case_id=f"backend-{abs(hash(title)) % 100000}",
            title=title,
            automation_type=AutomationType.BACKEND_AUTOMATION,
            steps=[
                TestStep(
                    step_id=f"b{index}",
                    intent="backend_assert",
                    target_semantics=step,
                    expected_state="后台断言通过",
                )
                for index, step in enumerate(steps, start=1)
            ],
            source="backend_generation",
        )
        return self.submit_case(scenario, test_case, TriggerType.CI if scenario == Scenario.DEV_SELF_TEST else TriggerType.MANUAL)

    def run_bug_regression(self, bug: BugReport) -> BugRegressionResult:
        regression_case = self.bug_agent.build_regression_case(bug)
        task = Task(
            scenario=Scenario.BUG_REGRESSION,
            case=regression_case,
            trigger_type=TriggerType.STATUS_CHANGE,
            source="bug_system",
            metadata={
                "writeback_target": "bug_system",
                "bug_id": bug.bug_id,
                "severity": bug.severity,
            },
        )
        self.scheduler.submit(task)
        results = self.scheduler.run_until_idle()
        result = next(item for item in reversed(results) if item.task_id == task.task_id)
        writeback = self._writeback_result(result)
        return BugRegressionResult(
            bug_id=bug.bug_id,
            result=result.status,
            conclusion=self._bug_conclusion(result.status, bug),
            evidence={
                "screenshots": result.trace.screenshots,
                "trace_id": result.trace.trace_id,
                "logs": result.trace.logs,
                "actions": result.trace.actions,
                "writeback": asdict(writeback) if writeback else None,
            },
            need_human_review=result.status == ResultStatus.UNKNOWN,
            unknown_reason=result.reason if result.status == ResultStatus.UNKNOWN else None,
        )

    def generate_prd_test_points(self, prd_id: str, prd_text: str) -> Dict[str, Any]:
        generation = self.prd_agent.generate(prd_id, prd_text)
        return asdict(generation)

    def run_queued_tasks(self) -> List[Dict[str, Any]]:
        results = self.scheduler.run_until_idle()
        for result in results:
            self._writeback_result(result)
        return [asdict(result) for result in results]

    def run_demo(self) -> Dict[str, Any]:
        manual = self.convert_manual_case(
            "case-notification-001",
            "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
        )
        scenario_examples = self._submit_four_scenario_examples()
        queued_results = self.run_queued_tasks()
        bug_result = self.run_bug_regression(
            BugReport(
                bug_id="BUG-1024",
                title="关闭通知开关后重新进入设置页仍显示开启",
                status="待回归",
                severity="P1",
                version="8.1.1",
                steps=["登录账号", "进入我的页面", "点击设置", "关闭通知开关", "退出设置页后重新进入"],
                expected="通知开关保持关闭",
                actual="通知开关重新变为开启",
            )
        )
        metrics = self.metrics.summarize(self.scheduler.submitted_tasks, self.scheduler.results)
        prd = self.generate_prd_test_points(
            "PRD-2026-001",
            "用户可在设置页关闭通知开关。关闭后不再发送消息推送。用户重新登录、重启 App 或切换网络后状态应保持不变。若接口保存失败，应提示稍后重试，并保持原状态。",
        )
        return {
            "manual_case_conversion": manual,
            "scenario_examples": scenario_examples,
            "scheduler_policy": self.scheduler.policy_snapshot(),
            "queue_snapshot": self.scheduler.queue_snapshot(),
            "queued_results": queued_results,
            "prd_test_points": prd,
            "bug_regression_result": asdict(bug_result),
            "writebacks": self.integrations.snapshot(),
            "metrics": metrics,
            "integration_config": integration_config(),
            "quarantine": self.quarantine.snapshot(),
        }

    def _submit_four_scenario_examples(self) -> List[Dict[str, Any]]:
        tasks = []
        tasks.append(
            self.submit_manual_case(
                Scenario.INTEGRATION_BATCH,
                "case-integration-001",
                "集成测试批量执行：登录后进入我的页面，点击设置，检查通知开关入口可见。",
                TriggerType.SCHEDULED,
            )
        )
        self.submit_manual_case(
            Scenario.DEV_SELF_TEST,
            "case-notification-001",
            "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
            TriggerType.CI,
        )
        tasks.append(self.scheduler.submitted_tasks[-1])
        tasks.append(
            self.submit_manual_case(
                Scenario.REQUIREMENT_TEST,
                "case-requirement-001",
                "需求测试：进入设置页，关闭通知开关，模拟保存失败后验证提示稍后重试并保持原状态。",
                TriggerType.WEBHOOK,
            )
        )
        tasks.append(
            self.submit_backend_case(
                Scenario.DEV_SELF_TEST,
                "开发自测：通知设置保存接口校验",
                ["调用保存通知设置接口", "查询用户设置状态", "验证状态为关闭"],
            )
        )
        return [
            {
                "scenario": task.scenario.value,
                "task_id": task.task_id,
                "case_id": task.case.case_id,
                "priority": task.priority,
                "timeout_seconds": task.timeout_seconds,
                "max_retry": task.max_retry,
                "writeback_target": task.metadata.get("writeback_target"),
                "scheduler_policy": task.metadata.get("scheduler_policy"),
            }
            for task in tasks
        ]

    def _bug_conclusion(self, status: ResultStatus, bug: BugReport) -> str:
        if status == ResultStatus.PASS:
            return f"回归通过，未复现原问题：{bug.actual}"
        if status == ResultStatus.FAIL:
            return f"回归失败，疑似仍存在：{bug.actual}"
        return "Agent 无法判定，需要人工复核"

    def _writeback_result(self, result):
        target = result.writeback_target
        if not target:
            return None
        external_id = (
            result.metadata.get("bug_id")
            or result.metadata.get("requirement_id")
            or result.metadata.get("pipeline_id")
            or result.metadata.get("batch_id")
            or result.task_id
        )
        return self.integrations.writeback_execution(result, target, external_id)
