# One image for api, worker and the three MCP servers (different commands in docker-compose).
FROM node:20-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npx vite build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore FASTEMBED_CACHE=/models
WORKDIR /app
COPY pyproject.toml README.md ./
COPY agent agent
COPY apps/api apps/api
COPY apps/__init__.py apps/__init__.py
COPY common common
COPY rag rag
COPY mcp_servers mcp_servers
COPY worker worker
COPY evals evals
COPY scripts scripts
COPY gigsim gigsim
COPY data/personas data/personas
COPY data/gigsim_seed data/gigsim_seed
COPY data/policy_pack data/policy_pack
RUN pip install --no-cache-dir -e . \
 && python -c "from rag.index.models import _embedder, _reranker; _embedder(); _reranker()"
COPY --from=web /web/dist apps/web/dist
EXPOSE 8000
# Render/Railway inject $PORT; docker-compose overrides the command anyway.
CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
