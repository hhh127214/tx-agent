import unittest

from yuanbao_agent_platform.models import BugReport, ResultStatus, Scenario, TriggerType
from yuanbao_agent_platform.platform import YuanbaoTestingPlatform


class YuanbaoTestingPlatformTest(unittest.TestCase):
    def setUp(self):
        self.platform = YuanbaoTestingPlatform()

    def test_manual_case_conversion_uses_vision_plan(self):
        converted = self.platform.convert_manual_case(
            "case-001",
            "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
        )

        plan = converted["agent_plan"]
        self.assertEqual(plan["context"]["execution_mode"], "VISION_BASED_GUI_AGENT")
        self.assertIn("selector_policy", plan["context"])
        self.assertEqual(plan["context"]["planning_mode"], "LLM_PLANNED")
        self.assertEqual(converted["ir"]["planner_provider"], "mock_llm")
        serialized = str(plan)
        self.assertNotIn("XPath", serialized)
        self.assertNotIn("ResourceId", serialized)
        self.assertIn("通知开关", serialized)

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

        results = self.platform.run_queued_tasks()
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

    def test_prd_generation_outputs_structured_test_points(self):
        result = self.platform.generate_prd_test_points(
            "PRD-001",
            "用户可在设置页关闭通知开关。用户重新登录、重启 App 或切换网络后状态应保持不变。若接口保存失败，应提示稍后重试，并保持原状态。",
        )

        self.assertEqual(result["feature"], "设置页通知开关")
        self.assertGreaterEqual(len(result["test_points"]), 3)
        self.assertIn("retrieved_knowledge", result)
        automation_types = {point["automation_type"] for point in result["test_points"]}
        self.assertIn("GUI_AGENT", automation_types)
        self.assertIn("BACKEND_AUTOMATION", automation_types)

    def test_demo_exposes_platform_level_policy_writeback_and_metrics(self):
        result = self.platform.run_demo()

        scenarios = {example["scenario"] for example in result["scenario_examples"]}
        self.assertIn("INTEGRATION_BATCH", scenarios)
        self.assertIn("DEV_SELF_TEST", scenarios)
        self.assertIn("REQUIREMENT_TEST", scenarios)

        self.assertIn("BUG_REGRESSION", result["metrics"]["scenario_counts"])
        self.assertIn("scheduler_policy", result)
        self.assertIn("scale", result["scheduler_policy"])
        self.assertIn("metrics", result)
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

        writeback_targets = {item["writeback_target"] for item in result["queued_results"]}
        self.assertNotIn(None, writeback_targets)

    def test_large_scale_demo_uses_worker_pool_and_quarantine(self):
        result = self.platform.run_large_scale_demo(total=200, max_workers=16)

        self.assertEqual(result["requested_tasks"], 200)
        self.assertEqual(result["scheduler_run_summary"]["mode"], "thread_pool_worker")
        self.assertEqual(result["scheduler_run_summary"]["max_workers"], 16)
        self.assertGreaterEqual(result["produced_results"], 200)
        self.assertIn("BUG_REGRESSION", result["metrics"]["scenario_counts"])
        self.assertTrue(result["quarantine"])


if __name__ == "__main__":
    unittest.main()
