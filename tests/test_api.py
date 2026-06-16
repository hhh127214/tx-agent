import unittest

from yuanbao_agent_platform.api import YuanbaoApi


class YuanbaoApiTest(unittest.TestCase):
    def test_health_endpoint(self):
        status, body = YuanbaoApi().handle("GET", "/health", {})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_convert_endpoint(self):
        status, body = YuanbaoApi().handle(
            "POST",
            "/cases/convert",
            {
                "case_id": "case-api-001",
                "text": "登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["agent_plan"]["context"]["execution_mode"], "VISION_BASED_GUI_AGENT")

    def test_policy_and_metrics_endpoints(self):
        api = YuanbaoApi()

        status, policy = api.handle("GET", "/scheduler/policy", {})
        self.assertEqual(status, 200)
        self.assertIn("BUG_REGRESSION", policy)
        self.assertIn("scale", policy)

        status, metrics = api.handle("GET", "/metrics", {})
        self.assertEqual(status, 200)
        self.assertIn("automation_coverage", metrics)

        status, integrations = api.handle("GET", "/integrations", {})
        self.assertEqual(status, 200)
        self.assertIn("bug_system", integrations["config"])

        status, adapters = api.handle("GET", "/adapters/health", {})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(adapters["connected_system_count"], 2)

        status, report = api.handle("GET", "/acceptance/report", {})
        self.assertEqual(status, 200)
        self.assertTrue(report["summary"]["mvp_acceptance_passed"])

    def test_webhook_endpoints(self):
        api = YuanbaoApi()

        status, bug_body = api.handle(
            "POST",
            "/webhooks/bug-status-changed",
            {
                "bug_id": "BUG-1024",
                "title": "关闭通知开关后重新进入设置页仍显示开启",
                "status": "待回归",
                "severity": "P1",
                "version": "8.1.1",
                "steps": ["登录账号", "进入我的页面", "点击设置", "关闭通知开关", "退出设置页后重新进入"],
                "expected": "通知开关保持关闭",
                "actual": "通知开关重新变为开启",
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(bug_body["trigger"], "bug_status_changed")

        status, ci_body = api.handle(
            "POST",
            "/webhooks/ci-finished",
            {
                "pipeline_id": "pipeline-001",
                "commit_sha": "abc123",
                "artifact": "yuanbao-debug.apk",
                "run_immediately": True,
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(ci_body["trigger"], "ci_finished")
        self.assertTrue(ci_body["results"])

    def test_ci_webhook_is_idempotent(self):
        api = YuanbaoApi()
        payload = {
            "pipeline_id": "pipeline-idempotent",
            "commit_sha": "abc123",
            "artifact": "yuanbao-debug.apk",
            "run_immediately": True,
        }

        first_status, first_body = api.handle("POST", "/webhooks/ci-finished", payload)
        second_status, second_body = api.handle("POST", "/webhooks/ci-finished", payload)

        self.assertEqual(first_status, 202)
        self.assertEqual(second_status, 200)
        self.assertFalse(first_body["idempotent"])
        self.assertTrue(second_body["idempotent"])
        self.assertEqual(first_body["task"]["task_id"], second_body["task"]["task_id"])
        self.assertEqual(len(api._platform.scheduler.submitted_tasks), 1)

    def test_large_scale_endpoint(self):
        status, body = YuanbaoApi().handle(
            "POST",
            "/demo/large-scale",
            {"total": 100, "max_workers": 8},
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["requested_tasks"], 100)
        self.assertEqual(body["scheduler_run_summary"]["mode"], "thread_pool_worker")


if __name__ == "__main__":
    unittest.main()
