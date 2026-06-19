from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

from yuanbao_agent_platform.config import PROJECT_ROOT
from yuanbao_agent_platform.models import (
    Assertion,
    AutomationType,
    Scenario,
    Task,
    TaskStatus,
    TestCase,
    TestStep,
    TriggerType,
)


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


class SQLiteStore:
    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path) if db_path else PROJECT_ROOT / "data" / "yuanbao_agent_platform.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def save_task(self, task) -> None:
        payload = jsonable(task)
        self._execute(
            """
            INSERT OR REPLACE INTO tasks(task_id, scenario, case_id, status, priority, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.scenario.value,
                task.case.case_id,
                task.status.value,
                task.priority,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    def save_result(self, result) -> None:
        payload = jsonable(result)
        self._execute(
            """
            INSERT OR REPLACE INTO execution_results(task_id, case_id, status, reason, confidence, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                result.task_id,
                result.case_id,
                result.status.value,
                result.reason,
                result.confidence,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    def save_writeback(self, record) -> None:
        payload = jsonable(record)
        self._execute(
            """
            INSERT OR REPLACE INTO writebacks(idempotency_key, target, external_id, status, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.idempotency_key,
                record.target,
                record.external_id,
                record.status,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    def save_acceptance_report(self, report: Dict[str, Any]) -> None:
        self._execute(
            "INSERT INTO acceptance_reports(payload) VALUES (?)",
            (json.dumps(jsonable(report), ensure_ascii=False),),
        )

    def load_recoverable_tasks(self) -> List[Task]:
        """Load unfinished tasks that were persisted but never produced a result.

        RUNNING tasks are treated as interrupted and restored to PENDING so the
        scheduler can safely retry them after an explicit recovery request.
        """

        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT payload
                FROM tasks
                WHERE status IN (?, ?)
                  AND task_id NOT IN (SELECT task_id FROM execution_results)
                ORDER BY priority DESC, created_at ASC
                """,
                (TaskStatus.PENDING.value, TaskStatus.RUNNING.value),
            ).fetchall()
        finally:
            conn.close()
        return [self._task_from_payload(json.loads(row[0])) for row in rows]

    def stats(self) -> Dict[str, int]:
        conn = self._connect()
        try:
            return {
                "tasks": self._count(conn, "tasks"),
                "execution_results": self._count(conn, "execution_results"),
                "writebacks": self._count(conn, "writebacks"),
                "acceptance_reports": self._count(conn, "acceptance_reports"),
            }
        finally:
            conn.close()

    def _init_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS tasks (
              task_id TEXT PRIMARY KEY,
              scenario TEXT NOT NULL,
              case_id TEXT NOT NULL,
              status TEXT NOT NULL,
              priority INTEGER NOT NULL,
              payload TEXT NOT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS execution_results (
              task_id TEXT PRIMARY KEY,
              case_id TEXT NOT NULL,
              status TEXT NOT NULL,
              reason TEXT NOT NULL,
              confidence REAL NOT NULL,
              payload TEXT NOT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS writebacks (
              idempotency_key TEXT PRIMARY KEY,
              target TEXT NOT NULL,
              external_id TEXT NOT NULL,
              status TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS acceptance_reports (
              report_id INTEGER PRIMARY KEY AUTOINCREMENT,
              payload TEXT NOT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ]
        conn = self._connect()
        try:
            for statement in statements:
                conn.execute(statement)
            conn.commit()
        finally:
            conn.close()

    def _execute(self, statement: str, params: tuple) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(statement, params)
                conn.commit()
            finally:
                conn.close()

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def _count(self, conn, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _task_from_payload(self, payload: Dict[str, Any]) -> Task:
        case_payload = payload["case"]
        test_case = TestCase(
            case_id=case_payload["case_id"],
            title=case_payload["title"],
            automation_type=AutomationType(case_payload["automation_type"]),
            preconditions=list(case_payload.get("preconditions", [])),
            steps=[
                TestStep(
                    step_id=step["step_id"],
                    intent=step["intent"],
                    target_semantics=step["target_semantics"],
                    visual_hints=list(step.get("visual_hints", [])),
                    expected_state=step.get("expected_state"),
                    timeout_seconds=int(step.get("timeout_seconds", 30)),
                )
                for step in case_payload.get("steps", [])
            ],
            assertions=[
                Assertion(
                    assertion_id=assertion["assertion_id"],
                    expected=assertion["expected"],
                    pass_criteria=assertion["pass_criteria"],
                    fail_criteria=assertion["fail_criteria"],
                    unknown_criteria=assertion["unknown_criteria"],
                )
                for assertion in case_payload.get("assertions", [])
            ],
            source=case_payload.get("source", "manual"),
            priority=case_payload.get("priority", "P1"),
            metadata=dict(case_payload.get("metadata", {})),
        )
        metadata = dict(payload.get("metadata", {}))
        if payload.get("status") == TaskStatus.RUNNING.value:
            metadata["recovered_from_interrupted_run"] = True
        task = Task(
            scenario=Scenario(payload["scenario"]),
            case=test_case,
            trigger_type=TriggerType(payload["trigger_type"]),
            source=payload["source"],
            task_id=payload["task_id"],
            priority=int(payload.get("priority", 0)),
            timeout_seconds=int(payload.get("timeout_seconds", 180)),
            max_retry=int(payload.get("max_retry", 1)),
            retry_count=int(payload.get("retry_count", 0)),
            status=TaskStatus.PENDING,
            idempotency_key=payload.get("idempotency_key"),
            metadata=metadata,
            created_at=float(payload.get("created_at", 0)),
        )
        return task
