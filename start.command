#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12
fi
uv pip install -r requirements.lock.txt
if curl --fail --silent http://127.0.0.1:8000/api/photos > /dev/null; then
  open http://127.0.0.1:8000
  exit 0
fi
(
  for attempt in {1..50}; do
    if curl --fail --silent http://127.0.0.1:8000/api/photos > /dev/null; then
      open http://127.0.0.1:8000
      break
    fi
    sleep 0.2
  done
) &
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
