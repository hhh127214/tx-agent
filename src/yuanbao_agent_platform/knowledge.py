from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List

from yuanbao_agent_platform.models import KnowledgeChunk, RetrievedKnowledge


def tokenize(text: str) -> List[str]:
    text = text.lower()
    latin = re.findall(r"[a-z0-9_]+", text)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = [text[index : index + 2] for index in range(max(0, len(text) - 1))]
    return [token for token in latin + cjk + bigrams if token.strip()]


class HybridKnowledgeBase:
    def __init__(self, chunks: Iterable[KnowledgeChunk]):
        self._chunks = list(chunks)
        self._documents = [tokenize(chunk.title + " " + chunk.content + " " + " ".join(chunk.tags)) for chunk in self._chunks]
        self._document_frequency = Counter()
        for tokens in self._documents:
            self._document_frequency.update(set(tokens))

    def search(self, query: str, top_k: int = 5) -> List[RetrievedKnowledge]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored = []
        for chunk, tokens in zip(self._chunks, self._documents):
            bm25_score = self._bm25(query_tokens, tokens)
            semantic_score = self._jaccard(query_tokens, tokens)
            tag_boost = 0.15 if set(query_tokens) & set(tokenize(" ".join(chunk.tags))) else 0
            score = bm25_score * 0.65 + semantic_score * 0.35 + tag_boost
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedKnowledge(
                source_type=chunk.source_type,
                source_id=chunk.chunk_id,
                title=chunk.title,
                score=round(score, 4),
                reason=self._reason(query_tokens, chunk),
            )
            for score, chunk in scored[:top_k]
        ]

    def _bm25(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        if not doc_tokens:
            return 0
        avgdl = sum(len(document) for document in self._documents) / max(1, len(self._documents))
        frequencies = Counter(doc_tokens)
        score = 0.0
        k1 = 1.5
        b = 0.75
        for token in query_tokens:
            doc_frequency = self._document_frequency.get(token, 0)
            if doc_frequency == 0:
                continue
            idf = math.log(1 + (len(self._documents) - doc_frequency + 0.5) / (doc_frequency + 0.5))
            term_frequency = frequencies[token]
            numerator = term_frequency * (k1 + 1)
            denominator = term_frequency + k1 * (1 - b + b * len(doc_tokens) / avgdl)
            score += idf * numerator / max(denominator, 1e-6)
        return score

    def _jaccard(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        query_set = set(query_tokens)
        doc_set = set(doc_tokens)
        return len(query_set & doc_set) / max(1, len(query_set | doc_set))

    def _reason(self, query_tokens: List[str], chunk: KnowledgeChunk) -> str:
        content_tokens = set(tokenize(chunk.title + " " + chunk.content + " " + " ".join(chunk.tags)))
        hits = [token for token in query_tokens if token in content_tokens][:5]
        return "命中关键词: " + ", ".join(hits) if hits else "语义相似召回"


def default_knowledge_base() -> HybridKnowledgeBase:
    return HybridKnowledgeBase(
        [
            KnowledgeChunk(
                chunk_id="BUG-1024",
                source_type="HISTORY_BUG",
                title="关闭通知后重新进入设置页状态恢复为开启",
                content="设置页开关状态未持久化，重启 App 或重新登录后状态恢复，需验证前后端一致性。",
                tags=["设置", "通知", "开关", "状态持久化", "回归"],
            ),
            KnowledgeChunk(
                chunk_id="BUG-1142",
                source_type="HISTORY_BUG",
                title="弱网下保存设置失败但页面未提示",
                content="用户切换设置项后接口超时，页面保持加载状态且未回滚，需覆盖失败提示和原状态保持。",
                tags=["弱网", "保存失败", "设置", "异常提示"],
            ),
            KnowledgeChunk(
                chunk_id="BUG-2031",
                source_type="HISTORY_BUG",
                title="搜索结果点击后跳转到空白页",
                content="搜索结果列表首条点击后目标页白屏，需覆盖列表展示、点击跳转、返回和空结果。",
                tags=["搜索", "结果列表", "跳转", "白屏"],
            ),
            KnowledgeChunk(
                chunk_id="BUG-3108",
                source_type="HISTORY_BUG",
                title="会员价格文案与后台权益接口不一致",
                content="会员中心展示价格与权益接口返回不一致，需校验 UI 文案、后台接口和续费入口。",
                tags=["会员", "权益", "价格", "接口一致性"],
            ),
            KnowledgeChunk(
                chunk_id="BUG-4102",
                source_type="HISTORY_BUG",
                title="历史记录删除后刷新又出现",
                content="历史记录删除只更新本地列表，刷新后服务端记录仍返回，需校验删除接口和 UI 刷新状态。",
                tags=["历史记录", "删除", "刷新", "数据一致性"],
            ),
            KnowledgeChunk(
                chunk_id="SPEC-SETTING-TOGGLE",
                source_type="TEST_SPEC",
                title="设置项开关类功能测试规范",
                content="开关类功能需要覆盖默认态、切换态、保存失败回滚、重新进入、弱网和多端一致性。",
                tags=["测试规范", "开关", "异常", "边界"],
            ),
            KnowledgeChunk(
                chunk_id="SPEC-SEARCH",
                source_type="TEST_SPEC",
                title="搜索功能测试规范",
                content="搜索需覆盖输入联想、结果列表、无结果、特殊字符、历史搜索、点击跳转和返回恢复。",
                tags=["测试规范", "搜索", "列表", "边界"],
            ),
            KnowledgeChunk(
                chunk_id="SPEC-MEMBER",
                source_type="TEST_SPEC",
                title="会员权益测试规范",
                content="会员功能需覆盖价格文案、权益说明、续费入口、支付失败、登录态和后台接口一致性。",
                tags=["测试规范", "会员", "支付", "权益"],
            ),
            KnowledgeChunk(
                chunk_id="SPEC-DATA-CONSISTENCY",
                source_type="TEST_SPEC",
                title="前后台数据一致性测试规范",
                content="涉及状态变更、删除、保存的功能需同时校验 UI 展示、接口返回和刷新后的持久化状态。",
                tags=["数据一致性", "后台自动化", "持久化"],
            ),
            KnowledgeChunk(
                chunk_id="API-DOC-NOTIFICATION-001",
                source_type="INTERFACE_DOC",
                title="通知设置状态查询接口文档",
                content=(
                    "GET /api/settings/notification 返回通知开关状态，响应字段包含 status、"
                    "notification_enabled 和 source。通知设置 PRD 或 BUG 回归执行后，需要用该接口"
                    "复核 GUI 操作后的后台持久化状态。"
                ),
                tags=["接口文档", "通知", "设置", "Backend API", "前后台一致性"],
            ),
            KnowledgeChunk(
                chunk_id="CASE-LOGIN-001",
                source_type="HISTORY_CASE",
                title="登录后进入我的页面",
                content="用户登录后可通过底部导航进入我的页面，再进入设置页面修改个人配置。",
                tags=["登录", "我的", "设置", "页面路径"],
            ),
            KnowledgeChunk(
                chunk_id="CASE-SEARCH-001",
                source_type="HISTORY_CASE",
                title="搜索页输入关键词并打开结果",
                content="进入搜索页，输入关键词，等待结果列表出现，点击第一条结果并验证详情页展示。",
                tags=["搜索", "输入", "结果", "详情页"],
            ),
            KnowledgeChunk(
                chunk_id="CASE-MEMBER-001",
                source_type="HISTORY_CASE",
                title="会员中心权益说明展示",
                content="进入会员中心，打开权益说明，检查权益项、价格文案、续费入口和登录态提示。",
                tags=["会员", "权益", "价格", "续费"],
            ),
        ]
    )
