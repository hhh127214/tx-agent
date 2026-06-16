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


if __name__ == "__main__":
    unittest.main()
