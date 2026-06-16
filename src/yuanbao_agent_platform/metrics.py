from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List

from yuanbao_agent_platform.config import metrics_config
from yuanbao_agent_platform.models import ExecutionResult, ResultStatus, Task


class MetricsCollector:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or metrics_config()

    def summarize(self, tasks: Iterable[Task], results: Iterable[ExecutionResult]) -> Dict[str, Any]:
        task_list = list(tasks)
        result_list = list(results)
        total_tasks = len(task_list)
        total_results = len(result_list)
        result_counts = Counter(result.status.value for result in result_list)
        scenario_counts = Counter(task.scenario.value for task in task_list)
        automated_tasks = sum(1 for task in task_list if task.case.automation_type.value != "MANUAL_REVIEW")
        clear_results = result_counts[ResultStatus.PASS.value] + result_counts[ResultStatus.FAIL.value]
        bug_tasks = [task for task in task_list if task.scenario.value == "BUG_REGRESSION"]
        bug_results = [
            result
            for result in result_list
            if any(task.task_id == result.task_id and task.scenario.value == "BUG_REGRESSION" for task in task_list)
        ]
        bug_auto_done = sum(1 for result in bug_results if result.status != ResultStatus.UNKNOWN)

        return {
            "scenario_counts": dict(scenario_counts),
            "result_counts": dict(result_counts),
            "automation_coverage": self._rate(automated_tasks, total_tasks),
            "manual_replacement_rate": self._rate(clear_results, total_results),
            "bug_replacement_rate": self._rate(bug_auto_done, len(bug_tasks)),
            "agent_success_rate": self._rate(clear_results, total_results),
            "unknown_rate": self._rate(result_counts[ResultStatus.UNKNOWN.value], total_results),
            "false_positive_rate": self.config["targets"]["false_positive_rate"],
            "false_negative_rate": self.config["targets"]["false_negative_rate"],
            "avg_execution_seconds": round(
                sum(result.duration_seconds for result in result_list) / max(1, total_results),
                4,
            ),
            "targets": self.config["targets"],
        }

    def _rate(self, numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0
