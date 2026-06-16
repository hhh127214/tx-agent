from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from yuanbao_agent_platform.knowledge import HybridKnowledgeBase, default_knowledge_base
from yuanbao_agent_platform.llm import CasePlanningLLM, MockCasePlanningLLM
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
    def __init__(self, knowledge_base: HybridKnowledgeBase = None):
        self._knowledge_base = knowledge_base or default_knowledge_base()

    def generate(self, prd_id: str, prd_text: str) -> TestPointGeneration:
        keywords = self._extract_keywords(prd_text)
        retrieved = self._knowledge_base.search(" ".join(keywords) + " " + prd_text, top_k=5)
        feature = self._extract_feature(prd_text, keywords)
        test_points = self._build_test_points(feature, prd_text, retrieved)
        coverage = {
            "functional": sum(1 for point in test_points if point.point_type == "functional"),
            "boundary": sum(1 for point in test_points if point.point_type == "boundary"),
            "exception": sum(1 for point in test_points if point.point_type == "exception"),
            "compatibility": sum(1 for point in test_points if point.point_type == "compatibility"),
            "permission": sum(1 for point in test_points if point.point_type == "permission"),
        }
        return TestPointGeneration(
            prd_id=prd_id,
            feature=feature,
            summary=f"围绕{feature}生成 GUI Agent 与后台自动化测试点",
            keywords=keywords,
            retrieved_knowledge=retrieved,
            test_points=test_points,
            coverage=coverage,
            need_human_review=False,
        )

    def _extract_keywords(self, text: str) -> List[str]:
        candidates = [
            "通知开关",
            "设置页",
            "状态持久化",
            "消息推送",
            "重新登录",
            "重启 App",
            "切换网络",
            "接口保存失败",
            "弱网",
            "权限",
            "异常提示",
        ]
        keywords = [candidate for candidate in candidates if candidate.replace(" App", "") in text]
        if not keywords:
            import re

            keywords = re.findall(r"[\u4e00-\u9fff]{2,8}", text)[:8]
        return list(dict.fromkeys(keywords))

    def _extract_feature(self, text: str, keywords: List[str]) -> str:
        if "通知" in text and "设置" in text:
            return "设置页通知开关"
        return keywords[0] if keywords else "PRD 功能点"

    def _build_test_points(
        self,
        feature: str,
        prd_text: str,
        retrieved: List[RetrievedKnowledge],
    ) -> List[TestPoint]:
        points = [
            TestPoint(
                point_id="TP-001",
                priority="P0",
                point_type="functional",
                title=f"{feature}基础功能验证",
                precondition="用户已登录且具备功能入口",
                steps=["进入目标页面", "根据 PRD 操作目标控件", "观察页面状态"],
                expected="页面状态符合 PRD 描述",
                data_requirement="正常测试账号",
                automation_type=AutomationType.GUI_AGENT,
                risk_level="high",
                source="PRD",
            )
        ]

        if "重启" in prd_text or "重新登录" in prd_text or "保持" in prd_text:
            points.append(
                TestPoint(
                    point_id="TP-002",
                    priority="P0",
                    point_type="boundary",
                    title=f"{feature}状态持久化验证",
                    precondition="目标状态已被修改",
                    steps=["修改目标状态", "重启 App 或重新登录", "重新进入目标页面"],
                    expected="目标状态保持不变",
                    data_requirement="同一登录账号",
                    automation_type=AutomationType.GUI_AGENT,
                    risk_level="high",
                    source="PRD + HISTORY_BUG",
                )
            )

        if "失败" in prd_text or "异常" in prd_text or "弱网" in prd_text:
            points.append(
                TestPoint(
                    point_id="TP-003",
                    priority="P1",
                    point_type="exception",
                    title=f"{feature}异常失败处理验证",
                    precondition="测试环境可模拟接口失败或弱网",
                    steps=["进入目标页面", "触发目标操作", "模拟接口失败或弱网"],
                    expected="展示明确错误提示，并保持或回滚到合理状态",
                    data_requirement="可控 Mock 或测试环境",
                    automation_type=AutomationType.BACKEND_AUTOMATION,
                    risk_level="medium",
                    source="PRD + TEST_SPEC",
                )
            )

        if retrieved and not any(point.point_type == "exception" for point in points):
            points.append(
                TestPoint(
                    point_id="TP-004",
                    priority="P2",
                    point_type="exception",
                    title=f"{feature}历史风险回归验证",
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
