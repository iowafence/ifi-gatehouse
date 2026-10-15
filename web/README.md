# web

Next.js 15 / React 19 workspace for IFI Gatehouse: project portfolio, a PDF evidence viewer (C101 beside the review panels), Takeoff Review, the Scope / Labor / Release gates, and AI Findings. It never calls an AI service itself; it talks only to the engine through server-side proxy routes (`app/api/demo/*`).

```sh
cd web
cp .env.example .env.local        # fill ENGINE_BASE_URL, ENGINE_API_KEY, SESSION_SIGNING_SECRET, DP001_DIR
npm ci                            # also copies the pdf.js worker into public/
npm run typecheck && npm run build
npx next start -p 5071 -H 127.0.0.1
```

* `ENGINE_API_KEY` must equal the engine's. `SESSION_SIGNING_SECRET` must be at least 32 random characters. Both are server-side only.
* `DP001_DIR` is the repository's `dp001/` directory (document registry, scope draft, AI findings ledger). The PDFs are read from `samples/public-demo/dp001/` unless `DP001_DOCUMENTS_DIR` is set; each is served only if its SHA-256 matches the registry.
* The engine must run with `ENGINE_DEMO_ROUTES=1`. Without an engine the page shows "Engine unavailable"; there is no simulated mode.
* Sessions are anonymous signed cookies (12 h). The proxy allows 12 new demo projects per hour per IP, held in memory.
* The stylesheet imports DM Sans and IBM Plex Mono from Google Fonts; remove the `@import` in `app/globals.css` for a fully offline run.
