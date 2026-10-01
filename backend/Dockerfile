FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py ./
COPY database ./database
COPY knowledge ./knowledge
COPY security ./security
COPY dataset/__init__.py ./dataset/
COPY dataset/synthetic ./dataset/synthetic
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend ./backend
COPY backend/docker-entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

RUN mkdir -p /srv/keystore /srv/models /srv/datasets /srv/storage/documents /srv/storage/external /srv/storage/signals /srv/storage/observations /srv/data \
    && useradd --system --uid 1001 painscore \
    && chown -R painscore:painscore /srv
USER painscore

EXPOSE 8000
ENTRYPOINT ["entrypoint"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
