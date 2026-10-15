# Single-container judge demo: the Python engine (loopback only) and the Next.js web tier in one image, ONE instance.
# Build from the repository root:  docker build -f hosting/Dockerfile -t gatehouse-judge-demo .
# No AMD / Evolus credential, client or hold-file bypass is in this image; replay is offline. See docs/HOSTING.md.
FROM node:22-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
COPY web/scripts ./scripts
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home app
WORKDIR /app
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY engine ./engine
COPY api ./api
COPY pricing ./pricing
COPY config/rates.example.json config/portfolio.example.json ./config/
COPY samples ./samples
COPY dp001 ./dp001
# Authentic Evolus execution evidence, baked in READ-ONLY (a hosted container has no host mounts). Byte-exact copies staged by hosting/stage_release_evidence.py; hashes in RELEASE_SHA256SUMS.
# A host or `docker run -v` mount at /app/traces or /app/cases still overrides these (local drops for new traces).
COPY release_evidence/traces ./traces
COPY release_evidence/cases ./cases
COPY release_evidence/loom ./loom_reports
COPY release_evidence/SHA256SUMS ./RELEASE_SHA256SUMS
COPY run/start_engine_dp001.py ./run/start_engine_dp001.py
COPY --from=web /build/web ./web
COPY hosting/entrypoint.sh ./entrypoint.sh
RUN chmod 0555 /app/entrypoint.sh && mkdir -p /app/traces /app/cases && chown app:app /app/web/.next && chmod -R a-w,a+rX /app/traces /app/cases /app/loom_reports /app/RELEASE_SHA256SUMS /app/dp001/independent_audits
ENV NODE_ENV=production PORT=8080 PYTHONDONTWRITEBYTECODE=1 NEXT_TELEMETRY_DISABLED=1 DP001_DIR=/app/dp001 FLIGHT_TRACE_DIR=/app/traces GATEHOUSE_CASES_DIR=/app/cases
USER app
EXPOSE 8080
CMD ["/app/entrypoint.sh"]
