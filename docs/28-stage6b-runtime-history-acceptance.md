# Stage 6B Runtime Persistence & History Acceptance

日期：2026-10-04。状态：技术验收完成；等待 Owner 确认是否正式关闭 Stage 6。

## 契约与接入

- 复核 Stage 6A 的 `DiagnosisRun v1`、SQLAlchemy Repository、versioned IncidentDiagnosis/DiagnosisTrace 快照和独立 `run_id`。已有 Markdown、结构化诊断、Trace 与来源 ID 足以阅读一次诊断的结论和过程，因此本批不复制完整日志、指标载荷、Runbook 或 Prompt，也不改写 v1 契约。
- Operational Evidence 历史引用仅存 `evidence_id/source_type`，Knowledge 仅存 `document_id/chunk_id/source_ref`。若源数据被改写或删除，历史页不能完整重建原始证据正文；Stage 7 展示必须保留这一限制，不得伪装为不可变审计档案。
- 仅在普通 `/chat` 获得 `DiagnosisOutcome` 后，调用 `build_diagnosis_run` 并在线程中保存。DiagnosisPipeline、Agent、Assembler、Tool、RAG 和共享 `run_diagnosis` 均不依赖数据库；`/eval/run` 不写普通历史。
- `ChatResponse` 兼容增加 `run_id` 与 `persistence_status=saved|failed|disabled`。只有提交成功才返回可查的 `run_id`；数据库初始化或写入失败时仍返回原诊断，状态为 `failed`，不把 SQL 错误、路径或堆栈发给客户端。澄清、部分工具失败、Agent 降级和结构化构建失败但有 Markdown 的结果同样可保存。

## 历史访问与隐私

- `GET /diagnoses` 返回轻量分页列表，支持 `limit` (1-100)、`offset`、`service_name`、`diagnosis_status`、`degraded`，默认按创建时间倒序。`GET /diagnoses/{run_id}` 返回详情但不包含完整 Trace；`GET /diagnoses/{run_id}/trace` 单独返回 Stage 5 的 allowlisted Trace。未知记录返回 404，未知快照 schema 返回 409，存储故障返回安全的 503。
- 历史 API 默认关闭。启用时还要求不少于 32 字符的 `ROOTLENS_HISTORY_API_TOKEN`，三个接口均用 `X-RootLens-History-Token` 校验；未授权返回 401。当前本地 `.env` 为验收显式开启，密钥不提交 Git，也不写入本报告。
- 写库前对整个记录的序列化内容检查常见 credential-like 形式（password/API key/Authorization/Bearer/中文密码赋值）；命中时拒绝保存，`/chat` 仍正常返回且 `run_id=null`。这是保守保护而非通用 DLP，其他自由文本敏感信息仍可能存在。历史列表、详情和 Trace 只适合本机/私有演示；共享 token 不是用户级鉴权，当前 HTTP 也未配置 TLS 或租户隔离，不能直接公开到生产网络。

## Docker 与测试

- 本地默认 SQLite URL 可配置；Compose 使用 `sqlite:////app/data/history/diagnoses.sqlite3` 与独立 `rootlens-history` named volume。Dockerfile 预建可写目录。测试只用临时库和隔离 Redis，不触碰正式运行库。`docker compose config --quiet` 通过。
- Stage 6B 新增 13 项确定性测试：普通/澄清/降级/结构化失败保存、数据库失败不影响响应、分页过滤、详情与 Trace 分离、权限与未知 schema、评测隔离、重开 Repository 后可读，以及 4 类凭据拒绝持久化。加上既有 Stage 1-6A，完整离线回归 **316 passed、0 skipped**。
- 首次测试容器因生产镜像按原规则排除 `datasets/evaluation/`，出现缺少评测文件的失败；只在临时测试容器中只读挂载该目录后恢复。正式镜像仍不含 expected labels。隔离测试 Redis 容器和网络已清理。
- 真实模型仅做一次普通 `/chat` smoke：HTTP 200，`deployment_issue`、Application 主、Database 辅，`persistence_status=saved`，`run_id=96d7ca76967b49a1809dbf67accd27be`，结构化诊断成功。历史列表、详情和 13 步 Trace 与该 run 对应；详情不内联 Trace。无再次运行六案例 Judge。
- `rootlens-app` 重启和镜像重新部署后，同一记录仍可经 8100 与 Nginx 8081 读回。应用容器重建后 Nginx 曾沿用旧 upstream，单独重启 Nginx 后代理恢复；现五个 Compose 服务均健康。
- Stage 5 approved baseline `f79e1d913c7146088805290f7e1580e3` 的历史快照 SHA-256 保持 `821F49BA337447CFB6AEBDDC6AE6334C4D7475919DD13B02D32651CC6816AC1F`；本批未修改 suite、dataset、Judge、Router、RAG 或 Agent。

## 结论与边界

Stage 6B 的运行时保存、失败隔离、History API、访问边界、Docker 重启持久性、评测隔离与离线回归均已验证，无已知 Stage 6 blocker。**建议 Owner 审阅后正式关闭 Stage 6**，不自动进入 Stage 7。

当前仍是单机 SQLite 和共享演示 token，没有迁移系统、按用户授权、TLS、生产负载测试或跨进程/磁盘故障研究。History API 的 token 只解决本地私有演示的基本访问边界，不应宣传为生产级认证。六案例评测仍是模拟数据，不代表生产准确率。
