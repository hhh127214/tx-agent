import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib import request

from yuanbao_agent_platform.api import YuanbaoApi
from yuanbao_agent_platform.demo_web import run_demo_web_server
from yuanbao_agent_platform.external_acceptance import ExternalAcceptanceRunner
from yuanbao_agent_platform.external_adapters import ExternalAdapterRegistry, GitHubActionsAdapter, GitHubIssuesAdapter, MarkdownPRDAdapter
from yuanbao_agent_platform.platform import YuanbaoTestingPlatform


class FakeGitHubIssuesAdapter:
    system_name = "github_issues"
    mode = "github_api"

    def __init__(self):
        self.written_issue_number = None

    def fetch_waiting_regression(self):
        return [
            {
                "bug_id": "GH-42",
                "number": 42,
                "title": "关闭通知开关后重新进入设置页仍显示开启",
                "body": "复现步骤：登录，进入设置，关闭通知。",
                "url": "https://github.com/example/repo/issues/42",
            }
        ]

    def write_regression_result(self, issue_number, status, payload):
        self.written_issue_number = issue_number
        return {"system": self.system_name, "mode": self.mode, "external_id": f"example/repo#{issue_number}", "status": status}

    def health_check(self):
        return {"system": self.system_name, "mode": self.mode, "healthy": True, "calls": 1}


class ExternalAcceptanceTest(unittest.TestCase):
    def test_demo_web_is_a_real_http_business_system(self):
        with run_demo_web_server() as base_url:
            with request.urlopen(f"{base_url}/health", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("yuanbao-demo-web", response.read().decode("utf-8"))

            with request.urlopen(f"{base_url}/search?q=Yuanbao", timeout=5) as response:
                page = response.read().decode("utf-8")
                self.assertIn("Yuanbao", page)
                self.assertIn("加入购物车", page)

    def test_external_substitute_acceptance_runs_end_to_end(self):
        with TemporaryDirectory() as tmpdir:
            platform = YuanbaoTestingPlatform(db_path=str(Path(tmpdir) / "platform.db"))
            report = platform.run_external_acceptance_demo()

            self.assertTrue(report["summary"]["external_substitute_acceptance_passed"])
            self.assertFalse(report["summary"]["strict_yuanbao_internal_acceptance_passed"])
            self.assertTrue(report["real_gui_system"]["passed"])
            self.assertEqual(report["external_systems"]["github_actions"]["system"], "github_actions")
            self.assertEqual(report["external_systems"]["github_issues_writeback"]["system"], "github_issues")
            self.assertEqual(report["external_systems"]["markdown_prd"]["prd_id"], "external_demo_prd")
            self.assertGreaterEqual(report["scenario_counts"]["INTEGRATION_BATCH"], 1)
            self.assertGreaterEqual(report["scenario_counts"]["DEV_SELF_TEST"], 1)
            self.assertGreaterEqual(report["scenario_counts"]["REQUIREMENT_TEST"], 1)
            self.assertGreaterEqual(report["scenario_counts"]["BUG_REGRESSION"], 1)

    def test_external_adapters_expose_real_api_boundaries_without_tokens(self):
        registry = ExternalAdapterRegistry(
            github_actions=GitHubActionsAdapter(repo="", token=""),
            github_issues=GitHubIssuesAdapter(repo="", token=""),
            markdown_prd=MarkdownPRDAdapter(),
        )

        health = registry.health()

        self.assertEqual(health["mode"], "external_substitute_adapters")
        modes = {adapter["system"]: adapter["mode"] for adapter in health["adapters"]}
        self.assertEqual(modes["github_actions"], "dry_run_payload")
        self.assertEqual(modes["github_issues"], "dry_run_payload")
        self.assertEqual(modes["markdown_prd"], "local_file_real_prd")

    def test_external_acceptance_writes_back_to_fetched_issue_number(self):
        with TemporaryDirectory() as tmpdir:
            fake_issues = FakeGitHubIssuesAdapter()
            adapters = ExternalAdapterRegistry(
                github_actions=GitHubActionsAdapter(repo="", token=""),
                github_issues=fake_issues,
                markdown_prd=MarkdownPRDAdapter(),
            )
            platform = YuanbaoTestingPlatform(db_path=str(Path(tmpdir) / "platform.db"))

            report = ExternalAcceptanceRunner(platform, adapters).run()

            self.assertTrue(report["summary"]["external_substitute_acceptance_passed"])
            self.assertEqual(fake_issues.written_issue_number, 42)
            self.assertEqual(report["external_systems"]["github_issue"]["number"], 42)

    def test_external_acceptance_api_endpoint(self):
        with TemporaryDirectory() as tmpdir:
            api = YuanbaoApi(YuanbaoTestingPlatform(db_path=str(Path(tmpdir) / "platform.db")))
            status, body = api.handle("GET", "/acceptance/external-substitute", {})

            self.assertEqual(status, 200)
            self.assertTrue(body["summary"]["external_substitute_acceptance_passed"])


if __name__ == "__main__":
    unittest.main()
