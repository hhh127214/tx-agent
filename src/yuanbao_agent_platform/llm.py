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


class CasePlanningLLM(Protocol):
    def plan_case(self, case_text: str) -> CasePlanningResult:
        """Convert natural language test case into semantic GUI Agent steps."""


class MockCasePlanningLLM:
    """Deterministic local LLM adapter.

    The implementation is intentionally dependency-free, but the boundary is the
    same place where a real internal LLM service would be called in production.
    """

    def plan_case(self, case_text: str) -> CasePlanningResult:
        text = case_text.strip()
        entities = self._extract_entities(text)
        steps = self._compose_steps(text, entities)
        need_review = not steps or "不明确" in text or "随便" in text
        confidence = 0.72 if need_review else 0.88
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
            goal=self._goal_from_text(text),
            preconditions=self._preconditions(text),
            pages=self._pages(entities),
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
            planner_provider="mock_llm",
            prompt_version="case-planning-v1",
            raw_reasoning_summary="模拟 LLM 从用例文本中抽取页面、动作、控件语义和断言点。",
            extracted_entities=entities,
        )

    def _extract_entities(self, text: str) -> Dict[str, List[str]]:
        page_candidates = {
            "我的": ["我的", "个人中心", "Mine"],
            "设置": ["设置", "系统设置", "Settings", "齿轮"],
        }
        action_candidates = {
            "登录": ["登录", "登陆"],
            "点击": ["点击", "进入", "打开"],
            "关闭": ["关闭", "关掉", "禁用"],
            "验证": ["验证", "检查", "确认", "保持", "保留"],
        }
        target_candidates = {
            "通知开关": ["通知", "消息提醒", "推送通知", "开关"],
            "设置入口": ["设置", "齿轮"],
        }
        return {
            "pages": [name for name, aliases in page_candidates.items() if any(alias in text for alias in aliases)],
            "actions": [name for name, aliases in action_candidates.items() if any(alias in text for alias in aliases)],
            "targets": [name for name, aliases in target_candidates.items() if any(alias in text for alias in aliases)],
        }

    def _compose_steps(self, text: str, entities: Dict[str, List[str]]) -> List[PlannedStep]:
        steps: List[PlannedStep] = []
        if "我的" in entities["pages"]:
            steps.append(
                PlannedStep(
                    intent="navigate",
                    target_semantics="我的页面",
                    visual_hints=["底部导航", "我的", "头像", "个人信息区域"],
                    expected_state="当前页面为我的页面",
                )
            )
        if "设置" in entities["pages"] or "设置入口" in entities["targets"]:
            steps.append(
                PlannedStep(
                    intent="tap",
                    target_semantics="设置入口",
                    visual_hints=["设置", "齿轮图标", "列表项"],
                    expected_state="进入设置页面",
                )
            )
        if "通知开关" in entities["targets"] and "关闭" in entities["actions"]:
            steps.append(
                PlannedStep(
                    intent="set_toggle",
                    target_semantics="通知开关",
                    visual_hints=["通知", "消息提醒", "推送通知", "开关控件"],
                    expected_state="off",
                )
            )
        if "验证" in entities["actions"] or "保持" in text or "保留" in text:
            target = "通知开关状态保留" if "通知开关" in entities["targets"] else "目标状态符合预期"
            expected = "通知开关仍为关闭" if "通知开关" in entities["targets"] else "实际结果符合预期"
            steps.append(
                PlannedStep(
                    intent="verify",
                    target_semantics=target,
                    visual_hints=["目标控件", "预期状态", "重新进入页面后的状态"],
                    expected_state=expected,
                )
            )
        return steps

    def _preconditions(self, text: str) -> List[str]:
        if "登录" in text or "登陆" in text:
            return ["用户已登录"]
        return ["满足业务前置条件"]

    def _pages(self, entities: Dict[str, List[str]]) -> List[Dict[str, List[str]]]:
        aliases = {
            "我的": ["我的", "个人中心", "Mine"],
            "设置": ["设置", "系统设置", "Settings", "齿轮"],
        }
        return [{"name": page, "aliases": aliases[page]} for page in entities["pages"] if page in aliases]

    def _title_from_text(self, text: str) -> str:
        title = re.sub(r"[，。,.]", " ", text).strip()
        return title[:40] or "自然语言 GUI Agent 用例"

    def _goal_from_text(self, text: str) -> str:
        if "验证" in text:
            return text[text.index("验证") :].strip("，。,.")
        return self._title_from_text(text)
