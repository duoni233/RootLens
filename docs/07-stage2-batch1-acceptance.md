# Stage 2 第 1 批：证据层验收与学习入口

日期：2026-09-29。结论：本批通过，可以进入第 2 批；整个 Stage 2 尚未完成。

## 本次做到了什么

```text
明确服务 + 环境 + 完整时间
  -> QueryContext 算出三个查询窗口
  -> 注册到既有 MCPToolManager
  -> query_logs / query_metrics / query_deployments
  -> runtime 文件中的源记录
  -> 严格校验、范围筛选、稳定 ID、来源引用
  -> ToolResult.data
  -> EvidenceBundle：证据 + 每个工具状态
```

这是新业务能力，不是重写原运行时。没有接 Agent、Router、Intent、RAG、Memory、Trace、数据库或前端；`api/main.py` 和原 ToolManager 未修改，当前 /chat 不会调用这些新工具。

## 文件与用途

| 文件 | 为什么新增/修改 |
| --- | --- |
| `app/core/evidence.py` | Pydantic 契约、窗口、类型化源记录、现场 Evidence、Bundle 及范围校验 |
| `app/mcp/incident_tools.py` | 只读 runtime loader、来源解析、三个 async handler 和 register；沿用 call 的可靠性框架 |
| `app/datasets/runtime/manifest.json` | 声明数据集 ID/版本、模拟性质、时区、允许的事件目录，不含答案 |
| `app/datasets/runtime/INC-001/*.json` | 一致的模拟日志/指标/发布，含服务/环境/时间边界对照记录 |
| `app/datasets/evaluation/INC-001.expected.json` | 单独的评测答案文件，仅用于测试，不被 runtime 读取 |
| `app/test_rootlens_evidence.py` | 新增 37 项确定性测试，无模型调用 |
| `app/tools/demo_incident_evidence.py` | 独立跑三个工具，打印真实 Bundle，便于学习 |
| `app/requirements-test.txt` | 复用生产依赖，增加 pytest；Windows 时区需要 tzdata |
| `app/.dockerignore` | 唯一部署相关改动：禁止 evaluation 数据进入后续应用构建上下文 |
| `docs/03-progress.md`、`06-stage2-design-v0.1.md`、本文 | 记录边界、评审和验收，防止把计划误认为已完成 |

未改 .env、Compose、Dockerfile，也没有重启现有 RootLens/EchoMind。没有提交 API Key 或依赖缓存。

## 数据目录

```text
app/datasets/
  runtime/
    manifest.json
    INC-001/
      logs.json
      metrics.json
      deployments.json
  evaluation/
    INC-001.expected.json
```

所有数据均为模拟。日志/发布是点事件，指标是区间聚合；指标必须整个区间落在查询范围，避免部分区间数据被当作完整事实。

## 输入输出示例

共同条件：payment-service、demo、2026-09-01 10:05:00+08:00、Asia/Shanghai、rootlens-demo v1。

| 工具 | 自动输入窗口（含边界） | 实际输出 |
| --- | --- | --- |
| query_logs | 10:00 至 10:20 | L003、L001、L002、L004；L001 在 10:05:12 出现 DBConnectionError / connection pool exhausted |
| query_metrics | 10:00 至 10:20 | M001、M002、M003；5xx 从 0.1% 升至 28%，池使用量 20 connections |
| query_deployments | 09:05 至 10:05 | D002（09:05 v2.3.6）、D001（10:00 v2.3.7）；未来发布排除 |

调用方式示意：

```python
tools = IncidentTools()
tools.register(manager)  # manager 是现有 MCPToolManager 实例
params = query_context.tool_params("query_logs")
result = await manager.call("query_logs", params)
```

一条日志证据的关键字段：

```json
{
  "evidence_category": "operational",
  "source_type": "log",
  "evidence_id": "rootlens-demo:v1:INC-001:log:L001",
  "observed_at": "2026-09-01T10:05:12+08:00",
  "raw_ref": "INC-001/logs.json#L001"
}
```

实际对象还包含 retrieved_at、服务/环境、summary、结构化 attributes、数据集版本。`resolve_raw_ref` 可以回到原记录。重复查询保持 evidence_id 不变；重新取证可改变 retrieved_at，缓存命中则保留原取证时间。

