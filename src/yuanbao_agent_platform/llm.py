from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Protocol


@dataclass
class PlannedStep:
    intent: str
    target_semantics: str
    visual_hints: List[str]
    expected_state: str


@dataclass
class CasePlanningResult:
    title: str
    goal: str
    preconditions: List[str]
    pages: List[Dict[str, List[str]]]
    steps: List[PlannedStep]
    assertions: List[str]
    fallback_strategy: List[str]
    confidence: float
    need_human_review: bool
    planner_provider: str
    prompt_version: str
    raw_reasoning_summary: str = ""
    extracted_entities: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class TestPointBlueprint:
    point_type: str
    priority: str
    title: str
    precondition: str
    steps: List[str]
    expected: str
    data_requirement: str
    automation_type: str
    risk_level: str
    source: str


@dataclass
class PRDPlanningResult:
    feature: str
    summary: str
    keywords: List[str]
    risk_points: List[str]
    test_blueprints: List[TestPointBlueprint]
    confidence: float
    need_human_review: bool
    planner_provider: str
    prompt_version: str


class CasePlanningLLM(Protocol):
    def plan_case(self, case_text: str) -> CasePlanningResult:
        """Convert natural language test case into semantic GUI Agent steps."""


class PRDPlanningLLM(Protocol):
    def plan_prd(self, prd_text: str) -> PRDPlanningResult:
        """Extract PRD semantics and generate test point blueprints."""


class SemanticConceptMapper:
    """Tiny dependency-free semantic mapper used by Mock LLM adapters.

    It is still deterministic, but it intentionally maps fuzzy phrases onto
    product concepts instead of checking only exact feature keywords.
    """

    CONCEPT_ALIASES = {
        "notification": [
            "通知",
            "提醒",
            "推送",
            "消息",
            "叮叮咚咚",
            "打扰",
            "响铃",
            "弹消息",
            "叫我",
        ],
        "settings": ["设置", "配置", "偏好", "选项", "开关中心", "齿轮", "管理页"],
        "mine": ["我的", "个人", "账号", "头像", "个人中心", "我"],
        "disable": ["关闭", "关掉", "禁用", "停用", "不要", "不再", "取消", "屏蔽"],
        "verify": ["验证", "检查", "确认", "看看", "确保", "保持", "保留", "还在"],
        "persist": ["保持", "保留", "重新进入", "重进", "重启", "重新登录", "切换网络", "不变", "还关着", "还开着"],
        "failure": ["失败", "异常", "报错", "弱网", "超时", "不可用"],
        "login": ["登录", "登陆", "进入账号态"],
    }

    def detect(self, text: str) -> Dict[str, List[str]]:
        return {
            concept: [alias for alias in aliases if alias.lower() in text.lower()]
            for concept, aliases in self.CONCEPT_ALIASES.items()
            if any(alias.lower() in text.lower() for alias in aliases)
        }

    def has(self, concepts: Dict[str, List[str]], name: str) -> bool:
        return name in concepts


class MockCasePlanningLLM:
    """Deterministic local LLM adapter with semantic generalization examples."""

    def __init__(self, mapper: SemanticConceptMapper = None):
        self._mapper = mapper or SemanticConceptMapper()

    def plan_case(self, case_text: str) -> CasePlanningResult:
        text = case_text.strip()
        concepts = self._mapper.detect(text)
        steps = self._compose_steps(text, concepts)
        need_review = not steps or "不明确" in text or "随便" in text
        confidence = 0.7 if need_review else 0.9
        if not steps:
            steps = [
                PlannedStep(
                    intent="understand_and_execute",
                    target_semantics=text,
                    visual_hints=["根据当前页面视觉信息寻找与测试意图匹配的目标"],
                    expected_state="完成自然语言描述的用户任务",
                )
            ]

        return CasePlanningResult(
            title=self._title_from_text(text),
            goal=self._goal_from_text(text, steps),
            preconditions=["用户已登录"] if self._mapper.has(concepts, "login") else ["满足业务前置条件"],
            pages=self._pages(concepts),
            steps=steps,
            assertions=[steps[-1].expected_state],
            fallback_strategy=[
                "目标入口不可见时滚动查找",
                "页面跳转失败时基于 Page Graph 重新规划路径",
                "控件名称不一致时使用同义词和历史执行经验匹配",
                "断言低置信度时输出 UNKNOWN 并进入人工复核",
            ],
            confidence=confidence,
            need_human_review=need_review,
            planner_provider="mock_semantic_llm",
            prompt_version="case-planning-v2",
            raw_reasoning_summary="基于语义概念映射模拟 LLM 对模糊表达、动作意图和断言目标的规划。",
            extracted_entities={
                "concepts": sorted(concepts.keys()),
                "matched_aliases": concepts,
            },
        )

    def _compose_steps(self, text: str, concepts: Dict[str, List[str]]) -> List[PlannedStep]:
        steps: List[PlannedStep] = []
        if self._mapper.has(concepts, "mine"):
            steps.append(
                PlannedStep(
                    intent="navigate",
                    target_semantics="我的页面",
                    visual_hints=["底部导航", "我的", "头像", "个人信息区域"],
                    expected_state="当前页面为我的页面",
                )
            )
        if self._mapper.has(concepts, "settings") or self._mapper.has(concepts, "notification"):
            steps.append(
                PlannedStep(
                    intent="tap",
                    target_semantics="设置入口",
                    visual_hints=["设置", "齿轮图标", "偏好设置", "开关列表"],
                    expected_state="进入设置页面",
                )
            )
        if self._mapper.has(concepts, "notification") and self._mapper.has(concepts, "disable"):
            steps.append(
                PlannedStep(
                    intent="set_toggle",
                    target_semantics="通知/消息提醒开关",
                    visual_hints=["通知", "消息提醒", "推送", "开关控件", "勿扰相关入口"],
                    expected_state="off",
                )
            )
        if self._mapper.has(concepts, "verify") or self._mapper.has(concepts, "persist"):
            expected = "通知/消息提醒开关仍为关闭" if self._mapper.has(concepts, "notification") else "实际结果符合预期"
            steps.append(
                PlannedStep(
                    intent="verify",
                    target_semantics="目标状态保留",
                    visual_hints=["目标控件", "预期状态", "重新进入页面后的状态"],
                    expected_state=expected,
                )
            )
        return steps

    def _pages(self, concepts: Dict[str, List[str]]) -> List[Dict[str, List[str]]]:
        pages = []
        if self._mapper.has(concepts, "mine"):
            pages.append({"name": "我的", "aliases": ["我的", "个人中心", "账号页", "Mine"]})
        if self._mapper.has(concepts, "settings") or self._mapper.has(concepts, "notification"):
            pages.append({"name": "设置", "aliases": ["设置", "系统设置", "偏好设置", "Settings", "齿轮"]})
        return pages

    def _title_from_text(self, text: str) -> str:
        title = re.sub(r"[，。,.]", " ", text).strip()
        return title[:40] or "自然语言 GUI Agent 用例"

    def _goal_from_text(self, text: str, steps: List[PlannedStep]) -> str:
        if steps:
            return steps[-1].expected_state
        return self._title_from_text(text)


