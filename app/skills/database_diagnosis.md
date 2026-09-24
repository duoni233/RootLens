---
name: 数据库故障诊断
description: 处理数据库连接、慢查询和事务相关故障
keywords: DBConnectionError,database,数据库,连接池,慢查询,锁等待,deadlock,SQL
agents: database
enabled: true
---

# 数据库故障诊断

- 区分连接失败、连接池耗尽、慢查询和锁等待；仅凭错误名不能断定原因。
- 优先要求错误发生时间、受影响服务、连接池使用量和数据库侧指标。
- 给出可验证的排查顺序，说明应用端与数据库端各需要什么证据。
- 不得建议未经审批的清库、重启、修改生产参数或泄露连接凭据。
