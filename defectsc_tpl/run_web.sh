#!/usr/bin/env bash
set -euo pipefail


source /src/.venv/bin/activate
exec /src/.venv/bin/python -m gunicorn defects4c_api:app \
     --worker-class uvicorn.workers.UvicornWorker \
     --bind 0.0.0.0:80


gunicorn -k uvicorn.workers.UvicornWorker --workers 8 --bind 0.0.0.0:80 main:app --timeout 600
