# RootLens

RootLens is a demo incident-diagnosis application built on the EchoMind agent runtime. It accepts a service incident description, retrieves **simulated** logs, metrics and deployment records, consults RootLens runbooks, selects primary/supporting agents, and returns a structured diagnosis with evidence references. It also records an execution trace and a local diagnosis history.

The current data source is `rootlens-demo:v2`, a small, internally consistent synthetic dataset. RootLens is **not connected to staging or production systems** and its six-case regression suite is not a production accuracy estimate.

## Try the local console

Prerequisites: Docker Desktop with a running engine, Docker Compose, Node.js/npm, and an Anthropic-compatible model endpoint. Copy `app/.env.example` to `app/.env` and set the model credentials there; never commit the populated file. From the repository root on an E: drive:

```powershell
cd E:\code\RootLens\frontend
npm ci --cache E:\Codex\cache\npm
npm test
npm run build

cd E:\code\RootLens\app
docker compose up -d --build
docker compose ps
```

Open [the diagnosis console](http://localhost:8081/console/) or [the API documentation](http://localhost:8081/docs). The Nginx container serves the prebuilt `frontend/dist`; rebuild it after frontend changes. The History API is disabled unless explicitly enabled in `app/.env` with a separate, long `ROOTLENS_HISTORY_API_TOKEN`. This token is **not** the model API key. Keep the console on a trusted private network: plain HTTP plus a shared token is not production authentication.

Demo input (Asia/Shanghai, simulated incident date `2026-09-01`):

> payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，帮我判断原因。

Expected *behavior*, not a guaranteed wording: the system should find the 10:00 deployment, 5xx/connection-pool evidence, route to Application with Database support, and distinguish confirmed observations from the unproven hypothesis that the release caused the fault. The event-time field can be edited. Using the computer's current date for this historical demo may return no matching evidence.

## Current request path

```text
FastAPI /chat
  -> intent and RootLens entity projection
  -> evidence gate and time-scoped log/metric/deployment tools
  -> evidence-enriched RootLens runbook retrieval
  -> one evidence-aware primary/supporting-agent route
  -> validated IncidentDiagnosis + DiagnosisTrace
  -> best-effort SQLite DiagnosisRun persistence
  -> React console (diagnosis, history, trace)
```

`/eval/run` uses the same core diagnosis path and compares observations against a separate six-case expected dataset. A saved, human-approved `stage3-v3` / `rootlens-demo:v2` baseline is retained; promotion is explicit. Test-only failure injection is not exposed through `/chat`.

History supports two different actions: **explain an archived diagnosis** (read-only; sends that saved structured diagnosis and the new question to the configured model, without fresh evidence retrieval) and **start a new diagnosis** (a new `/chat` run against demo data). An archived explanation is not a current operational finding.

## What has been verified

- Stage 5 live six-case acceptance: structured diagnosis 6/6, Judge v2 valid 6/6. These are synthetic cases, not an independent production benchmark.
- Stage 6: restart-persistent SQLite history and guarded list/detail/trace API.
- Stage 7: console and history navigation, local HTTP health, 22 frontend tests and 322 isolated backend tests after the latest follow-up changes. See [Stage 7 acceptance](docs/29-stage7-diagnosis-console-acceptance.md) for the scope and earlier test setup.
- One real-model archived-explanation API smoke test on a demo diagnosis separated facts/hypotheses/actions and did not treat deployment timing as proven causation. Browser-level final acceptance of that workflow remains an Owner check; see [closeout checklist](docs/30-stage7-closeout-and-demo.md).

## Limits and provenance

The operational evidence tools query versioned JSON fixtures, not live observability systems. Some unrelated runbooks may appear as extra RAG hits. The Judge has not been calibrated on a large human-reviewed set; no production load, outage or tenant-isolation study has been performed. History stores references rather than full immutable copies of all source records. Do not expose the current demo deployment publicly as a production service.

RootLens started from the EchoMind codebase and reuses its runtime components. RootLens-specific work includes the incident data and evidence contracts, tools, knowledge isolation, diagnosis pipeline and structured output, evaluation alignment, trace/reliability tests, persistence and console. [The source-to-target mapping](docs/02-migration-mapping.md) records that boundary. Before redistributing the inherited source publicly, confirm and comply with the original project's license/permission; no license grant is asserted here. `app/README.md` is the inherited EchoMind guide, not the current RootLens deployment guide.

For a reproducible demo and interview talking points, use [the closeout guide](docs/30-stage7-closeout-and-demo.md). Detailed stage-by-stage evidence is under `docs/`.
