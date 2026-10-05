# RootLens demo and Stage 7 closeout

Date: 2026-10-05. **Status: technical smoke accepted; Stage 7 Owner browser sign-off pending.** This page distinguishes a verified observation from a claim about general quality.

## Verification record

| Check | Result | Boundary |
| --- | --- | --- |
| Local Nginx `/health` and `/console/` | HTTP 200 on 2026-10-05 | Does not prove model quality |
| Console loads in the in-app browser | RootLens title, form and API-ready state visible | History unlock was not repeated with a real token in this check |
| Archived explanation, real model, one synthetic `payment-service` diagnosis | `POST /diagnoses/{run_id}/explain` returned `basis=saved_diagnosis`; facts, hypotheses, actions and evidence gaps were separated | API check, not a browser-click acceptance; no new evidence was fetched |
| Source comparison | The three confirmed findings, three hypotheses and three actions in the answer matched the archived structured fields; release timing was not called proven causation | One selected record and one question only |
| Frontend regression rerun | Vitest 22/22 on 2026-10-05 | Production build and backend suite were not rerun for this documentation change |
| Latest isolated backend regression recorded by the project | 322/322 | See `29-stage7-diagnosis-console-acceptance.md`; not rerun for this documentation change |

The test question asked whether v2.3.7's 10:00 deployment, followed by the 10:05 incident, proved causation. The model correctly answered **no** and requested version/configuration, connection-lifecycle, database and traffic comparisons. The archived diagnosis and question were sent to the configured provider with Owner permission. The access token and full answer are deliberately not copied into this document.

## Five-minute demo

1. Confirm Docker services and `http://localhost:8081/health`; open `http://localhost:8081/console/`.
2. Submit the synthetic `payment-service` example from the root README. Set the event time to `2026-09-01 10:05` Asia/Shanghai if it is not suggested. Show the operational Evidence IDs, three tool statuses, Runbook source, primary/supporting route, and the difference between confirmed facts and hypotheses.
3. Show a clarification case: `10:05 开始 5xx 激增，请帮我排查`. It should ask for the affected service rather than scanning every service. Supply `payment-service` in the same page, then check that a new result appears without a refresh.
4. In a trusted private demo only, unlock History with the separate history token. Open a successful record and its Trace. Do not put the token into slides, terminal output, browser recording or the repository.
5. From that record choose **解读已有记录** and ask: `哪些是已确认事实、哪些是假设？v2.3.7 一定是根因吗？` This must not start new evidence queries or create another run. Choose **重新诊断** only when new live-demo evidence is desired; it is a separate run, not a continuation of the archived conclusion.

## Owner sign-off checklist

- [ ] In the browser, unlock a successful demo history record and inspect Detail and Trace.
- [ ] In the browser, submit one archived-explanation question. Confirm it says the record is historical, separates facts from hypotheses, and does not assert deployment as root cause.
- [ ] Try **重新诊断** with a clean incident description. Confirm a new run and no duplicated archived input. This is a paid-model request and intentionally was not repeated during the one-record explanation smoke test.
- [ ] Rotate the history token previously exposed in chat before any further sharing or recorded demo. Do not record the replacement token here.
- [ ] Check original EchoMind redistribution permission/license before publishing a public fork or presenting inherited components as original work.

Stage 7 can be formally closed after the Owner confirms the browser workflow and records any quality issues. The current API smoke is encouraging but is not that sign-off.

## Interview account

**One sentence:** RootLens adapts an existing agent runtime into an evidence-grounded incident diagnosis application; it separates operational facts, reference knowledge and hypotheses, then makes the full path testable and inspectable.

**Own contribution:** describe the incident tools and versioned synthetic dataset; evidence/query contracts; RootLens RAG and memory isolation; evidence-aware routing; structured diagnosis/validator; aligned evaluation and approved baseline; Trace/fault-injection tests; SQLite history and React console. Describe EchoMind's original orchestration/ToolManager as reused and modified, not invented from zero.

**One engineering trade-off:** querying all three operational tools for a diagnostic request is simple and testable on the small demo dataset; a larger deployment would need tool selection, real provider integrations and cost/latency measurement before making that choice.

**One bad case:** the older history follow-up submitted an explanation question to `/chat` and triggered an irrelevant clarification. The fix separated read-only archive explanation from a new diagnosis; a single smoke check now verifies the distinction. Another failure was a metric summary improperly implying log state in a partial-evidence case; the v2 dataset corrected that source attribution without hiding an empty log result.

**Do not claim:** production root-cause accuracy, a production-grade authorization scheme, live staging/prod integration, large-scale Judge calibration, or ownership of the entire inherited runtime.
