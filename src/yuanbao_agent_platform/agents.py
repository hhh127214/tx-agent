from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from yuanbao_agent_platform.knowledge import HybridKnowledgeBase, default_knowledge_base
from yuanbao_agent_platform.llm import CasePlanningLLM, MockCasePlanningLLM, MockPRDPlanningLLM, PRDPlanningLLM
from yuanbao_agent_platform.models import (
    AgentPlan,
    Assertion,
    AutomationType,
    BugReport,
    RetrievedKnowledge,
    TestCase,
    TestPoint,
    TestPointGeneration,
    TestStep,
)


class NaturalLanguageCaseConverter:
    def __init__(self, planner: CasePlanningLLM = None):
        self._planner = planner or MockCasePlanningLLM()

    def convert(self, case_id: str, text: str) -> TestCase:
        planning = self._planner.plan_case(text)
        steps = [
            TestStep(
                step_id=f"s{index}",
                intent=step.intent,
                target_semantics=step.target_semantics,
                visual_hints=step.visual_hints,
                expected_state=step.expected_state,
            )
            for index, step in enumerate(planning.steps, start=1)
        ]
        assertion = Assertion(
            assertion_id=f"assert-{case_id}",
            expected=planning.assertions[-1] if planning.assertions else steps[-1].expected_state,
            pass_criteria="视觉状态和业务状态均符合预期",
            fail_criteria="页面明确展示与预期相反的结果",
            unknown_criteria="页面变化、断言不明确或视觉置信度不足",
        )
        return TestCase(
            case_id=case_id,
            title=planning.title,
            automation_type=AutomationType.GUI_AGENT,
            preconditions=planning.preconditions,
            steps=steps,
            assertions=[assertion],
            source="natural_language",
            metadata={
                "raw_text": text.strip(),
                "conversion": "llm_planned_vision_based_semantic_plan",
                "planner_provider": planning.planner_provider,
                "prompt_version": planning.prompt_version,
                "planner_confidence": planning.confidence,
                "planner_reasoning_summary": planning.raw_reasoning_summary,
                "extracted_entities": planning.extracted_entities,
                "pages": planning.pages,
                "fallback_strategy": planning.fallback_strategy,
                "need_human_review": planning.need_human_review,
            },
        )

    def to_agent_plan(self, test_case: TestCase) -> AgentPlan:
        plan_steps = []
        for step in test_case.steps:
            plan_steps.append(
                {
                    "intent": step.intent,
                    "visual_target": step.target_semantics,
                    "visual_hints": step.visual_hints,
                    "success_criteria": step.expected_state or "完成该步骤目标",
                    "unknown_criteria": "无法找到语义目标或页面状态无法可靠识别",
                }
            )

        return AgentPlan(
            plan_id=f"plan-{test_case.case_id}",
            goal=test_case.title,
            context={
                "execution_mode": "VISION_BASED_GUI_AGENT",
                "planning_mode": "LLM_PLANNED",
                "planner_provider": test_case.metadata.get("planner_provider", "unknown"),
                "prompt_version": test_case.metadata.get("prompt_version"),
                "selector_policy": "visual_first_auxiliary_metadata_only",
                "preconditions": test_case.preconditions,
            },
            steps=plan_steps,
            max_steps=max(10, len(plan_steps) * 5),
            timeout_seconds=max(120, len(plan_steps) * 45),
            self_healing={
                "allow_scroll": True,
                "allow_backtrack": True,
                "allow_synonym_match": True,
                "allow_page_graph_reroute": True,
                "max_recovery_attempts": 3,
            },
        )

    def as_ir(self, test_case: TestCase) -> Dict[str, Any]:
        return {
            "case_id": test_case.case_id,
            "title": test_case.title,
            "goal": test_case.title,
            "preconditions": test_case.preconditions,
            "pages": test_case.metadata.get("pages", []),
            "steps": [asdict(step) for step in test_case.steps],
            "assertions": [asdict(assertion) for assertion in test_case.assertions],
            "fallback_strategy": test_case.metadata.get("fallback_strategy", []),
            "planner_provider": test_case.metadata.get("planner_provider"),
            "prompt_version": test_case.metadata.get("prompt_version"),
            "extracted_entities": test_case.metadata.get("extracted_entities", {}),
            "confidence": test_case.metadata.get("planner_confidence", 0.0),
            "need_human_review": test_case.metadata.get("need_human_review", False),
        }


