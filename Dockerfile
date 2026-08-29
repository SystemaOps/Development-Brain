# Software Development Brain — core runtime image (Phase 32).
# One image runs every entry point: brain-api, brain-worker, brain-scheduler,
# brainctl, and the one-shot migration.
#
#   docker build -t brain .
#   docker run --rm brain brainctl --help
#   docker run --rm brain python -m brain.bootstrap.migrate

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# uv for reproducible dependency installation.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY brain ./brain

RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000

CMD ["brain-api"]