from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Deque, Dict, List, Optional
from uuid import uuid4

from yuanbao_agent_platform.config import scheduler_policy
from yuanbao_agent_platform.executors import ExecutionRouter, ResultAnalyzer
from yuanbao_agent_platform.models import ExecutionJob, ExecutionResult, ExecutionTrace, ResultStatus, Scenario, Task, TaskStatus


class ResourceManager:
    def __init__(self, devices: int = 2, containers: int = 2):
        self._devices_total = devices
        self._containers_total = containers
        self._devices_busy = 0
        self._containers_busy = 0
        self._lock = Lock()

    def allocate(self, task: Task) -> Optional[Dict[str, str]]:
        with self._lock:
            needs_container = task.case.automation_type.value == "BACKEND_AUTOMATION"
            if needs_container:
                if self._containers_busy >= self._containers_total:
                    return None
                self._containers_busy += 1
                return {"type": "container", "id": f"container-{self._containers_busy}"}

            if self._devices_busy >= self._devices_total:
                return None
            self._devices_busy += 1
            return {"type": "device", "id": f"device-{self._devices_busy}"}

    def release(self, resource: Dict[str, str]) -> None:
        with self._lock:
            if resource["type"] == "container":
                self._containers_busy = max(0, self._containers_busy - 1)
            else:
                self._devices_busy = max(0, self._devices_busy - 1)


class QuarantineManager:
    def __init__(self, failure_threshold: int = 2):
        self._failure_threshold = failure_threshold
        self._case_failures: Dict[str, int] = defaultdict(int)
        self._blocked: Dict[str, str] = {}
        self._lock = Lock()

    def is_blocked(self, case_id: str) -> bool:
        with self._lock:
            return case_id in self._blocked

    def record(self, result: ExecutionResult) -> None:
        with self._lock:
            if result.status in {ResultStatus.PASS, ResultStatus.SKIPPED}:
                self._case_failures[result.case_id] = 0
                return
            if result.status in {ResultStatus.FAIL, ResultStatus.UNKNOWN, ResultStatus.BLOCKED}:
                self._case_failures[result.case_id] += 1
                if self._case_failures[result.case_id] >= self._failure_threshold:
                    self._blocked[result.case_id] = result.reason

    def reason(self, case_id: str) -> Optional[str]:
        with self._lock:
            return self._blocked.get(case_id)

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._blocked)


class PriorityPolicy:
    def __init__(self, policy: Dict[str, Dict] = None):
        self.policy = policy or scheduler_policy()

    def apply(self, task: Task) -> Task:
        scenario_policy = self.policy[task.scenario.value]
        task.priority = scenario_policy["priority"]
        if task.metadata.get("severity") in {"P0", "P1"}:
            task.priority += 15
        if task.metadata.get("ci_blocking"):
            task.priority += 10
        task.timeout_seconds = scenario_policy["timeout_seconds"]
        task.max_retry = scenario_policy["max_retry"]
        task.metadata["scheduler_policy"] = {
            "resource_quota": scenario_policy["resource_quota"],
            "concurrency": scenario_policy["concurrency"],
            "allow_queue": scenario_policy["allow_queue"],
            "allow_preempt": scenario_policy["allow_preempt"],
            "execution_window": scenario_policy["execution_window"],
            "strategy": scenario_policy["strategy"],
        }
        task.metadata.setdefault("writeback_target", scenario_policy["writeback_target"])
        return task


