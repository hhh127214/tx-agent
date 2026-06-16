from __future__ import annotations

from typing import Any, Dict, List

from yuanbao_agent_platform.config import load_config


class AcceptanceReporter:
    def __init__(self, platform):
        self._platform = platform
        self._business_cases = load_config("business_acceptance.json")["business_cases"]

    def build_report(self) -> Dict[str, Any]:
        demo = self._platform.run_demo()
        scenario_counts = demo["metrics"]["scenario_counts"]
        writeback_targets = {record["target"] for record in demo["writebacks"]}
        business_results = self._business_results(scenario_counts, writeback_targets)
        adapter_health = self._platform.adapters.health()
        integrated_systems = [
            adapter["system"]
            for adapter in adapter_health["adapters"]
            if adapter["healthy"]
        ]
        return {
            "summary": {
                "mvp_acceptance_passed": all(item["mvp_passed"] for item in business_results) and len(integrated_systems) >= 2,
                "strict_real_internal_acceptance_passed": False,
                "reason": "当前工程完成可运行适配器与端到端链路；真实公司内网系统对接需要 endpoint、鉴权、字段映射和测试账号。",
            },
            "requirement_1_four_directions": {
                "required": ["INTEGRATION_BATCH", "DEV_SELF_TEST", "REQUIREMENT_TEST", "BUG_REGRESSION"],
                "business_results": business_results,
                "scenario_counts": scenario_counts,
            },
            "requirement_2_system_integrations": {
                "required_min_count": 2,
                "implemented_adapter_count": len(integrated_systems),
                "implemented_adapters": integrated_systems,
                "adapter_health": adapter_health,
            },
            "evidence": {
                "scheduler_run_summary": demo["scheduler_run_summary"],
                "metrics": demo["metrics"],
                "writeback_targets": sorted(writeback_targets),
                "sample_writebacks": demo["writebacks"][:4],
            },
            "production_gap": [
                "将 InMemoryCICDAdapter 替换为公司 CI/CD REST/Webhook 客户端",
                "将 InMemoryBugSystemAdapter 替换为 TAPD/Jira/内部缺陷系统客户端",
                "将 InMemoryRequirementAdapter 替换为需求管理系统客户端",
                "配置真实鉴权、字段映射、幂等 key、测试账号和回写权限"
            ],
        }

    def _business_results(self, scenario_counts: Dict[str, int], writeback_targets: set) -> List[Dict[str, Any]]:
        results = []
        for case in self._business_cases:
            scenario_ok = scenario_counts.get(case["direction"], 0) >= 1
            writeback_ok = case["expected_writeback"] in writeback_targets
            results.append({
                **case,
                "scenario_executed": scenario_ok,
                "writeback_observed": writeback_ok,
                "mvp_passed": scenario_ok and writeback_ok,
                "real_business_note": "当前为元宝设置域样例业务；真实业务验收需替换为导师指定业务线和环境。",
            })
        return results
