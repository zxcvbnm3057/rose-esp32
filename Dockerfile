FROM node:22-alpine AS console-build

WORKDIR /build/console
COPY console/package.json console/package-lock.json ./
RUN npm ci
COPY console/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROSE_CONSOLE_DIR=/opt/rose/console \
    ROSE_DATABASE_URL=sqlite+aiosqlite:////data/rose_iot.db

WORKDIR /opt/rose
COPY requirements.docker.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY platform ./platform
COPY hardware_config.json ./hardware_config.json
COPY --from=console-build /build/console/dist ./console

WORKDIR /opt/rose/platform
EXPOSE 8000 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]