FROM python:3.11-slim

ENV TZ=Asia/Colombo \
    PYTHONUNBUFFERED=1 \
    CONFIG_PATH=/opt/data/config.yaml

# System deps: tzdata (for TZ), nodejs/npm (npx-based MCP servers), curl (uv installer)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# uv / uvx — used to run Python-based MCP servers (e.g. mcp-server-fetch)
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /opt/data
VOLUME ["/opt/data"]

CMD ["bash", "start.sh"]
