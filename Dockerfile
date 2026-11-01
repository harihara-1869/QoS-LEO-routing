FROM --platform=linux/amd64 node:24-bookworm-slim AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM --platform=linux/amd64 ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates git python3 python3-dev python3-venv && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/leo-venv && python3 -m venv /opt/leo-ns3-venv
COPY requirements/ /tmp/requirements/
RUN /opt/leo-venv/bin/pip install -r /tmp/requirements/dashboard.txt && /opt/leo-ns3-venv/bin/pip install -r /tmp/requirements/ns3.txt
ENV LEO_NS3_PYTHON=/opt/leo-ns3-venv/bin/python PATH=/opt/leo-venv/bin:$PATH
WORKDIR /workspace
COPY . .
COPY --from=frontend /app/web/dist ./web/dist
EXPOSE 8000
CMD ["/opt/leo-venv/bin/python", "-m", "uvicorn", "dashboard.server:app", "--host", "0.0.0.0", "--port", "8000"]
