from __future__ import annotations

import json
from typing import Any, Dict
from urllib import parse, request

from yuanbao_agent_platform.demo_web import run_demo_web_server
from yuanbao_agent_platform.external_adapters import ExternalAdapterRegistry
from yuanbao_agent_platform.models import Scenario, TriggerType


class ExternalAcceptanceRunner:
    def __init__(self, platform, adapters: ExternalAdapterRegistry = None):
        self._platform = platform
        self._adapters = adapters or ExternalAdapterRegistry()

    def run(self) -> Dict[str, Any]:
        with run_demo_web_server() as base_url:
            web_probe = self._probe_demo_web(base_url)
            integration_task = self._platform.submit_manual_case(
                Scenario.INTEGRATION_BATCH,
                "external-web-search-001",
                f"打开真实Web系统 {base_url}，登录后搜索 Yuanbao，验证搜索结果展示并可加入购物车。",
                TriggerType.MANUAL,
                metadata={"external_business_system": "local_demo_web", "base_url": base_url},
            )
            dev_self_test = self._adapters.github_actions.trigger_agent_self_test(
                ref="master",
                inputs={"scenario": "dev_self_test", "target_url": base_url},
            )
            dev_task = self._platform.submit_manual_case(
                Scenario.DEV_SELF_TEST,
                "external-github-actions-001",
                "GitHub Actions 触发后，在真实Web Demo上执行登录和搜索冒烟验证。",
                TriggerType.CI,
                metadata={
                    "external_ci_system": "github_actions",
                    "base_url": base_url,
                    "ci_blocking": True,
                    "writeback_target": "ci_cd",
                },
            )
            prd = self._adapters.markdown_prd.fetch_prd("external_demo_prd")
            test_points = self._platform.generate_prd_test_points(prd["prd_id"], prd["prd_text"])
            issues = self._adapters.github_issues.fetch_waiting_regression()
            bug_task = self._platform.submit_manual_case(
                Scenario.BUG_REGRESSION,
                "external-github-issue-001",
                "根据 GitHub Issue 复现步骤：登录 Demo Web，进入设置，关闭通知开关，重新进入设置页，验证状态保持关闭。",
                TriggerType.WEBHOOK,
                metadata={
                    "external_bug_system": "github_issues",
                    "bug_id": issues[0]["bug_id"],
                    "writeback_target": "bug_system",
                },
            )
            requirement_task = self._platform.submit_manual_case(
                Scenario.REQUIREMENT_TEST,
                "external-markdown-prd-001",
                "根据 Markdown PRD 验证 Demo Web 搜索、加入购物车和通知开关状态保持。",
                TriggerType.WEBHOOK,
                metadata={"external_requirement_system": "markdown_prd", "requirement_id": prd["prd_id"]},
            )
            results = self._platform.run_queued_tasks(max_workers=4)
            bug_result = next(item for item in results if item["task_id"] == bug_task.task_id)
            issue_writeback = self._adapters.github_issues.write_regression_result(
                issue_number=1,
                status=bug_result["status"],
                payload={
                    "reason": bug_result["reason"],
                    "trace_id": bug_result["trace"]["trace_id"],
                },
            )
            scenario_counts = self._platform.metrics.summarize(
                self._platform.scheduler.submitted_tasks,
                self._platform.scheduler.results,
            )["scenario_counts"]
            return {
                "summary": {
                    "external_substitute_acceptance_passed": self._passed(web_probe, scenario_counts, dev_self_test, issue_writeback),
                    "strict_yuanbao_internal_acceptance_passed": False,
                    "reason": "使用本地真实Web系统、GitHub Actions/GitHub Issues适配边界与Markdown PRD完成外部可验证替代闭环；真实元宝内网接入仍需公司权限。",
                },
                "real_gui_system": web_probe,
                "external_systems": {
                    "github_actions": dev_self_test,
                    "github_issues_writeback": issue_writeback,
                    "markdown_prd": {"prd_id": prd["prd_id"], "path": prd["path"]},
                    "adapter_health": self._adapters.health(),
                },
                "tasks": {
                    "integration_batch": integration_task.task_id,
                    "dev_self_test": dev_task.task_id,
                    "bug_regression": bug_task.task_id,
                    "requirement_test": requirement_task.task_id,
                },
                "scenario_counts": scenario_counts,
                "results": results,
                "generated_test_points": test_points,
            }

    def _probe_demo_web(self, base_url: str) -> Dict[str, Any]:
        health = self._get_json(f"{base_url}/health")
        login_page = self._get_text(f"{base_url}/login")
        search_page = self._get_text(f"{base_url}/search?{parse.urlencode({'q': 'Yuanbao'})}")
        checkout = self._get_json(f"{base_url}/checkout")
        return {
            "base_url": base_url,
            "health": health,
            "login_page_contains": "元宝 Demo 登录" in login_page,
            "search_result_contains": "Yuanbao" in search_page,
            "checkout_status": checkout.get("status"),
            "passed": health.get("status") == "ok" and "Yuanbao" in search_page,
        }

    def _get_text(self, url: str) -> str:
        with request.urlopen(url, timeout=5) as response:
            return response.read().decode("utf-8")

    def _get_json(self, url: str) -> Dict[str, Any]:
        return json.loads(self._get_text(url))

    def _passed(self, web_probe: Dict[str, Any], scenario_counts: Dict[str, int], dev_self_test: Dict[str, Any], issue_writeback: Dict[str, Any]) -> bool:
        return (
            bool(web_probe["passed"])
            and scenario_counts.get("INTEGRATION_BATCH", 0) >= 1
            and scenario_counts.get("DEV_SELF_TEST", 0) >= 1
            and scenario_counts.get("REQUIREMENT_TEST", 0) >= 1
            and scenario_counts.get("BUG_REGRESSION", 0) >= 1
            and dev_self_test["system"] == "github_actions"
            and issue_writeback["system"] == "github_issues"
        )
