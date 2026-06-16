from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional
from uuid import uuid4


class Scenario(str, Enum):
    INTEGRATION_BATCH = "INTEGRATION_BATCH"
    DEV_SELF_TEST = "DEV_SELF_TEST"
    REQUIREMENT_TEST = "REQUIREMENT_TEST"
    BUG_REGRESSION = "BUG_REGRESSION"


class AutomationType(str, Enum):
    GUI_AGENT = "GUI_AGENT"
    BACKEND_AUTOMATION = "BACKEND_AUTOMATION"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    QUARANTINED = "QUARANTINED"


class TriggerType(str, Enum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    WEBHOOK = "WEBHOOK"
    CI = "CI"
    STATUS_CHANGE = "STATUS_CHANGE"


@dataclass
class Assertion:
    assertion_id: str
    expected: str
    pass_criteria: str
    fail_criteria: str
    unknown_criteria: str


@dataclass
class TestStep:
    step_id: str
    intent: str
    target_semantics: str
    visual_hints: List[str] = field(default_factory=list)
    expected_state: Optional[str] = None
    timeout_seconds: int = 30


@dataclass
class TestCase:
    case_id: str
    title: str
    automation_type: AutomationType
    preconditions: List[str] = field(default_factory=list)
    steps: List[TestStep] = field(default_factory=list)
    assertions: List[Assertion] = field(default_factory=list)
    source: str = "manual"
    priority: str = "P1"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentPlan:
    plan_id: str
    goal: str
    context: Dict[str, Any]
    steps: List[Dict[str, Any]]
    max_steps: int = 20
    timeout_seconds: int = 180
    self_healing: Dict[str, Any] = field(default_factory=dict)
    result_schema: List[str] = field(default_factory=lambda: ["PASS", "FAIL", "UNKNOWN"])


@dataclass
class Task:
    scenario: Scenario
    case: TestCase
    trigger_type: TriggerType
    source: str
    task_id: str = field(default_factory=lambda: f"task-{uuid4().hex[:8]}")
    priority: int = 0
    timeout_seconds: int = 180
    max_retry: int = 1
    retry_count: int = 0
    status: TaskStatus = TaskStatus.PENDING
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time)


@dataclass
class ExecutionJob:
    job_id: str
    task: Task
    resource: Dict[str, Any]
    started_at: float = field(default_factory=time)


@dataclass
class ExecutionTrace:
    trace_id: str
    actions: List[Dict[str, Any]]
    screenshots: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class ExecutionResult:
    task_id: str
    case_id: str
    status: ResultStatus
    reason: str
    trace: ExecutionTrace
    duration_seconds: float
    confidence: float
    writeback_target: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BugReport:
    bug_id: str
    title: str
    status: str
    severity: str
    version: str
    steps: List[str]
    expected: str
    actual: str
    environment: str = ""
    attachments: List[str] = field(default_factory=list)


@dataclass
class BugRegressionResult:
    bug_id: str
    result: ResultStatus
    conclusion: str
    evidence: Dict[str, Any]
    need_human_review: bool
    unknown_reason: Optional[str] = None


@dataclass
class KnowledgeChunk:
    chunk_id: str
    source_type: str
    title: str
    content: str
    tags: List[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time)


@dataclass
class RetrievedKnowledge:
    source_type: str
    source_id: str
    title: str
    score: float
    reason: str


@dataclass
class TestPoint:
    point_id: str
    priority: str
    point_type: str
    title: str
    precondition: str
    steps: List[str]
    expected: str
    data_requirement: str
    automation_type: AutomationType
    risk_level: str
    source: str


@dataclass
class TestPointGeneration:
    prd_id: str
    feature: str
    summary: str
    keywords: List[str]
    retrieved_knowledge: List[RetrievedKnowledge]
    test_points: List[TestPoint]
    coverage: Dict[str, int]
    need_human_review: bool = False
