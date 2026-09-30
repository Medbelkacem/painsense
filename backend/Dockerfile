FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY migrations ./migrations
COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

# The keystore, the trained artifacts, the generated datasets and the uploaded documents
# are all state. They belong on volumes, not in the image.
RUN mkdir -p /srv/keystore /srv/models /srv/datasets /srv/storage/documents \
    && useradd --system --uid 1001 painscore \
    && chown -R painscore:painscore /srv
USER painscore

EXPOSE 8000
ENTRYPOINT ["entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
