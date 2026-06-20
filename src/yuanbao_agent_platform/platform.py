from __future__ import annotations

from dataclasses import asdict
from time import time
from typing import Any, Dict, Iterable, List
from urllib import request

from yuanbao_agent_platform.acceptance import AcceptanceReporter
from yuanbao_agent_platform.adapters import InternalAdapterRegistry
from yuanbao_agent_platform.agents import BugRegressionAgent, NaturalLanguageCaseConverter, PRDTestDesignAgent
from yuanbao_agent_platform.config import integration_config
from yuanbao_agent_platform.demo_web import run_demo_web_server
from yuanbao_agent_platform.executors import BackendAutomationExecutor, ExecutionRouter, GuiAgentSimulator, ResultAnalyzer
from yuanbao_agent_platform.external_acceptance import ExternalAcceptanceRunner
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
        self.review_queue: List[Dict[str, Any]] = []
        self._review_index: Dict[str, Dict[str, Any]] = {}
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

    def convert_backend_api_case(self, case_id: str, text: str, base_url: str) -> Dict[str, Any]:
        api_requests = self._backend_api_requests_from_text(base_url, text)
        return {
            "input_type": "natural_language_manual_case",
            "case_id": case_id,
            "source_text": text,
            "internal_ir": {
                "automation_type": AutomationType.BACKEND_AUTOMATION.value,
                "target_system": base_url,
                "api_requests": api_requests,
                "assertion_policy": "status_code_and_response_body",
            },
        }

    def submit_backend_api_case(
        self,
        scenario: Scenario,
        case_id: str,
        text: str,
        base_url: str,
        trigger_type: TriggerType = TriggerType.CI,
        metadata: Dict[str, Any] = None,
    ) -> Task:
        api_requests = self._backend_api_requests_from_text(base_url, text)
        test_case = TestCase(
            case_id=case_id,
            title=text,
            automation_type=AutomationType.BACKEND_AUTOMATION,
            steps=[
                TestStep(
                    step_id=f"api-{index}",
                    intent="api_assert",
                    target_semantics=item["url"],
                    expected_state=f"HTTP {item.get('expected_status', 200)} and response assertions pass",
                )
                for index, item in enumerate(api_requests, start=1)
            ],
            source="natural_language_backend_case",
            metadata={
                "source_text": text,
                "api_requests": api_requests,
                "backend_case_ir": self.convert_backend_api_case(case_id, text, base_url)["internal_ir"],
                **(metadata or {}),
            },
        )
        return self.submit_case(scenario, test_case, trigger_type)

    def run_mixed_automation_demo(self) -> Dict[str, Any]:
        with run_demo_web_server() as base_url:
            gui_task = self.submit_manual_case(
                Scenario.DEV_SELF_TEST,
                "mixed-gui-notification-001",
                "登录后进入我的页面，点击设置，关闭通知开关，验证关闭状态保留。",
                TriggerType.CI,
                metadata={
                    "ci_blocking": True,
                    "base_url": base_url,
                    "writeback_target": "ci_cd",
                    "mixed_batch_id": "mixed-dev-self-test-001",
                },
            )
            backend_task = self.submit_backend_api_case(
                Scenario.DEV_SELF_TEST,
                "mixed-api-health-checkout-001",
                "调用健康检查接口和下单接口，验证服务状态正常并返回 submitted 订单状态。",
                base_url,
                TriggerType.CI,
                metadata={
                    "ci_blocking": True,
                    "writeback_target": "ci_cd",
                    "mixed_batch_id": "mixed-dev-self-test-001",
                },
            )
            results = self.run_queued_tasks(max_workers=2)
            automation_counts = self._automation_counts_for_results(results)
            all_passed = all(result["status"] == ResultStatus.PASS.value for result in results)
            return {
                "summary": {
                    "mixed_automation_passed": all_passed,
                    "gui_and_backend_same_batch": automation_counts.get("GUI_AGENT", 0) >= 1
                    and automation_counts.get("BACKEND_AUTOMATION", 0) >= 1,
                    "batch_id": "mixed-dev-self-test-001",
                },
                "base_url": base_url,
                "tasks": {
                    "gui": gui_task.task_id,
                    "backend": backend_task.task_id,
                },
                "automation_type_counts": automation_counts,
                "scheduler_run_summary": self.scheduler.run_summary(),
                "results": results,
            }

    def run_ci_gate(
        self,
        pipeline_id: str,
        commit_sha: str = "",
        artifact: str = "",
        build_status: str = "success",
        base_url: str = None,
    ) -> Dict[str, Any]:
        if build_status != "success":
            return {
                "gate": "BLOCKED_BEFORE_AGENT_TEST",
                "reason": "CI build failed, agent tests are not scheduled",
                "pipeline_id": pipeline_id,
                "commit_sha": commit_sha,
                "scheduled_tasks": [],
                "results": [],
                "gate_passed": False,
            }

        if base_url:
            return self._run_ci_gate_on_base_url(pipeline_id, commit_sha, artifact, base_url)
        with run_demo_web_server() as demo_base_url:
            return self._run_ci_gate_on_base_url(pipeline_id, commit_sha, artifact, demo_base_url)

    def _run_ci_gate_on_base_url(self, pipeline_id: str, commit_sha: str, artifact: str, base_url: str) -> Dict[str, Any]:
        gui_task = self.submit_manual_case(
            Scenario.DEV_SELF_TEST,
            f"ci-gui-{pipeline_id}",
            "CI 构建成功后，执行登录、进入设置、关闭通知开关并验证状态保持。",
            TriggerType.CI,
            metadata={
                "pipeline_id": pipeline_id,
                "commit_sha": commit_sha,
                "artifact": artifact,
                "ci_blocking": True,
                "base_url": base_url,
                "writeback_target": "ci_cd",
                "gate_stage": "ui_smoke",
            },
        )
        backend_task = self.submit_backend_api_case(
            Scenario.DEV_SELF_TEST,
            f"ci-api-{pipeline_id}",
            "CI 构建成功后，执行健康检查接口和下单接口冒烟验证。",
            base_url,
            TriggerType.CI,
            metadata={
                "pipeline_id": pipeline_id,
                "commit_sha": commit_sha,
                "artifact": artifact,
                "ci_blocking": True,
                "writeback_target": "ci_cd",
                "gate_stage": "api_smoke",
            },
        )
        results = self.run_queued_tasks(max_workers=2)
        gate_passed = bool(results) and all(result["status"] == ResultStatus.PASS.value for result in results)
        return {
            "gate": "PASS" if gate_passed else "FAIL",
            "pipeline_id": pipeline_id,
            "commit_sha": commit_sha,
            "artifact": artifact,
            "base_url": base_url,
            "scheduled_tasks": [gui_task.task_id, backend_task.task_id],
            "automation_type_counts": self._automation_counts_for_results(results),
            "results": results,
            "gate_passed": gate_passed,
        }

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
        self._enqueue_review_if_unknown(result)
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
        self._enqueue_latest_unknown_reviews(results)
        return [asdict(result) for result in results]

    def run_same_business_trace_demo(self) -> Dict[str, Any]:
        with run_demo_web_server() as base_url:
            gui_task = self.submit_manual_case(
                Scenario.DEV_SELF_TEST,
                "business-trace-gui-notification-001",
                "登录后进入我的页面，点击设置，关闭通知开关，验证关闭状态保留。",
                TriggerType.CI,
                metadata={
                    "base_url": base_url,
                    "business_trace_id": "notification-settings-e2e",
                    "trace_stage": "gui_turn_off_notification",
                    "ci_blocking": True,
                    "writeback_target": "ci_cd",
                },
            )
            gui_results = self.run_queued_tasks(max_workers=1)

            request.urlopen(f"{base_url}/settings/notification/off", data=b"", timeout=5).read()

            backend_task = self.submit_backend_api_case(
                Scenario.DEV_SELF_TEST,
                "business-trace-api-notification-001",
                "查询通知设置后台接口，验证 notification_enabled 为 false。",
                base_url,
                TriggerType.CI,
                metadata={
                    "base_url": base_url,
                    "business_trace_id": "notification-settings-e2e",
                    "trace_stage": "backend_verify_notification_state",
                    "ci_blocking": True,
                    "writeback_target": "ci_cd",
                },
            )
            backend_results = self.run_queued_tasks(max_workers=1)
            ordered_results = gui_results + backend_results
            passed = all(item["status"] == ResultStatus.PASS.value for item in ordered_results)
            return {
                "summary": {
                    "business_trace_passed": passed,
                    "business_trace_id": "notification-settings-e2e",
                    "chain": [
                        "natural_language_gui_case",
                        "gui_agent_visual_execution",
                        "backend_api_state_query",
                        "unified_pass_fail_decision",
                    ],
                },
                "base_url": base_url,
                "tasks": {"gui": gui_task.task_id, "backend": backend_task.task_id},
                "results": ordered_results,
                "unified_decision": "PASS" if passed else "FAIL",
            }

    def review_queue_snapshot(self) -> Dict[str, Any]:
        pending = [item for item in self.review_queue if item["review_status"] == "PENDING_REVIEW"]
        resolved = [item for item in self.review_queue if item["review_status"] == "RESOLVED"]
        return {
            "pending_count": len(pending),
            "resolved_count": len(resolved),
            "items": list(self.review_queue),
        }

    def resolve_review_item(self, review_id: str, final_status: str, reviewer: str, note: str) -> Dict[str, Any]:
        if review_id not in self._review_index:
            raise ValueError(f"review item not found: {review_id}")
        item = self._review_index[review_id]
        item.update(
            {
                "review_status": "RESOLVED",
                "final_status": final_status,
                "reviewer": reviewer,
                "review_note": note,
                "resolved_at": time(),
            }
        )
        return dict(item)

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

    def run_external_acceptance_demo(self) -> Dict[str, Any]:
        return ExternalAcceptanceRunner(self).run()

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

    def _backend_api_requests_from_text(self, base_url: str, text: str) -> List[Dict[str, Any]]:
        normalized_text = text.lower()
        requests = [
            {
                "name": "health_check",
                "method": "GET",
                "url": f"{base_url}/health",
                "expected_status": 200,
                "expected_json": {"status": "ok", "service": "yuanbao-demo-web"},
            }
        ]
        if any(keyword in text.lower() for keyword in ["checkout", "order", "submitted", "下单", "订单"]):
            requests.append(
                {
                    "name": "checkout_status",
                    "method": "GET",
                    "url": f"{base_url}/checkout",
                    "expected_status": 200,
                    "expected_json": {"status": "submitted"},
                }
            )
        if any(keyword in normalized_text for keyword in ["notification", "通知", "开关", "notification_enabled"]):
            requests.append(
                {
                    "name": "notification_state",
                    "method": "GET",
                    "url": f"{base_url}/api/settings/notification",
                    "expected_status": 200,
                    "expected_json": {"status": "ok", "notification_enabled": False},
                }
            )
        return requests

    def _automation_counts_for_results(self, results: List[Dict[str, Any]]) -> Dict[str, int]:
        task_by_id = {task.task_id: task for task in self.scheduler.submitted_tasks}
        counts: Dict[str, int] = {}
        for result in results:
            task = task_by_id.get(result["task_id"])
            automation_type = task.case.automation_type.value if task else "UNKNOWN"
            counts[automation_type] = counts.get(automation_type, 0) + 1
        return counts

    def _enqueue_latest_unknown_reviews(self, results) -> None:
        latest_by_task = {}
        for result in results:
            latest_by_task[result.task_id] = result
        for result in latest_by_task.values():
            self._enqueue_review_if_unknown(result)

    def _enqueue_review_if_unknown(self, result) -> None:
        if result.status != ResultStatus.UNKNOWN:
            return
        review_id = f"review-{result.task_id}"
        if review_id in self._review_index:
            return
        item = {
            "review_id": review_id,
            "review_status": "PENDING_REVIEW",
            "task_id": result.task_id,
            "case_id": result.case_id,
            "reason": result.reason,
            "trace_id": result.trace.trace_id,
            "screenshots": result.trace.screenshots,
            "actions": result.trace.actions,
            "confidence": result.confidence,
            "created_at": time(),
            "suggested_action": "人工查看截图、trace 和原因后确认最终 PASS / FAIL / UNKNOWN",
        }
        self.review_queue.append(item)
        self._review_index[review_id] = item

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
