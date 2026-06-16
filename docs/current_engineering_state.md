# 元宝 GUI Agent 测试平台当前工程状态

## 当前定位

本仓库是一个可运行的测试 Agent 平台 MVP。它不是公司内网生产系统，但已经把生产系统应有的关键边界落成代码：

- LLM 用例规划接口
- VLM 视觉执行接口
- 多场景并发调度
- 系统适配器注册
- SQLite 持久化
- 验收报告自检
- PRD 知识库召回与测试点生成

## 核心链路

```text
PRD / 手工用例 / BUG / CI Webhook
  -> LLM Planner
  -> AgentPlan / TestPoint
  -> ThreadPool Scheduler
  -> VLM GUI Agent Adapter / Backend Executor
  -> Verification Result
  -> IntegrationHub Writeback
  -> SQLiteStore
  -> AcceptanceReporter
```

## 最新工程能力

| 能力 | 实现位置 | 说明 |
| --- | --- | --- |
| 语义化 LLM Mock | `src/yuanbao_agent_platform/llm.py` | 使用 `SemanticConceptMapper` 模拟模糊表达泛化，例如“叮叮咚咚老打扰”映射为通知类功能 |
| PRD LLM Planner | `src/yuanbao_agent_platform/llm.py`、`agents.py` | PRD 测试点生成也接入 `PRDPlanningLLM`，不再停留在关键词函数 |
| VLM Adapter | `src/yuanbao_agent_platform/vlm.py` | 基于视觉置信度、断言置信度和视觉不一致信号输出 PASS/FAIL/UNKNOWN |
| 并发调度 | `src/yuanbao_agent_platform/scheduler.py` | 使用 `ThreadPoolExecutor` 模拟 worker 池，支持大规模混合任务执行 |
| SQLite 持久化 | `src/yuanbao_agent_platform/storage.py` | 持久化任务、执行结果、回写记录和验收报告 |
| 系统适配器 | `src/yuanbao_agent_platform/adapters.py` | 提供 CI/CD、缺陷、需求管理三个 InMemory Adapter |
| 验收自检 | `src/yuanbao_agent_platform/acceptance.py` | 对照四方向端到端和至少两个系统对接生成验收报告 |
| 知识库召回 | `src/yuanbao_agent_platform/knowledge.py` | 包含设置、搜索、会员、历史记录等多业务知识样例 |

## 验收要求覆盖

### 1. 四类应用方向端到端打通

| 方向 | 当前样例业务 | 触发 | 回写 |
| --- | --- | --- | --- |
| 集成测试批量执行 | 搜索模块集成批量回归 | nightly batch | report_center |
| 开发自测 | 通知设置开发自测准入 | CI finished | ci_cd |
| 需求测试 | 会员权益需求验收测试 | requirement status changed | requirement_system |
| BUG 回归 | 通知开关状态持久化 BUG 回归 | bug status changed | bug_system |

这些样例定义在 `configs/business_acceptance.json`，运行 `GET /acceptance/report` 可看到逐项证据。

### 2. 至少完成两个系统对接

当前提供三个可替换适配器：

- `InMemoryCICDAdapter`
- `InMemoryBugSystemAdapter`
- `InMemoryRequirementAdapter`

它们是模拟内网适配器，不是公司真实系统。真实落地时需要替换 endpoint、鉴权、字段映射、Webhook 配置和测试账号。

## 运行方式

```powershell
cd C:\Users\17128\Documents\tx-yuanbao
$env:PYTHONPATH="src"
python -m yuanbao_agent_platform.cli
```

启动 API：

```powershell
$env:PYTHONPATH="src"
python -m yuanbao_agent_platform.api
```

关键接口：

- `GET /acceptance/report`
- `GET /storage/stats`
- `POST /demo/large-scale`
- `POST /webhooks/bug-status-changed`
- `POST /webhooks/ci-finished`

## 仍未完成的生产级能力

- 未接真实公司 GUI Agent / VLM 服务
- 未接真实 Android/iOS 设备池
- 未接真实 CI/CD、缺陷系统、需求系统 endpoint
- 未实现真实截图、录屏、点击、滑动
- 未实现鉴权、多租户、权限隔离

当前工程的价值是证明平台主链路、接口边界和验收证据均已具备。进入公司环境后，重点替换 Adapter，而不是重写调度、转换、回写和验收逻辑。
