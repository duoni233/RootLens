---
name: 基础设施故障诊断
description: 排查资源、网关和网络层异常
keywords: CPU,内存,OOM,磁盘,节点,Nginx,网关,DNS,502,503,upstream,Redis
agents: infrastructure
enabled: true
---

# 基础设施故障诊断

- 先确认受影响节点、时间范围和业务影响，再看 CPU、内存、磁盘、网络等指标。
- 比较异常前后的指标变化，并核对网关、依赖和部署事件。
- 明确区分观测到的事实与待验证的推测。
- 不得把重启、扩容或切流当作已经执行的操作；高风险动作需要人工审批。