class BugRegressionAgent:
    def __init__(self, converter: NaturalLanguageCaseConverter):
        self._converter = converter

    def build_regression_case(self, bug: BugReport) -> TestCase:
        text = "，".join(bug.steps + [f"验证{bug.expected}"])
        test_case = self._converter.convert(f"bug-{bug.bug_id}", text)
        test_case.title = f"BUG回归：{bug.title}"
        test_case.source = "bug_regression"
        test_case.priority = "P0" if bug.severity in {"P0", "P1"} else "P1"
        test_case.metadata.update(
            {
                "bug_id": bug.bug_id,
                "bug_status": bug.status,
                "severity": bug.severity,
                "expected": bug.expected,
                "actual": bug.actual,
                "version": bug.version,
            }
        )
        return test_case


class PRDTestDesignAgent:
    def __init__(self, knowledge_base: HybridKnowledgeBase = None, planner: PRDPlanningLLM = None):
        self._knowledge_base = knowledge_base or default_knowledge_base()
        self._planner = planner or MockPRDPlanningLLM()

    def generate(self, prd_id: str, prd_text: str) -> TestPointGeneration:
        planning = self._planner.plan_prd(prd_text)
        retrieved = self._knowledge_base.search(" ".join(planning.keywords + planning.risk_points) + " " + prd_text, top_k=5)
        test_points = self._build_test_points(planning, retrieved)
        coverage = {
            "functional": sum(1 for point in test_points if point.point_type == "functional"),
            "boundary": sum(1 for point in test_points if point.point_type == "boundary"),
            "exception": sum(1 for point in test_points if point.point_type == "exception"),
            "compatibility": sum(1 for point in test_points if point.point_type == "compatibility"),
            "permission": sum(1 for point in test_points if point.point_type == "permission"),
        }
        return TestPointGeneration(
            prd_id=prd_id,
            feature=planning.feature,
            summary=planning.summary,
            keywords=planning.keywords,
            retrieved_knowledge=retrieved,
            test_points=test_points,
            coverage=coverage,
            need_human_review=planning.need_human_review,
            metadata={
                "planner_provider": planning.planner_provider,
                "prompt_version": planning.prompt_version,
                "planner_confidence": planning.confidence,
                "risk_points": planning.risk_points,
            },
        )

    def _build_test_points(self, planning, retrieved: List[RetrievedKnowledge]) -> List[TestPoint]:
        points = []
        for index, blueprint in enumerate(planning.test_blueprints, start=1):
            points.append(
                TestPoint(
                    point_id=f"TP-{index:03d}",
                    priority=blueprint.priority,
                    point_type=blueprint.point_type,
                    title=blueprint.title,
                    precondition=blueprint.precondition,
                    steps=blueprint.steps,
                    expected=blueprint.expected,
                    data_requirement=blueprint.data_requirement,
                    automation_type=AutomationType(blueprint.automation_type),
                    risk_level=blueprint.risk_level,
                    source=blueprint.source,
                )
            )
        if retrieved and not any(point.point_type == "exception" for point in points):
            points.append(
                TestPoint(
                    point_id=f"TP-{len(points) + 1:03d}",
                    priority="P2",
                    point_type="exception",
                    title=f"{planning.feature}历史风险回归验证",
                    precondition="存在历史相似缺陷知识",
                    steps=["执行历史缺陷相关路径", "验证风险点不再出现"],
                    expected="历史相似问题不复现",
                    data_requirement="历史缺陷相关账号或数据",
                    automation_type=AutomationType.GUI_AGENT,
                    risk_level="medium",
                    source=retrieved[0].source_id,
                )
            )
        return points
