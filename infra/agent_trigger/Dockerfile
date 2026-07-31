FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY infra/agent_trigger/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY infra/agent_trigger/app ./app
COPY agent_core/agent_core ./agent_core

EXPOSE 8090
