#!/usr/bin/env bash
set -euo pipefail

venv_candidates=()
if [[ -n "${DEFECTS4C_VENV:-}" ]]; then
    venv_candidates+=("${DEFECTS4C_VENV}")
fi
venv_candidates+=("/opt/defects4c-venv" "/src/.venv")

for venv_dir in "${venv_candidates[@]}"; do
    if [[ -f "${venv_dir}/bin/activate" ]]; then
        # shellcheck disable=SC1090
        source "${venv_dir}/bin/activate"
        break
    fi
done

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "No usable Python environment found. Set DEFECTS4C_VENV or create /opt/defects4c-venv." >&2
    exit 1
fi

#exec /src/.venv/bin/python -m gunicorn defects4c_api:app \
#     --worker-class uvicorn.workers.UvicornWorker \
#     --bind 0.0.0.0:80


gunicorn -k uvicorn.workers.UvicornWorker --workers 8 --bind 0.0.0.0:80 new_main:app --timeout 600
