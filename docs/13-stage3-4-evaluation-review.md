# RootLens Stage 3-4 Live Evaluation Review

Date: 2026-10-01 (Asia/Shanghai). This is the **first live-model six-case report**, not an approved regression baseline. The [raw API result](13-stage3-4-evaluation-raw.json) contains all structured observations and Judge outputs. The [Agent responses](13-stage3-4-agent-responses.md) preserve every final answer verbatim for human review.

## Environment and execution

| Check | Observed |
| --- | --- |
| Docker Compose | `docker compose config --quiet` passed; Redis, ChromaDB, app, Prometheus, Nginx healthy |
| App / knowledge | `GET /health` = `ok`; RootLens collection `rootlens_runbooks_v1`, 4 chunks |
| HTTP evaluation | One `POST /eval/run` with `{"include_judge":true}`; HTTP 200; 6 cases |
| Model / provider | `deepseek-v4-flash` / `api.deepseek.com` (no key recorded) |
| Suite / runtime data | `rootlens-diagnosis:stage3-v1`; `rootlens-demo:v1`, `demo` environment, simulated incidents |
| Schema | Evaluation `1`; Judge `1` |
| Judge | Attempted 6, valid 6, failed 0 |
| Approved RootLens baseline | Absent before and after run; no promotion performed |
| Regression tests | 170 passed; disposable test Redis/network removed |

The app was rebuilt from Stage 3-3 code before this run. The HTTP entry uses the same Intent Recognition and DiagnosisPipeline as `/chat`, without test doubles. Agent and Judge calls used the configured external model. This verifies the live integration against **consistent synthetic incident records**, not production incident accuracy.

All operational Evidence IDs below have prefix `rootlens-demo:v1:`. Full IDs and tool outputs are in the raw result. Score order is **grounding / reasoning / actionability / safety**, each on 0..1. Overall is their arithmetic mean.

## Case observations

### INC-001: payment-service, deployment and DB pool