class MockPRDPlanningLLM:
    """Dependency-free PRD planner that uses the same semantic boundary as LLM."""

    def __init__(self, mapper: SemanticConceptMapper = None):
        self._mapper = mapper or SemanticConceptMapper()

    def plan_prd(self, prd_text: str) -> PRDPlanningResult:
        concepts = self._mapper.detect(prd_text)
        feature = "设置页通知/消息提醒开关" if "notification" in concepts else self._fallback_feature(prd_text)
        keywords = self._keywords(concepts)
        risk_points = self._risk_points(concepts)
        blueprints = self._blueprints(feature, concepts)
        return PRDPlanningResult(
            feature=feature,
            summary=f"围绕{feature}生成 GUI Agent 与后台自动化测试点",
            keywords=keywords,
            risk_points=risk_points,
            test_blueprints=blueprints,
            confidence=0.88 if keywords else 0.68,
            need_human_review=not keywords,
            planner_provider="mock_semantic_llm",
            prompt_version="prd-test-design-v2",
        )

    def _keywords(self, concepts: Dict[str, List[str]]) -> List[str]:
        concept_keywords = {
            "notification": "通知/消息提醒",
            "settings": "设置页",
            "disable": "关闭/禁用",
            "persist": "状态持久化",
            "failure": "异常失败处理",
            "login": "登录态",
        }
        return [concept_keywords[name] for name in concept_keywords if name in concepts]

    def _risk_points(self, concepts: Dict[str, List[str]]) -> List[str]:
        risks = []
        if "persist" in concepts:
            risks.append("状态未持久化或重新进入后恢复默认值")
        if "failure" in concepts:
            risks.append("保存失败时提示缺失或状态未回滚")
        if "notification" in concepts:
            risks.append("前端开关状态与后台推送状态不一致")
        return risks or ["需求描述缺少明确断言，需要人工确认风险点"]

    def _blueprints(self, feature: str, concepts: Dict[str, List[str]]) -> List[TestPointBlueprint]:
        blueprints = [
            TestPointBlueprint(
                point_type="functional",
                priority="P0",
                title=f"{feature}基础功能验证",
                precondition="用户已登录且具备功能入口",
                steps=["进入目标页面", "根据 PRD 操作目标控件", "观察页面状态"],
                expected="页面状态符合 PRD 描述",
                data_requirement="正常测试账号",
                automation_type="GUI_AGENT",
                risk_level="high",
                source="PRD_LLM",
            )
        ]
        if "persist" in concepts:
            blueprints.append(
                TestPointBlueprint(
                    point_type="boundary",
                    priority="P0",
                    title=f"{feature}状态持久化验证",
                    precondition="目标状态已被修改",
                    steps=["修改目标状态", "重启 App 或重新登录", "重新进入目标页面"],
                    expected="目标状态保持不变",
                    data_requirement="同一登录账号",
                    automation_type="GUI_AGENT",
                    risk_level="high",
                    source="PRD_LLM + HISTORY_BUG",
                )
            )
        if "failure" in concepts:
            blueprints.append(
                TestPointBlueprint(
                    point_type="exception",
                    priority="P1",
                    title=f"{feature}异常失败处理验证",
                    precondition="测试环境可模拟接口失败或弱网",
                    steps=["进入目标页面", "触发目标操作", "模拟接口失败或弱网"],
                    expected="展示明确错误提示，并保持或回滚到合理状态",
                    data_requirement="可控 Mock 或测试环境",
                    automation_type="BACKEND_AUTOMATION",
                    risk_level="medium",
                    source="PRD_LLM + TEST_SPEC",
                )
            )
        return blueprints

    def _fallback_feature(self, text: str) -> str:
        matches = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
        return matches[0] if matches else "PRD 功能点"
