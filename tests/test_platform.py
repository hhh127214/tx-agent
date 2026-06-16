import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from yuanbao_agent_platform.models import BugReport, ResultStatus, Scenario, TaskStatus, TriggerType
from yuanbao_agent_platform.platform import YuanbaoTestingPlatform
from yuanbao_agent_platform.vlm import MockVisionAgentClient, OpenAICompatibleVisionAgentClient


class YuanbaoTestingPlatformTest(unittest.TestCase):
    def setUp(self):
        self.platform = YuanbaoTestingPlatform()

    def test_manual_case_conversion_uses_llm_planned_vision_plan(self):
        converted = self.platform.convert_manual_case(
            "case-001",
            "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
        )

        plan = converted["agent_plan"]
        self.assertEqual(plan["context"]["execution_mode"], "VISION_BASED_GUI_AGENT")
        self.assertEqual(plan["context"]["planning_mode"], "LLM_PLANNED")
        self.assertEqual(converted["ir"]["planner_provider"], "mock_semantic_llm")
        self.assertEqual(converted["ir"]["prompt_version"], "case-planning-v2")
        serialized = str(plan)
        self.assertNotIn("XPath", serialized)
        self.assertNotIn("ResourceId", serialized)
        self.assertIn("通知/消息提醒开关", serialized)

    def test_llm_mock_handles_fuzzy_expression_without_exact_notification_keyword(self):
        converted = self.platform.convert_manual_case(
            "case-fuzzy-001",
            "进入个人中心，把那个叮叮咚咚老打扰我的功能禁用掉，再看看重进后是不是还关着。",
        )

        ir = converted["ir"]
        concepts = ir["extracted_entities"]["concepts"]
        self.assertIn("notification", concepts)
        self.assertIn("disable", concepts)
        self.assertIn("persist", concepts)
        self.assertIn("通知/消息提醒开关", str(converted["agent_plan"]))
        self.assertFalse(ir["need_human_review"])

    def test_scheduler_prioritizes_dev_self_test(self):
        integration = self.platform.submit_manual_case(
            Scenario.INTEGRATION_BATCH,
            "case-integration",
            "登录后进入我的页面，点击设置。",
        )
        dev = self.platform.submit_manual_case(
            Scenario.DEV_SELF_TEST,
            "case-dev",
            "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
            TriggerType.CI,
        )

        results = self.platform.run_queued_tasks(max_workers=1)
        self.assertEqual(results[0]["task_id"], dev.task_id)
        self.assertEqual(results[1]["task_id"], integration.task_id)

    def test_bug_regression_returns_three_state_result(self):
        result = self.platform.run_bug_regression(
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

        self.assertIn(result.result, {ResultStatus.PASS, ResultStatus.FAIL, ResultStatus.UNKNOWN})
        self.assertEqual(result.result, ResultStatus.PASS)
        self.assertFalse(result.need_human_review)

    def test_prd_generation_uses_llm_planner_and_outputs_structured_test_points(self):
        result = self.platform.generate_prd_test_points(
            "PRD-001",
            "用户可在设置页关闭通知开关。用户重新登录、重启 App 或切换网络后状态应保持不变。若接口保存失败，应提示稍后重试，并保持原状态。",
        )

        self.assertEqual(result["feature"], "设置页通知/消息提醒开关")
        self.assertEqual(result["metadata"]["planner_provider"], "mock_semantic_llm")
        self.assertEqual(result["metadata"]["prompt_version"], "prd-test-design-v2")
        self.assertGreaterEqual(len(result["test_points"]), 3)
        self.assertIn("retrieved_knowledge", result)
        automation_types = {point["automation_type"] for point in result["test_points"]}
        self.assertIn("GUI_AGENT", automation_types)
        self.assertIn("BACKEND_AUTOMATION", automation_types)

    def test_vlm_status_uses_confidence_and_visual_mismatch_not_keywords(self):
        with TemporaryDirectory() as tmpdir:
            client = MockVisionAgentClient(artifact_root=str(Path(tmpdir) / "screenshots"))
            plan = self.platform.case_converter.to_agent_plan(
                self.platform.case_converter.convert("case-vlm-001", "登录后进入我的页面，点击设置，验证状态。")
            )

            fail_run = client.run_plan(
                plan,
                {"task_id": "task-vlm-artifact", "visual_mismatch_count": 1, "vision_confidence": 0.95},
            )
            unknown_run = client.run_plan(plan, {"task_id": "task-vlm-unknown", "vision_confidence": 0.4})

            self.assertEqual(fail_run.status, ResultStatus.FAIL)
            self.assertEqual(unknown_run.status, ResultStatus.UNKNOWN)
            self.assertTrue(fail_run.screenshots)
            self.assertTrue(Path(fail_run.screenshots[0]).exists())
            self.assertIn("task-vlm-artifact", fail_run.screenshots[0])

    def test_openai_compatible_vlm_client_is_explicit_integration_boundary(self):
        client = OpenAICompatibleVisionAgentClient(
            base_url="https://internal-vlm.example.test/v1",
            model="vision-gui-agent",
        )
        plan = self.platform.case_converter.to_agent_plan(
            self.platform.case_converter.convert("case-vlm-boundary", "点击设置并验证状态。")
        )

        with self.assertRaises(NotImplementedError):
            client.run_plan(plan, {})

    def test_demo_exposes_platform_level_policy_writeback_and_metrics(self):
        result = self.platform.run_demo()

        scenarios = {example["scenario"] for example in result["scenario_examples"]}
        self.assertIn("INTEGRATION_BATCH", scenarios)
        self.assertIn("DEV_SELF_TEST", scenarios)
        self.assertIn("REQUIREMENT_TEST", scenarios)
        self.assertIn("BUG_REGRESSION", result["metrics"]["scenario_counts"])
        self.assertEqual(result["scheduler_run_summary"]["mode"], "thread_pool_worker")
        self.assertGreaterEqual(result["scheduler_run_summary"]["max_workers"], 2)
        self.assertIn("bug_replacement_rate", result["metrics"])
        self.assertIn("false_positive_rate", result["metrics"])
        self.assertIn("false_negative_rate", result["metrics"])
        self.assertGreaterEqual(len(result["writebacks"]), 4)

        targets = {record["target"] for record in result["writebacks"]}
        self.assertIn("bug_system", targets)
        self.assertIn("ci_cd", targets)
        self.assertIn("requirement_system", targets)
        self.assertIn("report_center", targets)

    def test_large_scale_demo_uses_worker_pool_and_quarantine(self):
        result = self.platform.run_large_scale_demo(total=200, max_workers=16)

        self.assertEqual(result["requested_tasks"], 200)
        self.assertEqual(result["scheduler_run_summary"]["mode"], "thread_pool_worker")
        self.assertEqual(result["scheduler_run_summary"]["max_workers"], 16)
        self.assertGreaterEqual(result["produced_results"], 200)
        self.assertIn("BUG_REGRESSION", result["metrics"]["scenario_counts"])
        self.assertTrue(result["quarantine"])

    def test_acceptance_report_covers_new_acceptance_requirements(self):
        report = self.platform.run_acceptance_report()

        self.assertTrue(report["summary"]["mvp_acceptance_passed"])
        self.assertFalse(report["summary"]["strict_real_internal_acceptance_passed"])
        business_results = report["requirement_1_four_directions"]["business_results"]
        self.assertEqual(len(business_results), 4)
        self.assertTrue(all(item["mvp_passed"] for item in business_results))

        integrations = report["requirement_2_system_integrations"]
        self.assertGreaterEqual(integrations["implemented_adapter_count"], 2)
        self.assertIn("ci_cd", integrations["implemented_adapters"])
        self.assertIn("bug_system", integrations["implemented_adapters"])

    def test_sqlite_persists_tasks_results_writebacks_and_acceptance_reports(self):
        with TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "platform.db")
            platform = YuanbaoTestingPlatform(db_path=db_path)
            platform.run_demo()
            report = platform.run_acceptance_report()
            stats = platform.store.stats()

            self.assertGreaterEqual(stats["tasks"], 5)
            self.assertGreaterEqual(stats["execution_results"], 5)
            self.assertGreaterEqual(stats["writebacks"], 5)
            self.assertGreaterEqual(stats["acceptance_reports"], 1)
            self.assertIn("storage", report)

    def test_scheduler_explicitly_recovers_unfinished_tasks_from_sqlite(self):
        with TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "platform.db")
            first_platform = YuanbaoTestingPlatform(db_path=db_path)
            submitted = first_platform.submit_manual_case(
                Scenario.DEV_SELF_TEST,
                "case-recover-001",
                "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
                TriggerType.CI,
            )
            submitted.status = TaskStatus.RUNNING
            first_platform.store.save_task(submitted)

            cold_platform = YuanbaoTestingPlatform(db_path=db_path)
            self.assertEqual(sum(cold_platform.scheduler.queue_snapshot().values()), 0)

            recovery = cold_platform.recover_pending_tasks()
            self.assertEqual(recovery["loaded_from_store"], 1)
            self.assertEqual(recovery["recovered"], 1)
            self.assertEqual(sum(recovery["queue_snapshot"].values()), 1)

            recovered_task = cold_platform.scheduler.submitted_tasks[0]
            self.assertTrue(recovered_task.metadata["recovered_from_store"])
            self.assertTrue(recovered_task.metadata["recovered_from_interrupted_run"])

            results = cold_platform.run_queued_tasks(max_workers=1)
            self.assertEqual(results[0]["task_id"], submitted.task_id)
            self.assertEqual(results[0]["status"], ResultStatus.PASS.value)

            finished_platform = YuanbaoTestingPlatform(db_path=db_path)
            finished_recovery = finished_platform.recover_pending_tasks()
            self.assertEqual(finished_recovery["loaded_from_store"], 0)
            self.assertEqual(finished_recovery["recovered"], 0)


if __name__ == "__main__":
    unittest.main()
