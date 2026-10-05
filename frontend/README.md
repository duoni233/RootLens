# RootLens Diagnosis Console

React/TypeScript/Vite frontend for the existing RootLens backend. It is served at `http://localhost:8081/console/` by the project's Nginx container; the backend API stays on the same origin.

## Local build and deployment

Run from `E:\code\RootLens\frontend`:

```powershell
npm ci --cache E:\Codex\cache\npm
npm test
npm run build
```

Then from `E:\code\RootLens\app`:

```powershell
docker compose config --quiet
docker compose up -d --no-deps --force-recreate nginx
```

Compose mounts `frontend/dist` read-only into the existing Nginx image. Rebuild `dist` after frontend edits. When `rootlens-app` is recreated, restart Nginx if it retains the old upstream IP. `npm run dev` runs a Vite server on port 5173 with `/chat`, `/health`, and `/diagnoses` proxied to the local backend.

The console currently queries only the `demo` synthetic dataset; selecting a real staging or production data source is not supported. Its incident fixtures are dated `2026-09-01` Asia/Shanghai. When an incident time is explicit, the form may suggest that demo date and time; the operator can edit it. A clarification response can be continued in the same page: the console sends the original description together with the supplied details using the same `conv_id`. Start a new diagnosis to clear that session. An unfinished clarification does not survive a page reload.

From a history record, **Explain saved record** is a read-only explanation of the archived structured diagnosis: it sends that diagnosis and the question to the configured model but does not query current evidence, RAG or memory. A record that stopped at clarification gets a deterministic insufficient-record explanation. **New diagnosis** is a separate `/chat` run against demo data; it carries the known service name when available, not the prior full question, conclusions or conversation ID. Neither mode edits the original history record.

History API access remains disabled by default on the backend. In a private demo, enable it in `app/.env` using a long `ROOTLENS_HISTORY_API_TOKEN`; enter that token through the console unlock form, not an LLM provider API key. The token is verified before unlocking and is kept only in browser `sessionStorage`, not in source or the Vite bundle. This is not production user authentication, TLS, or tenant isolation.
