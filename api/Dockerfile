# Образ rf-analytics-api. Собирается в Actions (deploy-stack.yml) из корня репозитория:
#   docker build -f api/Dockerfile -t rf-analytics-api:<tag> .
# Конфиг (семантический слой, таксономия, гео) вшит в образ — версия API = версия конфига.
FROM ghcr.io/astral-sh/uv:0.11.3 AS uv

FROM python:3.12.7-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    RF_MARTS_DIR=/marts RF_CONFIG_DIR=/config
WORKDIR /app
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY api/src ./src
RUN uv sync --frozen --no-dev --no-editable && rm /usr/local/bin/uv
COPY config/metrics.yaml config/taxonomy.yaml /config/
COPY config/geo/regions.csv config/geo/regions.geojson /config/geo/
USER 65534:65534
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["/app/.venv/bin/uvicorn", "--factory", "rf_api.app:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
