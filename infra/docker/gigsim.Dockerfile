FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.12 "uvicorn[standard]==0.34.2" httpx==0.28.1 pydantic==2.11.4
COPY gigsim gigsim
COPY data/gigsim_seed data/gigsim_seed
ENV GIGSIM_SEED_DIR=/app/data/gigsim_seed
EXPOSE 8081
CMD ["uvicorn", "gigsim.app:app", "--host", "0.0.0.0", "--port", "8081"]
