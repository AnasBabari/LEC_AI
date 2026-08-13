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
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project definition and install dependencies
COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache -e .

# Copy application source and data
COPY src/ /app/src/
COPY data/ /app/data/
COPY examples/ /app/examples/

# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

EXPOSE 8000

CMD ["uvicorn", "faultline.app:app", "--host", "0.0.0.0", "--port", "8000"]
