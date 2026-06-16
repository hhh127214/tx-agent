from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Iterable, List

from yuanbao_agent_platform.acceptance import AcceptanceReporter
from yuanbao_agent_platform.adapters import InternalAdapterRegistry
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
from yuanbao_agent_platform.storage import SQLiteStore


class YuanbaoTestingPlatform:
    def __init__(
        self,
        devices: int = 20,
        containers: int = 20,
        db_path: str = None,
        recover_pending: bool = False,
    ):
        self.store = SQLiteStore(db_path=db_path)
        self.case_converter = NaturalLanguageCaseConverter()
        self.bug_agent = BugRegressionAgent(self.case_converter)
        self.prd_agent = PRDTestDesignAgent()
        router = ExecutionRouter(
            gui_executor=GuiAgentSimulator(self.case_converter),
            backend_executor=BackendAutomationExecutor(),
        )
        self.integrations = IntegrationHub()
        self.adapters = InternalAdapterRegistry()
        self.metrics = MetricsCollector()
        self.quarantine = QuarantineManager()
        self.scheduler = ExecutionScheduler(
            router=router,
            resource_manager=ResourceManager(devices=devices, containers=containers),
            quarantine_manager=self.quarantine,
            analyzer=ResultAnalyzer(),
        )
        if recover_pending:
            self.recover_pending_tasks()

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
        metadata: Dict[str, Any] = None,
    ) -> Task:
        test_case = self.case_converter.convert(case_id, text)
        if metadata:
            test_case.metadata.update(metadata)
        return self.submit_case(scenario, test_case, trigger_type)

    def submit_case(self, scenario: Scenario, test_case: TestCase, trigger_type: TriggerType) -> Task:
        task = Task(
            scenario=scenario,
            case=test_case,
            trigger_type=trigger_type,
            source=test_case.source,
            metadata=dict(test_case.metadata),
        )
        submitted = self.scheduler.submit(task)
        self.store.save_task(submitted)
        return submitted

    def submit_backend_case(
        self,
        scenario: Scenario,
        title: str,
        steps: Iterable[str],
        metadata: Dict[str, Any] = None,
    ) -> Task:
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
            metadata=metadata or {},
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
                **regression_case.metadata,
                "writeback_target": "bug_system",
                "bug_id": bug.bug_id,
                "severity": bug.severity,
            },
        )
        self.scheduler.submit(task)
        self.store.save_task(task)
        results = self.scheduler.run_until_idle_concurrent(max_workers=8)
        self._persist_results(results)
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
        return asdict(self.prd_agent.generate(prd_id, prd_text))

    def run_queued_tasks(self, max_workers: int = 8) -> List[Dict[str, Any]]:
        results = self.scheduler.run_until_idle_concurrent(max_workers=max_workers)
        self._persist_results(results)
        for result in results:
            self._writeback_result(result)
        return [asdict(result) for result in results]

    def run_demo(self) -> Dict[str, Any]:
        manual = self.convert_manual_case(
            "case-notification-001",
            "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
        )
        scenario_examples = self._submit_four_scenario_examples()
        queued_results = self.run_queued_tasks(max_workers=8)
        queued_run_summary = self.scheduler.run_summary()
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
        prd = self.generate_prd_test_points(
            "PRD-2026-001",
            "用户可在设置页关闭通知开关。关闭后不再发送消息推送。用户重新登录、重启 App 或切换网络后状态应保持不变。若接口保存失败，应提示稍后重试，并保持原状态。",
        )
        return {
            "manual_case_conversion": manual,
            "scenario_examples": scenario_examples,
            "scheduler_policy": self.scheduler.policy_snapshot(),
            "scheduler_run_summary": queued_run_summary,
            "latest_scheduler_run_summary": self.scheduler.run_summary(),
            "queue_snapshot": self.scheduler.queue_snapshot(),
            "queued_results": queued_results,
            "prd_test_points": prd,
            "bug_regression_result": asdict(bug_result),
            "writebacks": self.integrations.snapshot(),
            "metrics": self.metrics.summarize(self.scheduler.submitted_tasks, self.scheduler.results),
            "integration_config": integration_config(),
            "quarantine": self.quarantine.snapshot(),
            "storage": self.store.stats(),
        }

    def run_large_scale_demo(self, total: int = 10000, max_workers: int = 32) -> Dict[str, Any]:
        texts = [
            "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
            "在搜索页输入天气，确认搜索结果列表展示并可点击第一条结果。",
            "进入会员中心，打开权益说明，检查续费入口和价格文案展示正常。",
            "进入历史记录页面，删除一条记录，验证刷新后该记录不再出现。",
        ]
        for index in range(total):
            scenario = [Scenario.INTEGRATION_BATCH, Scenario.DEV_SELF_TEST, Scenario.REQUIREMENT_TEST, Scenario.BUG_REGRESSION][index % 4]
            metadata = {}
            case_id = f"case-large-{index}"
            if scenario == Scenario.BUG_REGRESSION:
                metadata = {"severity": "P1", "bug_id": f"BUG-LS-{index}"}
            if index % 97 == 0:
                metadata["force_status"] = "UNKNOWN"
                metadata["vision_confidence"] = 0.42
                case_id = "case-problem-vision-low-confidence"
            self.submit_manual_case(
                scenario=scenario,
                case_id=case_id,
                text=texts[index % len(texts)],
                trigger_type=TriggerType.SCHEDULED if scenario == Scenario.INTEGRATION_BATCH else TriggerType.WEBHOOK,
                metadata=metadata,
            )

        results = self.scheduler.run_until_idle_concurrent(max_workers=max_workers, max_iterations=total * 2)
        self._persist_results(results)
        return {
            "requested_tasks": total,
            "produced_results": len(results),
            "scheduler_policy": self.scheduler.policy_snapshot()["scale"],
            "scheduler_run_summary": self.scheduler.run_summary(),
            "queue_snapshot": self.scheduler.queue_snapshot(),
            "metrics": self.metrics.summarize(self.scheduler.submitted_tasks, self.scheduler.results),
            "quarantine": self.quarantine.snapshot(),
            "sample_results": [asdict(result) for result in results[:5]],
            "storage": self.store.stats(),
        }

    def run_acceptance_report(self) -> Dict[str, Any]:
        report = AcceptanceReporter(self).build_report()
        self.store.save_acceptance_report(report)
        report["storage"] = self.store.stats()
        return report

    def recover_pending_tasks(self) -> Dict[str, Any]:
        tasks = self.store.load_recoverable_tasks()
        summary = self.scheduler.recover_tasks(tasks)
        return {
            **summary,
            "loaded_from_store": len(tasks),
            "queue_snapshot": self.scheduler.queue_snapshot(),
        }

    def _submit_four_scenario_examples(self) -> List[Dict[str, Any]]:
        tasks = [
            self.submit_manual_case(
                Scenario.INTEGRATION_BATCH,
                "case-integration-search-001",
                "集成测试批量执行：在搜索页输入天气，确认搜索结果列表展示并可点击第一条结果。",
                TriggerType.SCHEDULED,
                metadata={"batch_id": "batch-search-001", "business": "搜索域"},
            ),
            self.submit_manual_case(
                Scenario.DEV_SELF_TEST,
                "case-dev-notification-001",
                "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
                TriggerType.CI,
                metadata={"pipeline_id": "pipeline-001", "ci_blocking": True, "business": "设置域"},
            ),
            self.submit_manual_case(
                Scenario.REQUIREMENT_TEST,
                "case-requirement-member-001",
                "需求测试：进入会员中心，打开权益说明，检查续费入口和价格文案展示正常。",
                TriggerType.WEBHOOK,
                metadata={"requirement_id": "REQ-001", "business": "会员域"},
            ),
            self.submit_backend_case(
                Scenario.DEV_SELF_TEST,
                "开发自测：通知设置保存接口校验",
                ["调用保存通知设置接口", "查询用户设置状态", "验证状态为关闭"],
                metadata={"pipeline_id": "pipeline-001", "business": "设置域"},
            ),
        ]
        return [
            {
                "scenario": task.scenario.value,
                "task_id": task.task_id,
                "case_id": task.case.case_id,
                "business": task.metadata.get("business"),
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
        record = self.integrations.writeback_execution(result, target, external_id)
        self.store.save_writeback(record)
        return record

    def _persist_results(self, results) -> None:
        for result in results:
            self.store.save_result(result)
        for task in self.scheduler.submitted_tasks:
            self.store.save_task(task)
