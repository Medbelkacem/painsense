#!/bin/sh
set -e

echo "applying migrations"
alembic upgrade head

if [ -n "$BOOTSTRAP_ADMIN_EMAIL" ] && [ -n "$BOOTSTRAP_ADMIN_PASSWORD" ]; then
  python -m backend.cli bootstrap \
    --email "$BOOTSTRAP_ADMIN_EMAIL" \
    --password "$BOOTSTRAP_ADMIN_PASSWORD" \
    --name "${BOOTSTRAP_ADMIN_NAME:-Administrator}" \
    --admin || echo "administrator account already present"
else
  python -m backend.cli seed
fi

exec "$@"
