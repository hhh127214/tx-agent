from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Dict, List, Protocol


@dataclass
class AdapterCall:
    operation: str
    external_id: str
    payload: Dict[str, Any]
    created_at: float = field(default_factory=time)


class InternalSystemAdapter(Protocol):
    system_name: str
    mode: str

    def health_check(self) -> Dict[str, Any]:
        """Return adapter health and integration mode."""


class InMemoryCICDAdapter:
    system_name = "ci_cd"
    mode = "simulated_internal_adapter"

    def __init__(self):
        self.calls: List[AdapterCall] = []

    def trigger_self_test(self, pipeline_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(AdapterCall("trigger_self_test", pipeline_id, payload))
        return {"system": self.system_name, "pipeline_id": pipeline_id, "accepted": True}

    def write_status(self, pipeline_id: str, status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(AdapterCall("write_status", pipeline_id, {"status": status, **payload}))
        return {"system": self.system_name, "pipeline_id": pipeline_id, "status": status}

    def health_check(self) -> Dict[str, Any]:
        return {"system": self.system_name, "mode": self.mode, "healthy": True, "calls": len(self.calls)}


class InMemoryBugSystemAdapter:
    system_name = "bug_system"
    mode = "simulated_internal_adapter"

    def __init__(self):
        self.calls: List[AdapterCall] = []

    def fetch_waiting_regression(self) -> List[Dict[str, Any]]:
        payload = {
            "bug_id": "BUG-1024",
            "title": "关闭通知开关后重新进入设置页仍显示开启",
            "status": "待回归"
        }
        self.calls.append(AdapterCall("fetch_waiting_regression", "BUG-1024", payload))
        return [payload]

    def write_regression_result(self, bug_id: str, status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(AdapterCall("write_regression_result", bug_id, {"status": status, **payload}))
        return {"system": self.system_name, "bug_id": bug_id, "status": status}

    def health_check(self) -> Dict[str, Any]:
        return {"system": self.system_name, "mode": self.mode, "healthy": True, "calls": len(self.calls)}


class InMemoryRequirementAdapter:
    system_name = "requirement_system"
    mode = "simulated_internal_adapter"

    def __init__(self):
        self.calls: List[AdapterCall] = []

    def fetch_acceptance_criteria(self, requirement_id: str) -> Dict[str, Any]:
        payload = {
            "requirement_id": requirement_id,
            "prd": "用户可在设置页关闭通知开关，保存失败时提示稍后重试并保持原状态。"
        }
        self.calls.append(AdapterCall("fetch_acceptance_criteria", requirement_id, payload))
        return payload

    def write_test_report(self, requirement_id: str, status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(AdapterCall("write_test_report", requirement_id, {"status": status, **payload}))
        return {"system": self.system_name, "requirement_id": requirement_id, "status": status}

    def health_check(self) -> Dict[str, Any]:
        return {"system": self.system_name, "mode": self.mode, "healthy": True, "calls": len(self.calls)}


class InternalAdapterRegistry:
    def __init__(self):
        self.ci_cd = InMemoryCICDAdapter()
        self.bug_system = InMemoryBugSystemAdapter()
        self.requirement_system = InMemoryRequirementAdapter()

    def health(self) -> Dict[str, Any]:
        adapters = [self.ci_cd, self.bug_system, self.requirement_system]
        return {
            "connected_system_count": len(adapters),
            "mode": "simulated_internal_adapter",
            "adapters": [adapter.health_check() for adapter in adapters],
            "production_note": "替换为真实内网 endpoint、鉴权和字段映射后，可作为真实系统适配层。"
        }
