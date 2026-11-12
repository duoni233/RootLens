# 项目来源与贡献范围

RootLens 基于 EchoMind 运行时进行场景改造。EchoMind 提供原有的 Agent 编排、ToolManager 等基础能力。RootLens 的实现集中在运维故障诊断，包括现场证据工具、Runbook 检索与证据增强、主辅路由适配、结构化结果、故障注入与回归评测、执行轨迹、历史存储和 React 控制台。

[早期源码梳理](00-echomind-source-verified-map.md)和[场景迁移记录](02-migration-mapping.md)保留了改造背景。当前运行方式见 [RootLens 后端说明](../app/README.md)。部分运行时配置键沿用原名称以兼容已有配置。

当前仓库用于私有展示。公开再分发继承源码前，应向原作者确认许可或授权范围。
