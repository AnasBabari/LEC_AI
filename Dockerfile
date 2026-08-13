# Stage 1: Build React Dashboard Frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Python Application Runner
FROM python:3.11-slim AS runner
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:0.5.24 /uv /bin/uv

# Copy project files and source before install
COPY pyproject.toml README.md uv.lock ./
COPY src/ /app/src/
COPY data/ /app/data/
# Install package and dependencies
RUN uv pip install --system --no-cache -e .

# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Create and switch to non-root user
RUN useradd -u 1000 -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "faultline.app:app", "--host", "0.0.0.0", "--port", "8000"]
