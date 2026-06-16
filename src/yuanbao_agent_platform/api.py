from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple

from yuanbao_agent_platform.models import BugReport, Scenario, TriggerType
from yuanbao_agent_platform.platform import YuanbaoTestingPlatform


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


class YuanbaoApi:
    def __init__(self, platform: YuanbaoTestingPlatform = None):
        self._platform = platform or YuanbaoTestingPlatform()

    def handle(self, method: str, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if method == "GET" and path == "/health":
            return 200, {"status": "ok", "service": "yuanbao-agent-platform"}

        if method == "GET" and path == "/scheduler/policy":
            return 200, self._platform.scheduler.policy_snapshot()

        if method == "GET" and path == "/metrics":
            return 200, self._platform.metrics.summarize(
                self._platform.scheduler.submitted_tasks,
                self._platform.scheduler.results,
            )

        if method == "GET" and path == "/integrations":
            return 200, {
                "config": self._platform.integrations.config,
                "writebacks": self._platform.integrations.snapshot(),
            }

        if method == "POST" and path == "/cases/convert":
            return 200, self._platform.convert_manual_case(
                payload.get("case_id", "case-api-001"),
                payload["text"],
            )

        if method == "POST" and path == "/prd/test-points":
            return 200, self._platform.generate_prd_test_points(
                payload.get("prd_id", "PRD-API-001"),
                payload["prd_text"],
            )

        if method == "POST" and path == "/bugs/regress":
            bug = BugReport(
                bug_id=payload["bug_id"],
                title=payload["title"],
                status=payload.get("status", "待回归"),
                severity=payload.get("severity", "P1"),
                version=payload.get("version", ""),
                steps=payload["steps"],
                expected=payload["expected"],
                actual=payload.get("actual", ""),
                environment=payload.get("environment", ""),
                attachments=payload.get("attachments", []),
            )
            return 200, asdict(self._platform.run_bug_regression(bug))

        if method == "POST" and path == "/tasks/manual":
            task = self._platform.submit_manual_case(
                Scenario(payload.get("scenario", Scenario.DEV_SELF_TEST.value)),
                payload.get("case_id", "case-api-001"),
                payload["text"],
                TriggerType(payload.get("trigger_type", TriggerType.MANUAL.value)),
            )
            return 202, asdict(task)

        if method == "POST" and path == "/tasks/run":
            return 200, {"results": self._platform.run_queued_tasks()}

        if method == "POST" and path == "/demo":
            return 200, self._platform.run_demo()

        return 404, {"error": "NOT_FOUND", "path": path}


class YuanbaoRequestHandler(BaseHTTPRequestHandler):
    api = YuanbaoApi()

    def do_GET(self) -> None:
        self._handle({})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._write(400, {"error": "INVALID_JSON"})
            return
        self._handle(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle(self, payload: Dict[str, Any]) -> None:
        try:
            status, body = self.api.handle(self.command, self.path, payload)
        except KeyError as exc:
            self._write(400, {"error": "MISSING_FIELD", "field": str(exc)})
            return
        except ValueError as exc:
            self._write(400, {"error": "INVALID_VALUE", "message": str(exc)})
            return
        self._write(status, body)

    def _write(self, status: int, body: Dict[str, Any]) -> None:
        encoded = json.dumps(to_jsonable(body), ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), YuanbaoRequestHandler)
    print(f"Yuanbao Agent Platform API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