class ExecutionScheduler:
    def __init__(
        self,
        router: ExecutionRouter,
        resource_manager: ResourceManager,
        quarantine_manager: QuarantineManager,
        analyzer: ResultAnalyzer,
    ):
        self._router = router
        self._resources = resource_manager
        self._quarantine = quarantine_manager
        self._analyzer = analyzer
        self._policy = PriorityPolicy()
        self._queues: Dict[Scenario, Deque[Task]] = {scenario: deque() for scenario in Scenario}
        self._queue_lock = Lock()
        self.results: List[ExecutionResult] = []
        self.submitted_tasks: List[Task] = []
        self.last_run_summary: Dict[str, int] = {}

    def submit(self, task: Task) -> Task:
        task = self._policy.apply(task)
        with self._queue_lock:
            self._queues[task.scenario].append(task)
            self.submitted_tasks.append(task)
        return task

    def run_until_idle(self, max_iterations: int = 100) -> List[ExecutionResult]:
        produced: List[ExecutionResult] = []
        iterations = 0
        while iterations < max_iterations:
            iterations += 1
            task = self._pop_next_task()
            if task is None:
                break
            result = self._finalize_task(task, self._run_task(task))
            produced.append(result)
        self.last_run_summary = {
            "mode": "single_worker",
            "max_workers": 1,
            "iterations": iterations,
            "produced": len(produced),
        }
        return produced

    def run_until_idle_concurrent(self, max_workers: int = 8, max_iterations: int = 10000) -> List[ExecutionResult]:
        produced: List[ExecutionResult] = []
        iterations = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while iterations < max_iterations:
                batch = self._pop_batch(max_workers)
                if not batch:
                    break
                iterations += len(batch)
                futures = {executor.submit(self._run_task, task): task for task in batch}
                for future in as_completed(futures):
                    task = futures[future]
                    result = self._finalize_task(task, future.result())
                    produced.append(result)
        self.last_run_summary = {
            "mode": "thread_pool_worker",
            "max_workers": max_workers,
            "iterations": iterations,
            "produced": len(produced),
        }
        return produced

    def _finalize_task(self, task: Task, result: ExecutionResult) -> ExecutionResult:
        self.results.append(result)
        if result.status not in {ResultStatus.PASS, ResultStatus.FAIL} and task.retry_count < task.max_retry:
            task.retry_count += 1
            task.status = TaskStatus.PENDING
            with self._queue_lock:
                self._queues[task.scenario].append(task)
        else:
            self._quarantine.record(result)
        return result

    def _pop_next_task(self) -> Optional[Task]:
        with self._queue_lock:
            candidates = [queue[0] for queue in self._queues.values() if queue]
            if not candidates:
                return None
            selected = sorted(candidates, key=lambda task: task.priority, reverse=True)[0]
            self._queues[selected.scenario].popleft()
            return selected

    def _pop_batch(self, batch_size: int) -> List[Task]:
        batch = []
        for _ in range(batch_size):
            task = self._pop_next_task()
            if task is None:
                break
            batch.append(task)
        return batch

    def policy_snapshot(self) -> Dict:
        return self._policy.policy

    def queue_snapshot(self) -> Dict[str, int]:
        with self._queue_lock:
            return {scenario.value: len(queue) for scenario, queue in self._queues.items()}

    def run_summary(self) -> Dict[str, int]:
        return dict(self.last_run_summary)

    def _run_task(self, task: Task) -> ExecutionResult:
        if self._quarantine.is_blocked(task.case.case_id):
            trace = self._empty_trace("用例处于 Quarantine 隔离池")
            return ExecutionResult(
                task_id=task.task_id,
                case_id=task.case.case_id,
                status=ResultStatus.SKIPPED,
                reason=self._quarantine.reason(task.case.case_id) or "CASE_IN_QUARANTINE",
                trace=trace,
                duration_seconds=0,
                confidence=0,
                writeback_target=task.metadata.get("writeback_target"),
                metadata=dict(task.metadata),
            )

        resource = self._resources.allocate(task)
        if not resource:
            trace = self._empty_trace("资源不足，任务阻塞")
            return ExecutionResult(
                task_id=task.task_id,
                case_id=task.case.case_id,
                status=ResultStatus.BLOCKED,
                reason="NO_RESOURCE",
                trace=trace,
                duration_seconds=0,
                confidence=0,
                writeback_target=task.metadata.get("writeback_target"),
                metadata=dict(task.metadata),
            )

        task.status = TaskStatus.RUNNING
        job = ExecutionJob(job_id=f"job-{uuid4().hex[:8]}", task=task, resource=resource)
        try:
            result = self._router.execute(job)
            result.metadata["analysis"] = self._analyzer.analyze(result)
            task.status = TaskStatus.FINISHED
            return result
        finally:
            self._resources.release(resource)

    def _empty_trace(self, reason: str) -> ExecutionTrace:
        return ExecutionTrace(trace_id=f"trace-{uuid4().hex[:8]}", actions=[], logs=[reason], confidence=0)
