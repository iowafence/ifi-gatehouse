FROM python:3.12-slim
WORKDIR /app
COPY engine ./engine
COPY api ./api
COPY config/rates.example.json ./config/rates.example.json
COPY config/portfolio.example.json ./config/portfolio.example.json
COPY samples/scope_synthetic.json ./samples/scope_synthetic.json
COPY samples/scope_generic_synthetic_pricing.json ./samples/scope_generic_synthetic_pricing.json
COPY samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx ./samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx
COPY pricing ./pricing
# Real rates: mount config/rates.local.json at runtime (never baked into the image). Set ENGINE_API_KEY.
ENV PORT=8080
USER nobody
EXPOSE 8080
CMD ["python3", "-m", "api.server"]
