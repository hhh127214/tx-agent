# 元宝 GUI Agent 测试平台 MVP

这是一个无外部依赖的工程 MVP，落地了元宝测试 Agent 平台的核心链路：

- Vision-Based GUI Agent 语义用例转换
- 多场景执行调度与资源配额
- BUG 回归三态回写模型
- PRD + 知识库混合召回生成测试点
- 后台自动化执行器占位实现

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
- `POST /cases/convert`
- `POST /prd/test-points`
- `POST /bugs/regress`
- `POST /tasks/manual`
- `POST /tasks/run`
- `POST /demo`

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
- `src/yuanbao_agent_platform/platform.py`：平台门面，串联端到端流程
- `tests/`：核心能力测试
