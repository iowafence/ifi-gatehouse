# api

**Status: implemented as a demonstration service.**

`server.py` is a standard-library HTTP service in front of the engine. Every request needs `X-Engine-Key`; it refuses to start without `ENGINE_API_KEY` (a separate flag exists only for isolated local smoke tests).

- Project routes: `GET /projects/{id}`, `POST /projects/{id}/scope/resolve`, `/labor/resolve`, `/release`, and `GET /health`.
- Demo mode (`ENGINE_DEMO_ROUTES=1`, called by the web tier only): `POST /demo/projects` creates an isolated project from the built-in fictional fixture, `DELETE /demo/projects/{id}` removes one, `GET /demo/portfolio` returns the static synthetic portfolio. Demo projects are owner-scoped, expire when idle, and are capped in number and in actions per project. Bodies are size-limited.
- Upload, documents and proposal routes answer `501`; they are not implemented.
- Projects are held in memory. There is no persistence and no user authentication.
