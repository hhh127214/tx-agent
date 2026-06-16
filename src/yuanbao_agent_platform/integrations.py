from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Dict, List

from yuanbao_agent_platform.config import integration_config
from yuanbao_agent_platform.models import ExecutionResult


@dataclass
class WritebackRecord:
    target: str
    external_id: str
    status: str
    message: str
    payload: Dict[str, Any]
    idempotency_key: str
    created_at: float = field(default_factory=time)


class IntegrationHub:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or integration_config()
        self.records: List[WritebackRecord] = []

    def writeback_execution(self, result: ExecutionResult, target: str, external_id: str) -> WritebackRecord:
        target_config = self.config[target]
        mapped_status = target_config["writeback_states"].get(result.status.value, result.status.value)
        record = WritebackRecord(
            target=target,
            external_id=external_id,
            status=mapped_status,
            message=result.reason,
            payload={
                "task_id": result.task_id,
                "case_id": result.case_id,
                "result": result.status.value,
                "confidence": result.confidence,
                "trace_id": result.trace.trace_id,
                "screenshots": result.trace.screenshots,
                "logs": result.trace.logs,
                "analysis": result.metadata.get("analysis", {}),
            },
            idempotency_key=f"{target}:{external_id}:{result.task_id}",
        )
        self.records.append(record)
        return record

    def snapshot(self) -> List[Dict[str, Any]]:
        return [
            {
                "target": record.target,
                "external_id": record.external_id,
                "status": record.status,
                "message": record.message,
                "idempotency_key": record.idempotency_key,
                "payload": record.payload,
            }
            for record in self.records
        ]
