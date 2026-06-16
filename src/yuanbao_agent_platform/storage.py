from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Dict

from yuanbao_agent_platform.config import PROJECT_ROOT


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

    def stats(self) -> Dict[str, int]:
        with self._connect() as conn:
            return {
                "tasks": self._count(conn, "tasks"),
                "execution_results": self._count(conn, "execution_results"),
                "writebacks": self._count(conn, "writebacks"),
                "acceptance_reports": self._count(conn, "acceptance_reports"),
            }

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
        with self._connect() as conn:
            for statement in statements:
                conn.execute(statement)
            conn.commit()

    def _execute(self, statement: str, params: tuple) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(statement, params)
                conn.commit()

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def _count(self, conn, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
