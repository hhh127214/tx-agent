# 元宝 GUI Agent 测试平台 MVP

这是一个无外部依赖的工程 MVP，落地了元宝测试 Agent 平台的核心链路：

- Vision-Based GUI Agent 语义用例转换
- 多场景执行调度与资源配额
- BUG 回归三态回写模型
- PRD + 知识库混合召回生成测试点
- 后台自动化执行器占位实现
- Mock GUI Agent 执行截图证据落盘

## 快速运行

```powershell
$env:PYTHONPATH="src"
python -m yuanbao_agent_platform.cli
```

## 启动 HTTP API

```powershell
$env:PYTHONPATH="src"
python -m yuanbao_agent_platform.api
```

默认监听 `http://127.0.0.1:8000`，可用接口：

- `GET /health`
- `GET /scheduler/policy`
- `GET /metrics`
- `GET /integrations`
- `GET /adapters/health`
- `GET /acceptance/report`
- `GET /storage/stats`
- `POST /cases/convert`
- `POST /prd/test-points`
- `POST /bugs/regress`
- `POST /tasks/manual`
- `POST /tasks/run`
- `POST /demo`
- `POST /demo/large-scale`
- `POST /webhooks/bug-status-changed`
- `POST /webhooks/ci-finished`

示例：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/cases/convert -ContentType "application/json" -Body '{"case_id":"case-001","text":"登录后进入我的页面，点击设置，关闭通知开关，验证开关状态保留。"}'
```

查看调度策略：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/scheduler/policy
```

运行完整 Demo：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/demo
```

运行大规模混合调度 Demo：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/demo/large-scale -ContentType "application/json" -Body '{"total":10000,"max_workers":32}'
```

模拟缺陷状态变更触发：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/webhooks/bug-status-changed -ContentType "application/json" -Body '{"bug_id":"BUG-1024","title":"关闭通知开关后重新进入设置页仍显示开启","status":"待回归","severity":"P1","version":"8.1.1","steps":["登录账号","进入我的页面","点击设置","关闭通知开关","退出设置页后重新进入"],"expected":"通知开关保持关闭","actual":"通知开关重新变为开启"}'
```

模拟 CI 构建完成触发：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/webhooks/ci-finished -ContentType "application/json" -Body '{"pipeline_id":"pipeline-001","commit_sha":"abc123","artifact":"yuanbao-debug.apk","run_immediately":true}'
```

查看验收报告：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/acceptance/report
```

查看 Mock GUI Agent 执行证据：

```powershell
Get-ChildItem -Recurse artifacts/screenshots
```

说明：`artifacts/screenshots/{task_id}/step-{n}-observe.png` 是 MVP 生成的可追溯执行证据文件，用于模拟真实设备/VLM 服务返回的截图产物形态；它不是物理设备实时截图。

## 运行测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

## 目录

- `src/yuanbao_agent_platform/models.py`：核心数据模型
- `src/yuanbao_agent_platform/agents.py`：用例理解、BUG 解析、PRD 测试点生成
- `src/yuanbao_agent_platform/scheduler.py`：多场景调度、资源、重试、隔离
- `src/yuanbao_agent_platform/executors.py`：GUI Agent 与后台自动化执行器模拟
- `src/yuanbao_agent_platform/vlm.py`：VLM/GUI Agent 客户端协议、Mock 截图证据、真实服务接口骨架
- `src/yuanbao_agent_platform/platform.py`：平台门面，串联端到端流程
- `src/yuanbao_agent_platform/storage.py`：SQLite 持久化
- `src/yuanbao_agent_platform/acceptance.py`：验收报告生成
- `docs/current_engineering_state.md`：当前工程状态与验收覆盖说明
- `tests/`：核心能力测试
