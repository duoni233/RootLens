# Stage 7 RootLens Diagnosis Console Acceptance

日期：2026-10-04。状态：控制台已实现并部署；用户反馈的澄清续接与连续提问已修复并复验，授权历史/Trace 的浏览器人工验收仍待确认。

## 实施前审计

- Stage 6 已由 Owner 人工关闭。仓库此前没有 frontend、React、Vite 或 Node 项目；本机 Node/npm 位于 D 盘。`/chat` 已返回 `IncidentDiagnosis v1`、`diagnosis_status`、取证 ID/工具状态、`run_id/persistence_status`；History API 返回轻量列表、详情及单独的 Trace，并默认关闭且需要 `X-RootLens-History-Token`。
- 现有 Nginx 代理所有后端路径，Compose 已有单独 Nginx、应用、Redis、Chroma、Prometheus 服务。Stage 7 不改后端诊断语义、数据集、Judge 或 baseline。

## 前端架构和页面

- `frontend/` 使用 React 18、TypeScript、Vite 5、React Router 6 和 Lucide。集中 API client 只在 History 请求加 token，统一处理 401/404/409/503/网络错误；错误文案不透出后端响应体。原始 Markdown 以纯文本 `<pre>` 展示，不启用 HTML 渲染。
- `/console/` 为新建诊断：输入故障描述、环境、可选事件时间；保留本次 `conv_id` 以支持澄清后的继续提交。结果以概览、已确认事实、待验证假设、行动/审批、证据缺口、现场证据、知识来源和工具状态为主。结构化结果缺失时仍显示 Markdown 与构建状态；clarification 不渲染空诊断区域。
- `/console/history` 为令牌解锁后的历史列表，支持现有 `limit/offset`、服务、构建状态和 degraded 筛选。`/console/history/:run_id` 为详情，并在独立 tab 按需加载 `/trace`。Trace 步骤按开始时间排列，重叠时间标为并行，明确区分 failed、degraded、skipped 与 empty。
- 历史详情只展示真实持久化的 Evidence ID/source type 与 Knowledge document/chunk/source ref，并说明完整源载荷未归档；不把 Runbook 当作现场事实，也不把假设混成确认事实。
- History token 由用户在私有演示环境手动输入，仅存当前浏览器 `sessionStorage`，可锁定/清除；既不写源码、Git、构建产物，也不发送到 `/chat`。此方案不是生产级用户认证/TLS/租户隔离。

## 部署与验收

- 本地依赖与 npm 缓存位于 E 盘。先在 `frontend/` 执行 `npm ci --cache E:\Codex\cache\npm`、`npm test`、`npm run build`，再在 `app/` 执行 `docker compose up -d --no-deps --force-recreate nginx`。现有 Nginx 只读挂载 `../frontend/dist`，把根路径重定向到 `/console/`，不新增端口和跨域代理。
- 曾尝试使用多阶段 Node/Nginx 镜像，但 Docker Hub 的 Node 镜像鉴权连接超时；改用已安装的 D 盘 Node 本地构建和现有 Nginx 镜像。前端构建先于 Compose 启动是明确的部署前置条件。应用容器将来单独重建后，如代理保留旧 upstream，可重启 Nginx。
- `docker compose config --quiet` 通过。五个 Compose 服务 healthy；`/console/`、SPA 深链接及 JS 资源均为 200；`/` 返回 302；`/health`、`/docs`、`/skills`、`/monitor`、`/knowledge/stats` 仍为 200；未带 token 的 `/diagnoses` 为 401。GET `/chat`、GET `/search` 为 405，说明仍代理到只接受 POST 的后端入口。
- 前端 Vitest/React Testing Library **11 passed**：结构化事实/假设分离、clarification、degraded、diagnosis=null、审批、Trace 失败/跳过/并行、New Diagnosis 提交、History 解锁/401/筛选、详情与 Trace 独立请求、错误信息安全映射。
- Stage 1-6 后端全量离线回归在只读挂载评测案例和独立 Redis 容器下 **316 passed、0 skipped**；测试容器与网络已清理。Stage 5 approved baseline 历史快照 SHA-256 保持 `821F49BA337447CFB6AEBDDC6AE6334C4D7475919DD13B02D32651CC6816AC1F`。
- 真实浏览器经 Nginx 提交一次 demo 故障：Intent `deployment_issue`、Application 主/Database 辅，结构化诊断成功，`persistence_status=saved`，run ID `e91c724c4a4746898dbef76d505a2e3c`；事实、假设、行动审批、来源和状态均可见。桌面 1365px 与手机 390px 视口均无横向溢出。无效历史令牌在浏览器中返回未授权并重新锁定。
- 在不输出令牌的命令行验收中，经同一 Nginx 入口的授权历史列表包含该 run，详情的 `run_id` 匹配，Trace ID 一致且有 13 个步骤；这验证了代理和 History API，但不替代浏览器里输入令牌后的页面验收。

## 待验与限制

- 尚待 Owner 许可在本机浏览器输入现有私有历史令牌，才能完成浏览器中的授权历史列表、刚保存的详情及 Trace 查看。后端 History API 与前端模拟交互测试已验证，但不能把这三项称为真实浏览器端到端通过。
- Nginx 使用本地 `dist` 只读挂载；新机器需要先完成 npm 构建。普通 HTTP 和共享 token 仅适合可信私有演示。历史只存来源引用而不存完整证据原文；六案例仍是合成数据，未做生产负载、用户级权限或大型人工质量校准。
- Stage 7 目前没有已知代码 blocker，但**正式关闭仍取决于授权 History/Detail/Trace 的浏览器验收**。不自动进入简历、README 或部署美化阶段。

## 用户反馈修复与复验（2026-10-04）

- 历史页现在先用 `/diagnoses?limit=1` 验证输入令牌，成功后才解锁；401 留在输入框并说明必须使用 `ROOTLENS_HISTORY_API_TOKEN`，不能使用模型 API Key。真实令牌未写入前端或日志；浏览器中使用无效测试令牌确认了原地错误反馈。
- 澄清结果下方增加补充输入与已提供信息。补充时以原始描述加本次/先前补充组成当前请求，并沿用 `conv_id`；正常连续提问只发送新问题，新诊断清空旧会话。输入区跟随最新结果，不再需要回到页面顶部。刷新页面后的未完成澄清续接尚未实现。
- 控制台明确限定为 `demo` 模拟数据；不再让人选择尚未连接的 staging/prod。后端缺服务名且缺时间时会一次指出两项条件，并说明不能直接访问真实后台。开放式系统问题仍受当前模拟服务与数据范围限制。
- 前端 **14/14**、后端全量 **317/317** 通过；后端测试使用只读源码挂载与隔离 Redis，临时容器/网络已清理。五项 Docker 服务 healthy，approved baseline 历史快照 SHA-256 仍为 `821F49BA337447CFB6AEBDDC6AE6334C4D7475919DD13B02D32651CC6816AC1F`。
- 真实浏览器验证了三轮同页请求：`后台界面打不开` 得到服务名与时间的澄清；补充 `payment-service 从 10:05 开始报 500` 后，同一会话得到有现场证据的结构化诊断；再次询问证据缺口后得到新诊断，未刷新。错误测试令牌停留在锁定页并给出具体提示。经 Nginx 的授权 HTTP 列表、详情、Trace 均可读；浏览器中使用真实令牌的 History/Detail/Trace 验收仍待 Owner 自行输入令牌。
