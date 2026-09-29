# Database connection pool exhaustion Runbook

模拟处置规则，不代表当前故障的根因。DBConnectionError / connection pool exhausted 表示连接获取失败的线索。
检查 db_pool_in_use、配置的 pool limit、等待时长与活跃请求；区分应用侧连接泄漏、慢 SQL、数据库不可达和流量激增。
比对错误发生前后的连接配置、查询耗时与流量。只看到 pool in use 达到上限，不能证明数据库宕机。
收集证据后提出限流、连接生命周期检查或配置修正；不要自动扩大连接池，不要执行生产变更。缓解动作需负责人批准。