Evidence 当前只允许 operational 类型，runbook/knowledge 被拒绝。knowledge 类别仅预留，不会参与本批 Bundle。

## 测试结果

- Stage 1：15 项回归全部通过，原测试未改。
- Stage 2：37 项全部通过，包括参数/日期/时区校验、服务/环境/窗口、完整指标区间、向前发布检索、筛选/limit、稳定 ID/raw_ref、缓存时间、空结果与失败、降级不制造事实、部分证据、去重、跨目录/符号链接越界、答案隔离、既有 timeout/breaker。
- 合计：52 passed in 2.88s，无跳过。
- 独立演示：9 条 Evidence，三个工具均为 ok，不联网、不调用模型。
- 额外预防：源记录若混入 expected_diagnosis 等未定义字段，Pydantic 拒绝整次查询，不悄悄接受。

“未知服务”使用正常空结果，不伪装成工具故障；错误参数/坏文件/超时返回失败。原框架 success=True + error 非空的降级结果被 Bundle 标 degraded，不进入现场证据。

## 测试环境与重跑

本机 Python 3.9.12 缺 Pydantic，pip HTTPS 下载中断；E:\code\RootLens\.venv 已创建，但本地依赖安装未完成，不能宣称本机虚拟环境已可用。

实际使用已有 rootlens-echomind 镜像的 Python 3.12 / Pydantic 2.10.3，在一次性容器离线测试；不是运行中的 rootlens-app。pytest 下载到 E:\Codex\cache\pip\test-wheels，临时文件放 E:\Codex\temp\rootlens-stage2。证书校验未关闭，系统代理未修改。

以下命令在 PowerShell 使用已有镜像和本次 wheel 缓存；源码只读挂载、测试容器断网：

```powershell
cd E:\code\RootLens
docker run --rm --network none --entrypoint python --mount 'type=bind,source=E:\code\RootLens\app,target=/workspace,readonly' --mount 'type=bind,source=E:\Codex\cache\pip\test-wheels,target=/wheels,readonly' --mount 'type=bind,source=E:\Codex\temp\rootlens-stage2,target=/test-temp' -w /workspace -e PYTHONDONTWRITEBYTECODE=1 -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -e TMPDIR=/test-temp rootlens-echomind -c "import subprocess,sys; subprocess.run([sys.executable,'-m','pip','install','--no-index','--no-cache-dir','--find-links=/wheels','pytest==8.3.4'],check=True); sys.exit(subprocess.call([sys.executable,'-m','pytest','-q','--capture=sys','-p','no:cacheprovider','--basetemp=/test-temp/pytest','test_rootlens_first_slice.py','test_rootlens_evidence.py']))"
```

只看工具输出，不需要安装 pytest：

```powershell
docker run --rm --network none --entrypoint python --mount 'type=bind,source=E:\code\RootLens\app,target=/workspace,readonly' -w /workspace -e PYTHONDONTWRITEBYTECODE=1 rootlens-echomind -m tools.demo_incident_evidence
```

## 尚未验证 / 尚未实现

工具注册验证是在独立 MCPToolManager 中完成，尚未放入 lifespan。没有真实日志平台/Prometheus 发布接口，没有 Agent 证据消费、证据评分、RootLens RAG、Memory 隔离、HTTP 集成或根因准确率评测。

.dockerignore 已配置答案隔离，但本批未重新构建应用镜像，未执行镜像内容验收。下一次部署前必须检查 evaluation 文件确实不在镜像内。

只读模拟快照以 dataset_version 管理缓存；修改 runtime 数据时必须更新版本并重新创建 loader/manager，不能在旧版本下修改文件却期待缓存自动失效。

## 下一步与学习顺序

建议进入 Stage 2 第 2 批：RootLens 知识集合 + Runbook + 必要 RAG 兼容 + Memory 隔离。不要直接跳到前端或诊断阈值优化。

学习时先看 demo 的 ctx/tool_params，再看 incident_tools 的 _query，最后看 Bundle 如何区分 ok/empty/failed/degraded。当前最重要的是能解释“什么条件、什么时间范围、为什么只返回这些记录”，不必一次背下所有字段。
