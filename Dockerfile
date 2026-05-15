FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "app.main:app", "--bind", "0.0.0.0:8000"]
