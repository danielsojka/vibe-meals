#!/bin/sh
set -e

if [ ! -f "$MEALPLANNER_DB" ]; then
    echo "No database found, seeding example data..."
    python seed.py || echo "Seed failed (starting with empty database)"
fi

exec python -m uvicorn app:app --host 0.0.0.0 --port 8000