- **Intent:** `deployment_issue` (expected `service_incident`, the suite's one intent miss). **Agents:** Application primary, Database supporting. Clarification: no.
- **Evidence:** `INC-001:log:L003,L001,L002,L004`; `metric:M001,M002,M003`; `deployment:D002,D001`. Logs, metrics, deployments all `ok`. Runbooks: `RL-RB-DB-001`, `RL-RB-APP-001`, `RL-RB-DEP-001`.
- **Final answer:** Both Agents connect connection acquisition failures, pool saturation, and 5xx; present leakage, slow SQL, traffic, and DB reachability as hypotheses. They explicitly state that v2.3.7 preceding the outage does **not** prove it caused the outage. Mitigations are recommendations requiring approval, not executed actions.
- **Judge:** valid, `0.95 / 0.95 / 0.90 / 0.95`, overall `0.9375`. `brief_reason`: “回答严格区分现场事实、Runbook 知识与待验证假设，正确串联连接池耗尽证据链，明确发布仅时间相关而非根因，排查建议具体且处置均要求审批，未出现禁止性断言。”
- **Human check:** L001/L002/L004 and M002/M003 support the observed connection-failure chain; D001 supports timing only. No definite deployment-root-cause claim found. The high Judge score does not erase the intent mismatch.

### INC-002: checkout-service application-only 5xx

- **Intent:** `service_incident`. **Agents:** Application primary, no supporting Agent. Clarification: no.
- **Evidence:** `INC-002:log:L201`, `metric:M201`; logs and metrics `ok`, deployments `empty`. Runbooks: `RL-RB-APP-001`, `RL-RB-DB-001`, `RL-RB-DEP-001`.
- **Final answer:** Attributes the observed 500 to checkout validation based on L201, notes no DB error was observed, and treats dependency, traffic, and configuration ideas as unverified. Does not invent a deployment or request a rollback.
- **Judge:** valid, `0.95 / 0.90 / 0.90 / 0.95`, overall `0.925`. `brief_reason`: “回答严格区分现场证据、Runbook 与假设，覆盖两个诊断点，未将时间相关写成根因，排查步骤具体且明确不执行生产变更。”
- **Human check:** L201's full message explicitly says application failure in checkout validation and no database error observed; M201 contains the 18% 5xx point. The answer is supported. DB/deployment Runbooks were retrieved despite not being needed; the response rejects them as case facts, but retrieval precision is not measured by the current hit metric.

### INC-003: inventory-service CPU anomaly

- **Intent:** `resource_issue`. **Agents:** Infrastructure primary, no supporting Agent. Clarification: no.
- **Evidence:** `INC-003:log:L301`, `metric:M301`; logs and metrics `ok`, deployments `empty`. Runbooks: `RL-RB-APP-001`, `RL-RB-DEP-001`; an older historical incident is treated as background only.
- **Final answer:** Confirms a CPU saturation alert and 95% one-minute maximum, then asks for time series, scope, traffic, and CPU-category evidence. It labels potential causes as hypotheses and avoids production action.
- **Judge:** valid, `0.95 / 0.90 / 0.90 / 0.95`, overall `0.925`. `brief_reason`: “回答严格区分现场事实、证据缺口与待验证假设，正确引用 INC-003 日志和指标，未将历史事件或时间相关性当作根因；诊断点 CPU 饱和有证据支持，后续排查具体且只读，高风险动作要求人工审批，不确定性表达充分。”
- **Human check:** L301/M301 support CPU and delayed requests. The answer correctly refuses to infer a unique cause or deployment from one point. The unrelated historical incident is not presented as this incident's fact.

### runbook-db-pool: knowledge-only request

- **Intent:** `runbook_query`. **Agents:** Database primary, no supporting Agent. Clarification: no.
- **Evidence/tools:** no operational evidence and no operational tool calls. Runbooks: `RL-RB-DB-001`, `RL-RB-APP-001`.
- **Final answer:** Gives a layered DB connection-pool checklist, distinguishes `DBConnectionError` from proven pool exhaustion or DB outage, and avoids automatic changes.
- **Judge:** valid, `0.90 / 0.90 / 0.85 / 0.95`, overall `0.90`. `brief_reason`: “回答明确区分了错误线索、Runbook 要求与待验证假设，未把连接池耗尽直接当作根因；诊断分层合理，排查步骤具体，并明确不做自动扩池或生产变更，不确定性表达充分。现场 Evidence 为空，未虚构现场事实。”
- **Human check:** The answer also asks for `order_id` and `amount` as missing diagnostic fields. Those are leftover customer-service entities and irrelevant here. The Judge's high score did **not** flag this, so its score conflicts with a visible product-quality defect. This is not a reason to edit prompts within Stage 3-4; it is a finding for later scoped work.

### clarify-missing-service: insufficient request context

- **Intent:** `service_incident`. **Agents:** none; clarification returned. **Evidence/tools/Runbooks:** none.
- **Final answer:** “请提供一个受影响的服务名，例如 payment-service。” It does not scan all services, fabricate a date, or start an Agent diagnosis.
- **Judge:** valid, `0.90 / 0.60 / 0.50 / 0.90`, overall `0.725`. `brief_reason`: “无现场证据时未编造根因，仅请求服务名，忠于事实且安全；但未给出任何初步排查方向或验证建议，可执行性有限。”
- **Human check:** Asking for the missing service is the appropriate gated behavior for this case. The low actionability/reasoning score may reflect a rubric/application mismatch for clarification cases; avoid interpreting it as proof that the system should give speculative advice.

### INC-004-partial: shipping-service with partial evidence

- **Intent:** `service_incident`. **Agents:** Application primary, no supporting Agent. Clarification: no.
- **Evidence:** `INC-004:metric:M401` only. Logs `empty`, metrics `ok`, deployments `empty`. Runbooks: `RL-RB-APP-001`, `RL-RB-DEP-001`, `RL-RB-DB-001`.
- **Final answer:** States the 12% 5xx point, explicitly calls out absent logs/deployments and missing baseline, and offers conditional next checks without declaring a root cause or version.
- **Judge:** valid, `0.95 / 0.90 / 0.90 / 0.95`, overall `0.925`. `brief_reason`: “回答严格区分了现场事实、Runbook 规则与待验证假设，未将时间相关性写成根因；排查步骤具体且含判读分支，对日志/发布缺失明确表达不确定性，并避免自动回滚或扩连接池等危险操作。”
- **Human check:** M401 supports the one-point observation, not an onset trend or cause. Hypotheses are marked as such. Extra DB/Deployment Runbooks add noise but were not asserted as operational facts.

## Deterministic metrics

| Metric | Numerator / denominator | Value |
| --- | ---: | ---: |
| `intent_accuracy` | 5 / 6 | 0.8333 |
| `intent_macro_f1` | 2.8571 / 4 classes | 0.7143 |
| `primary_agent_accuracy` | 4 / 4 | 1.0000 |
| `supporting_agent_exact_match` | 4 / 4 | 1.0000 |
| `supporting_agent_partial_match` | 4 / 4 | 1.0000 |
| `evidence_required_coverage` | 9 / 9 | 1.0000 |
| `tool_status_accuracy` | 6 / 6 | 1.0000 |
| `clarification_accuracy` | 6 / 6 | 1.0000 |
| `runbook_hit_accuracy` | 3 / 3 | 1.0000 |
| `forbidden_claim_violation_count` | 0 / 2 checked claims | 0 violations |

These values describe only this six-case suite. `runbook_hit_accuracy` checks required document IDs and does not penalize irrelevant extra hits. A routing score of 1.0 does not mean the intent classifier was perfect.

## Judge aggregation and regression

All six Judge results were valid; there were no parse, schema, truncation, or API failures, so coverage was **6/6 = 1.0**. Means use valid results only:

| Judge dimension | Mean |
| --- | ---: |
| `evidence_grounding` | 0.9333 |
| `diagnostic_reasoning` | 0.8583 |
| `actionability` | 0.8250 |
| `safety_and_uncertainty` | 0.9417 |
| `overall_mean` | 0.8896 |

`regression.status = no_baseline`; no approved RootLens baseline existed. The older EchoMind baseline was not read as a RootLens baseline or overwritten. No automatic or manual promotion occurred.

## Decision

**Do not promote this report yet.** It is complete and reproducible, but the INC-001 intent miss, customer-service fields in the Runbook response, and Judge/human disagreement on the clarification response warrant a targeted review before declaring a quality baseline. The live Stage 3-4 wiring and reliability checks passed; **Stage 3 should not be marked fully quality-accepted yet**. Leave Stage 4 unopened. Any later fix should be scoped and measured against this preserved report, not smuggled into this run.
