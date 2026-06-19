# 外部真实接入替代验收方案

## 定位

公司内网元宝环境、设备池、GUI Agent 服务、CI/CD、缺陷系统和需求系统通常需要导师或公司授权。若暂时拿不到权限，本项目提供一个外部可验证替代方案，用于证明平台具备真实接入能力，而不是只停留在 InMemory Mock。

## 替代接入组合

| 验收对象 | 替代实现 | 真实性说明 |
| --- | --- | --- |
| 真实 GUI 业务系统 | `yuanbao_agent_platform.demo_web` | 启动本地 HTTP Web 系统，真实访问登录、搜索、购物车、设置页 |
| CI/CD 系统 | GitHub Actions | `.github/workflows/agent-self-test.yml` 支持 push 和 workflow_dispatch |
| 缺陷系统 | GitHub Issues Adapter | 配置 `GITHUB_REPOSITORY` + `GITHUB_TOKEN` 后可调用 GitHub Issues API；未配置时输出 dry-run payload |
| 需求系统 | Markdown PRD Adapter | 从 `docs/prd/external_demo_prd.md` 读取真实 PRD 文件并生成测试点 |

## 端到端闭环

```text
Markdown PRD
  -> PRD Test Design Agent
  -> 测试点 JSON
  -> GitHub Actions 触发开发自测
  -> 本地真实 Web Demo 执行 GUI 场景
  -> GitHub Issues 拉取待回归 BUG / 回写评论 payload
  -> 平台调度四方向任务
  -> 输出 external_substitute_acceptance_report
```

## 运行方式

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_external_acceptance
```

或启动 API 后调用：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/acceptance/external-substitute
```

## 与真实元宝接入的边界

该方案可以证明真实 Web、真实 CI workflow 文件、真实 GitHub API 边界、真实 PRD 文件读取和平台四方向调度闭环。它不能替代公司内部元宝业务验收；接入公司内网时仍需替换为真实元宝环境、设备池、GUI Agent 服务、CI/CD endpoint、缺陷系统和需求平台权限。
