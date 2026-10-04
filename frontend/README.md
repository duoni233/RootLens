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

History API access remains disabled by default on the backend. In a private demo, enable it using the backend configuration and a long `ROOTLENS_HISTORY_API_TOKEN`; enter that token through the console unlock form. The token is kept only in browser `sessionStorage`, not in source or the Vite bundle. This is not production user authentication, TLS, or tenant isolation.
