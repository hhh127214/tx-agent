from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any, Dict, List, Optional
from urllib import parse, request


@dataclass
class ExternalCall:
    system: str
    operation: str
    external_id: str
    payload: Dict[str, Any]
    mode: str
    created_at: float = field(default_factory=time)


class GitHubActionsAdapter:
    system_name = "github_actions"

    def __init__(self, repo: str = None, token: str = None, workflow: str = "agent-self-test.yml"):
        self.repo = repo or os.getenv("GITHUB_REPOSITORY", "")
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.workflow = workflow
        self.calls: List[ExternalCall] = []

    @property
    def mode(self) -> str:
        if os.getenv("GITHUB_ACTIONS") == "true":
            return "github_actions_runtime"
        return "github_api" if self.repo and self.token else "dry_run_payload"

    def trigger_agent_self_test(self, ref: str = "master", inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        payload = {"ref": ref, "inputs": inputs or {"scenario": "dev_self_test"}}
        external_id = f"{self.repo or 'local-repo'}:{self.workflow}:{ref}"
        if self.mode == "github_actions_runtime":
            response = {
                "current_run": True,
                "run_id": os.getenv("GITHUB_RUN_ID", ""),
                "workflow": os.getenv("GITHUB_WORKFLOW", ""),
                "event": os.getenv("GITHUB_EVENT_NAME", ""),
                "request": payload,
            }
        elif self.mode == "github_api":
            response = self._post_json(
            f"https://api.github.com/repos/{self.repo}/actions/workflows/{self.workflow}/dispatches",
            payload,
            expected_status={204},
            )
        else:
            response = {"dry_run": True, "request": payload}
        self.calls.append(ExternalCall(self.system_name, "workflow_dispatch", external_id, payload, self.mode))
        return {"system": self.system_name, "mode": self.mode, "external_id": external_id, "response": response}

    def health_check(self) -> Dict[str, Any]:
        return {"system": self.system_name, "mode": self.mode, "healthy": True, "calls": len(self.calls)}

    def _post_json(self, url: str, payload: Dict[str, Any], expected_status: set) -> Dict[str, Any]:
        encoded = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=encoded,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with request.urlopen(req, timeout=10) as response:
            if response.status not in expected_status:
                raise RuntimeError(f"GitHub API status {response.status}")
            return {"status": response.status}


class GitHubIssuesAdapter:
    system_name = "github_issues"

    def __init__(self, repo: str = None, token: str = None, waiting_label: str = "待回归"):
        self.repo = repo or os.getenv("GITHUB_REPOSITORY", "")
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.waiting_label = waiting_label
        self.calls: List[ExternalCall] = []

    @property
    def mode(self) -> str:
        return "github_api" if self.repo and self.token else "dry_run_payload"

    def fetch_waiting_regression(self) -> List[Dict[str, Any]]:
        payload = {"state": "open", "labels": self.waiting_label}
        if self.mode == "github_api":
            query = parse.urlencode({"state": "open", "labels": self.waiting_label})
            response = self._request_json(f"https://api.github.com/repos/{self.repo}/issues?{query}")
            issues = [
                {
                    "bug_id": f"GH-{item['number']}",
                    "number": item["number"],
                    "title": item["title"],
                    "body": item.get("body", ""),
                    "url": item["html_url"],
                }
                for item in response
                if "pull_request" not in item
            ]
        else:
            issues = [
                {
                    "bug_id": "GH-1",
                    "number": 1,
                    "title": "关闭通知开关后重新进入设置页仍显示开启",
                    "body": "复现步骤：登录 Demo Web，进入设置，关闭通知开关，重新进入设置页。期望：保持关闭。",
                    "url": "https://github.com/example/repo/issues/1",
                }
            ]
        self.calls.append(ExternalCall(self.system_name, "fetch_waiting_regression", self.repo or "local-repo", payload, self.mode))
        return issues

    def write_regression_result(self, issue_number: int, status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "body": (
                f"### Yuanbao Agent 回归结果\n\n"
                f"- 状态：{status}\n"
                f"- 结论：{payload.get('reason', '')}\n"
                f"- Trace：{payload.get('trace_id', '')}\n"
            )
        }
        external_id = f"{self.repo or 'local-repo'}#{issue_number}"
        response = self._post_issue_comment(issue_number, body) if self.mode == "github_api" else {"dry_run": True, "request": body}
        self.calls.append(ExternalCall(self.system_name, "write_issue_comment", external_id, body, self.mode))
        return {"system": self.system_name, "mode": self.mode, "external_id": external_id, "response": response}

    def health_check(self) -> Dict[str, Any]:
        return {"system": self.system_name, "mode": self.mode, "healthy": True, "calls": len(self.calls)}

    def _request_json(self, url: str) -> Any:
        req = request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_issue_comment(self, issue_number: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        encoded = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"https://api.github.com/repos/{self.repo}/issues/{issue_number}/comments",
            data=encoded,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with request.urlopen(req, timeout=10) as response:
            return {"status": response.status, "body": json.loads(response.read().decode("utf-8"))}


class MarkdownPRDAdapter:
    system_name = "markdown_prd"
    mode = "local_file_real_prd"

    def __init__(self, prd_root: str = "docs/prd"):
        self.prd_root = Path(prd_root)
        self.calls: List[ExternalCall] = []

    def fetch_prd(self, prd_id: str) -> Dict[str, Any]:
        path = self.prd_root / f"{prd_id}.md"
        text = path.read_text(encoding="utf-8")
        payload = {"prd_id": prd_id, "path": str(path), "prd_text": text}
        self.calls.append(ExternalCall(self.system_name, "fetch_prd", prd_id, {"path": str(path)}, self.mode))
        return payload

    def health_check(self) -> Dict[str, Any]:
        return {"system": self.system_name, "mode": self.mode, "healthy": self.prd_root.exists(), "calls": len(self.calls)}


class ExternalAdapterRegistry:
    def __init__(
        self,
        github_actions: Optional[GitHubActionsAdapter] = None,
        github_issues: Optional[GitHubIssuesAdapter] = None,
        markdown_prd: Optional[MarkdownPRDAdapter] = None,
    ):
        self.github_actions = github_actions or GitHubActionsAdapter()
        self.github_issues = github_issues or GitHubIssuesAdapter()
        self.markdown_prd = markdown_prd or MarkdownPRDAdapter()

    def health(self) -> Dict[str, Any]:
        adapters = [self.github_actions, self.github_issues, self.markdown_prd]
        return {
            "connected_system_count": len(adapters),
            "mode": "external_substitute_adapters",
            "adapters": [adapter.health_check() for adapter in adapters],
            "note": "GitHub token/repo configured时可调用真实 GitHub API；未配置时输出 dry-run payload，Markdown PRD 为真实本地文件接入。",
        }
