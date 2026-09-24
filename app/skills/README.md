# RootLens Skills 文档

RootLens 启动时会从 `ECHOMIND_SKILLS_DIR` 读取 Skills，并在匹配用户请求时注入到对应 Agent 的 system prompt。环境变量名暂沿用原项目。

当前内置四类 Skills：

```text
skills/operations_triage.md         # 告警分诊
skills/application_diagnosis.md     # 应用故障
skills/database_diagnosis.md        # 数据库故障
skills/infrastructure_diagnosis.md  # 基础设施故障
```

## Skill 文件格式

Skill 可以直接放在 skills 目录，也可以使用独立目录和 `SKILL.md`：

```text
skills/<skill_name>.md
```

文件顶部使用简单 front matter：

```markdown
---
name: 应用服务故障诊断
description: 根据服务症状、版本和错误日志提出可验证的诊断步骤
keywords: service,5xx,500,报错,发布,日志
agents: application
enabled: true
---
```

字段说明：

- `name`：Skill 展示名称，会出现在注入给模型的 prompt 中。
- `description`：简短说明，方便 `/skills` 接口排查。
- `keywords`：触发关键词，用户消息命中后才注入；多个关键词用英文逗号或中文逗号分隔均可。
- `agents`：适用 Agent，可填 `general_ops`、`application`、`database`、`infrastructure`，多个值用逗号分隔。
- `enabled`：是否启用，支持 `true/false`。

## 编写要求

- 重要规则放在文档前半部分，因为过长内容会按 prompt 预算截断。
- 一类 Skill 只描述一个诊断领域，不混入其他领域的操作规范。
- 区分事实和假设，说明验证方式。
- 高风险操作只给出建议，执行前需要人工确认。

## 热加载

修改 Skill 文件后，不需要重启服务，调用：

```bash
curl -X POST http://localhost:8000/skills/reload
```

查看加载结果和解析错误：

```bash
curl http://localhost:8000/skills
```
