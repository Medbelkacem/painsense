#!/bin/sh
# The schema is brought up to date before the first request, so a fresh volume and an
# upgraded image both end up in the same place.
set -e

echo "applying migrations"
alembic upgrade head

if [ -n "$BOOTSTRAP_ADMIN_EMAIL" ] && [ -n "$BOOTSTRAP_ADMIN_PASSWORD" ]; then
  python -m app.cli bootstrap \
    --email "$BOOTSTRAP_ADMIN_EMAIL" \
    --password "$BOOTSTRAP_ADMIN_PASSWORD" \
    --name "${BOOTSTRAP_ADMIN_NAME:-Administrator}" \
    --admin || echo "administrator account already present"
else
  python -m app.cli seed
fi

exec "$@"
