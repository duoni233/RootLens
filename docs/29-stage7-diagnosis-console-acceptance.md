# Stage 7 RootLens Diagnosis Console Acceptance

日期：2026-10-04，更新至 2026-10-05。状态：控制台已部署；历史列表、详情、Trace 与追问入口已验证。历史解读模式已部署并通过离线测试，真实模型回答仍待 Owner 验收；Stage 7 尚未正式关闭。

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

- Owner 已在本机浏览器解锁历史；授权列表、详情与 Trace 浏览器查看已通过。基于历史的新诊断入口及上下文展示已通过，但尚未提交真实模型追问，不宣称新回复质量已验收。
- Nginx 使用本地 `dist` 只读挂载；新机器需要先完成 npm 构建。普通 HTTP 和共享 token 仅适合可信私有演示。历史只存来源引用而不存完整证据原文；六案例仍是合成数据，未做生产负载、用户级权限或大型人工质量校准。
- Stage 7 目前没有已知代码 blocker，但**正式关闭仍取决于 Owner 对新追问工作流的最终确认**。不自动进入简历、README 或部署美化阶段。

## 用户反馈修复与复验（2026-10-04）

- 历史页现在先用 `/diagnoses?limit=1` 验证输入令牌，成功后才解锁；401 留在输入框并说明必须使用 `ROOTLENS_HISTORY_API_TOKEN`，不能使用模型 API Key。真实令牌未写入前端或日志；浏览器中使用无效测试令牌确认了原地错误反馈。
- 澄清结果下方增加补充输入与已提供信息。补充时以原始描述加本次/先前补充组成当前请求，并沿用 `conv_id`；正常连续提问只发送新问题，新诊断清空旧会话。输入区跟随最新结果，不再需要回到页面顶部。刷新页面后的未完成澄清续接尚未实现。
- 控制台明确限定为 `demo` 模拟数据；不再让人选择尚未连接的 staging/prod。后端缺服务名且缺时间时会一次指出两项条件，并说明不能直接访问真实后台。开放式系统问题仍受当前模拟服务与数据范围限制。
- 前端 **14/14**、后端全量 **317/317** 通过；后端测试使用只读源码挂载与隔离 Redis，临时容器/网络已清理。五项 Docker 服务 healthy，approved baseline 历史快照 SHA-256 仍为 `821F49BA337447CFB6AEBDDC6AE6334C4D7475919DD13B02D32651CC6816AC1F`。
- 真实浏览器验证了三轮同页请求：`后台界面打不开` 得到服务名与时间的澄清；补充 `payment-service 从 10:05 开始报 500` 后，同一会话得到有现场证据的结构化诊断；再次询问证据缺口后得到新诊断，未刷新。错误测试令牌停留在锁定页并给出具体提示。经 Nginx 的授权 HTTP 列表、详情、Trace 均可读；浏览器中使用真实令牌的 History/Detail/Trace 验收仍待 Owner 自行输入令牌。

## 历史检索与追问补齐（2026-10-05）

- Owner 已能在浏览器解锁并查看历史列表；单条 Detail/Trace 仍需完成最终浏览器验收。历史访问令牌曾在聊天中暴露，需在私有演示完成后轮换；文档和仓库不记录其值。401 前端文案改为中性提示，不再把未授权直接归因于使用了模型 Key。
- 历史列表的服务名改为大小写不敏感的字面包含匹配，`pay` 可匹配 `payment-service`，`%` 等通配字符按普通文本处理。新增“服务待确认”和“待补充信息”筛选；状态选项改为中文，提供一键清空筛选。`degraded` 仍表示诊断执行的局部降级，不等于 clarification。
- 详情展示持久化的原始问题。旧版“基于此记录追问”曾把旧问题、摘要和新追问合成一次新诊断；Owner 真实体验发现它会把解释性问题送入取证澄清，历史上的复合输入还会反复嵌套。该实现已由下节所述的双模式替代。旧记录内容不改写。
- 后端 Repository/API 只增加历史过滤参数，不改诊断主链、模型、数据集或 baseline。前端 17/17、生产构建通过；后端先在断网容器获得 314 passed、3 skipped，随后使用独立内部网络和临时 Redis 完成 **317/317 passed**，临时容器与网络已清理。
- 仅重建 RootLens 应用与 Nginx，五服务保持健康。经同源 Nginx 的真实查询：`service_name=pay` 返回 5 条、`service_missing=true` 返回 16 条、`clarification_required=true` 返回 10 条；返回项逐一满足过滤条件。浏览器验证 `pay` 与“服务待确认 + 待补充信息”筛选、清空筛选、详情原问题、Trace 的 13 步以及从详情进入新追问页。未为验收调用付费模型或创建新诊断。
- Approved RootLens baseline pointer 与 immutable history 快照 SHA-256 仍相同，且保持 Stage 5 验收哈希 `821F49BA337447CFB6AEBDDC6AE6334C4D7475919DD13B02D32651CC6816AC1F`。先前将 EchoMind 通用 `data/eval/baseline.json` 与该 RootLens 快照哈希比较是不对应的对象，并非 baseline 被改动。

## 历史追问分流与事件时间修复（2026-10-05）

- Owner 用真实页面发现：对历史诊断问“哪些是事实、哪些是假设”却得到“需要补充信息”。原因是旧追问被包装成新故障诊断，QueryContext 在 RAG 之前因多个时间而澄清；不是知识库文档数量直接导致。
- 历史入口现在分为“解读已有记录”和“重新诊断”。前者新增受 `X-RootLens-History-Token` 保护的 `POST /diagnoses/{run_id}/explain`，只传已保存的结构化诊断和问题给当前配置模型；不调用 Intent、取证工具、RAG、Memory，不新增 DiagnosisRun，不把用户补充写进知识库。澄清记录或缺少有效结构化诊断时，确定性告知档案不足，不调用模型。源记录没有完整原始日志，回答不能据此声称掌握日志正文或当前状态；前端显式告知模型传输边界。
- “重新诊断”仍使用 `/chat`，只从来源记录带入可用的服务名，不自动复制旧问题或旧结论，不沿用旧 `conv_id`。用户需描述要重新调查的故障；原记录仍可查看。已有被旧版拼接而变长的历史输入在页面折叠展示，档案原文不篡改。
- demo 时间控件在文本中识别出明确故障时间时自动建议日期/时间，并允许覆盖；未写日期时使用已标注的 `2026-09-01` demo 样本日期，不把电脑今天误当成旧模拟故障日期。无时间或有歧义时留空。后端仅在显式 `anchor_time` 与候选时间一致时允许它消除“10:05 故障、10:00 发布”的歧义，不一致仍要求澄清。
- 隔离测试：前端 **22/22**，后端定向历史接口 **17/17**、时间与历史联合 **40/40**，最终隔离 Redis 的后端全量 **322/322** 通过。未更改运行数据、RAG、Router、Judge、评测标签或 approved baseline。应用与 Nginx 已重建；五个 Compose 服务 healthy，控制台经本机 HTTP 返回 200。
- 真实历史令牌下的解读 POST 被安全审查阻止，因为档案可能被发给配置模型；没有绕过。In-app Browser 在 Docker 重建后无法打开 localhost（本机 HTTP 检查成功），因此新版界面的最终视觉和真实模型回答仍待 Owner 在浏览器验收。不得把离线测试等同于真实解读质量。
